"""Operational features: alert delivery, expectancy, stale cleanup, backoff."""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

import pytest

import config
import notifications
from analysis import signals
from data import market_data
from simulator.demo_account import DemoAccount


# --------------------------------------------------------------------------- #
# Alert delivery
# --------------------------------------------------------------------------- #
def test_delivery_is_off_by_default(monkeypatch):
    monkeypatch.delenv(notifications.TELEGRAM_TOKEN_ENV, raising=False)
    monkeypatch.delenv(notifications.TELEGRAM_CHAT_ENV, raising=False)
    assert notifications.deliver({"id": 1, "title": "x"}, {}) is None


def test_delivery_reports_missing_credentials(monkeypatch):
    monkeypatch.delenv(notifications.TELEGRAM_TOKEN_ENV, raising=False)
    monkeypatch.delenv(notifications.TELEGRAM_CHAT_ENV, raising=False)
    result = notifications.deliver({"id": 7, "title": "BUY", "message": "m"}, {"telegram": True})
    assert result is not None
    assert result["ok"] is False and result["skipped"] is True
    assert "in-app alert was saved" in result["error"]


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _drain(timeout: float = 5.0) -> bool:
    """Wait until the background worker has finished every queued message."""
    return _wait_until(lambda: notifications._QUEUE.unfinished_tasks == 0, timeout)


def test_delivery_sends_labelled_message(monkeypatch):
    monkeypatch.setenv(notifications.TELEGRAM_TOKEN_ENV, "test-token")
    monkeypatch.setenv(notifications.TELEGRAM_CHAT_ENV, "123")
    sent: list[str] = []
    monkeypatch.setattr(notifications, "send_telegram",
                        lambda text, timeout=8.0: sent.append(text) or {"ok": True})
    result = notifications.deliver(
        {"id": 3, "title": "SELL signal · EURUSD=X", "message": "quality 80"},
        {"telegram": True},
    )
    assert result["ok"] is True and result["queued"] is True
    assert _wait_until(lambda: sent)
    assert "DEMO ONLY" in sent[0] and "EURUSD=X" in sent[0]
    assert _drain()
    report = notifications.delivery_report()
    assert report["last"]["ok"] is True
    assert report["last"]["alert_id"] == 3


def test_delivery_does_not_block_the_caller(monkeypatch):
    """A slow Bot API call must not stall the scan that queued the alert."""
    monkeypatch.setenv(notifications.TELEGRAM_TOKEN_ENV, "test-token")
    monkeypatch.setenv(notifications.TELEGRAM_CHAT_ENV, "123")
    release = threading.Event()
    started = threading.Event()

    def slow(text, timeout=8.0):
        started.set()
        release.wait(3.0)
        return {"ok": True}

    monkeypatch.setattr(notifications, "send_telegram", slow)
    begin = time.perf_counter()
    result = notifications.deliver(
        {"id": 4, "title": "BUY", "message": "slow"}, {"telegram": True},
    )
    elapsed = time.perf_counter() - begin
    assert elapsed < 0.2, f"deliver blocked for {elapsed:.2f}s"
    assert result["queued"] is True
    assert started.wait(2.0)
    release.set()
    assert _drain()


def test_failing_send_is_contained_and_logged(monkeypatch, caplog):
    monkeypatch.setenv(notifications.TELEGRAM_TOKEN_ENV, "test-token")
    monkeypatch.setenv(notifications.TELEGRAM_CHAT_ENV, "123")

    def boom(text, timeout=8.0):
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(notifications, "send_telegram", boom)
    with caplog.at_level(logging.WARNING):
        result = notifications.deliver(
            {"id": 5, "title": "SELL", "message": "failure path"}, {"telegram": True},
        )
        assert result["queued"] is True
        assert _drain()
    assert "telegram delivery failed" in caplog.text.lower()
    assert "test-token" not in caplog.text
    report = notifications.delivery_report()
    assert report["failed"] >= 1
    assert report["last"]["ok"] is False
    assert "telegram exploded" in report["last"]["error"]


def test_test_message_reports_missing_credentials(monkeypatch):
    monkeypatch.delenv(notifications.TELEGRAM_TOKEN_ENV, raising=False)
    monkeypatch.delenv(notifications.TELEGRAM_CHAT_ENV, raising=False)
    result = notifications.send_test_message()
    assert result["ok"] is False
    assert "not configured" in result["error"]
    assert "Nothing was sent" in result["error"]
    assert notifications.delivery_report()["last"]["alert_id"] == "test"


def test_test_message_runs_through_the_worker(monkeypatch):
    monkeypatch.setenv(notifications.TELEGRAM_TOKEN_ENV, "test-token")
    monkeypatch.setenv(notifications.TELEGRAM_CHAT_ENV, "123")
    sent: list[str] = []
    monkeypatch.setattr(notifications, "send_telegram",
                        lambda text, timeout=8.0: sent.append(text) or {"ok": True})
    result = notifications.send_test_message(timeout=3.0)
    assert result["ok"] is True
    assert result["alert_id"] == "test"
    assert any("Manual delivery test" in text for text in sent)
    assert notifications.delivery_report()["sent"] >= 1


def test_delivery_attempts_are_persisted_and_scoped(db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", db.path)
    monkeypatch.delenv(notifications.TELEGRAM_TOKEN_ENV, raising=False)
    monkeypatch.delenv(notifications.TELEGRAM_CHAT_ENV, raising=False)
    notifications.send_test_message(user_id=1)
    notifications.send_test_message(user_id=2)
    rows_one = db.list_delivery_attempts(1)
    assert len(rows_one) == 1
    assert rows_one[0]["ok"] == 0
    assert "not configured" in rows_one[0]["error"]
    assert len(db.list_delivery_attempts(2)) == 1
    assert db.list_delivery_attempts(3) == []


def test_delivery_history_is_capped_per_user(db):
    from database.database import DELIVERY_HISTORY_LIMIT
    for index in range(DELIVERY_HISTORY_LIMIT + 5):
        db.add_delivery_attempt({"user_id": 5, "alert_id": index, "ok": index % 2})
    db.add_delivery_attempt({"user_id": 6, "alert_id": "test", "ok": False})
    rows = db.list_delivery_attempts(5, limit=DELIVERY_HISTORY_LIMIT + 10)
    assert len(rows) == DELIVERY_HISTORY_LIMIT
    assert rows[0]["alert_id"] == str(DELIVERY_HISTORY_LIMIT + 4)
    assert rows[-1]["alert_id"] == "5"
    assert len(db.list_delivery_attempts(6)) == 1


def test_successful_delivery_is_persisted(db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", db.path)
    monkeypatch.setenv(notifications.TELEGRAM_TOKEN_ENV, "test-token")
    monkeypatch.setenv(notifications.TELEGRAM_CHAT_ENV, "123")
    monkeypatch.setattr(notifications, "send_telegram",
                        lambda text, timeout=8.0: {"ok": True})
    result = notifications.send_test_message(user_id=4, timeout=3.0)
    assert result["ok"] is True
    rows = db.list_delivery_attempts(4)
    assert len(rows) == 1
    assert rows[0]["ok"] == 1 and rows[0]["alert_id"] == "test"


def test_full_queue_drops_extra_messages_without_blocking(monkeypatch):
    """The queue is bounded: overflow is reported, never blocking the scan."""
    monkeypatch.setenv(notifications.TELEGRAM_TOKEN_ENV, "test-token")
    monkeypatch.setenv(notifications.TELEGRAM_CHAT_ENV, "123")
    release = threading.Event()
    started = threading.Event()

    def blocked(text, timeout=8.0):
        started.set()
        release.wait(10.0)
        return {"ok": True}

    monkeypatch.setattr(notifications, "send_telegram", blocked)
    try:
        assert notifications.deliver({"id": 0, "title": "BUY"}, {"telegram": True})["queued"]
        assert started.wait(2.0)
        begin = time.perf_counter()
        results = [
            notifications.deliver({"id": index, "title": "BUY"}, {"telegram": True})
            for index in range(60)
        ]
        elapsed = time.perf_counter() - begin
        dropped = [item for item in results if not item.get("queued")]
        assert elapsed < 1.0, f"enqueueing blocked for {elapsed:.2f}s"
        assert dropped, "bounded queue should report overflow"
        assert all("queue is full" in item["error"].lower() for item in dropped)
    finally:
        release.set()
        assert _drain(10.0)


def test_delivery_status_never_exposes_token(monkeypatch):
    monkeypatch.setenv(notifications.TELEGRAM_TOKEN_ENV, "super-secret")
    monkeypatch.setenv(notifications.TELEGRAM_CHAT_ENV, "42")
    status = notifications.delivery_status()
    assert status["telegram_configured"] is True
    assert "super-secret" not in str(status)


# --------------------------------------------------------------------------- #
# Expectancy
# --------------------------------------------------------------------------- #
def _row(label="BUY", outcome="TP hit", quality=90, timeframe="H1", symbol="EURUSD=X"):
    return {
        "label": label, "status": "Closed" if label in {"BUY", "SELL"} else "No trade",
        "outcome": outcome, "quality": quality,
        "timeframe": timeframe, "symbol": symbol,
        "entry_ref": 100.0, "tp": 110.0, "sl": 95.0,
    }


def test_r_multiple_uses_simulated_risk():
    assert signals.r_multiple(_row(outcome="TP hit")) == pytest.approx(2.0)
    assert signals.r_multiple(_row(outcome="SL hit")) == pytest.approx(-1.0)
    assert signals.r_multiple(_row(outcome="TP hit") | {"status": "Open"}) is None


def test_performance_expectancy_and_breakdown():
    rows = [
        _row(outcome="TP hit", quality=92),
        _row(outcome="SL hit", quality=92),
        _row(outcome="TP hit", quality=70, timeframe="H4"),
        _row(label="WAIT", outcome="", quality=50),
    ]
    stats = signals.signal_performance(rows)
    assert stats["resolved"] == 3
    assert stats["sample_size"] == 3
    assert stats["expectancy_r"] == pytest.approx((2.0 - 1.0 + 2.0) / 3)
    assert stats["profit_factor"] == pytest.approx(4.0)
    bands = {item["name"]: item for item in stats["breakdown"]["quality"]}
    assert bands["90–100"]["resolved"] == 2
    assert bands["90–100"]["avg_r"] == pytest.approx(0.5)
    assert {item["name"] for item in stats["breakdown"]["timeframe"]} == {"H1", "H4"}


# --------------------------------------------------------------------------- #
# Stale simulated positions
# --------------------------------------------------------------------------- #
def test_stale_position_is_closed_at_a_real_mark(db):
    account = DemoAccount.get_or_create(db, "Stale Demo", config.DEMO_STARTING_BALANCE)
    trade, problems = account.open_position(
        symbol="EURUSD=X", market="forex", side="Long", quantity=1.0,
        price=1.10, tp=1.20, sl=1.00, slot=1,
        when=config.utcnow() - timedelta(days=config.DEMO_MAX_OPEN_DAYS + 2),
    )
    assert problems == [] and trade is not None
    results = account.close_stale({"EURUSD=X": 1.12})
    assert results and results[0]["result"] == "closed"
    closed = account.closed_positions()[0]
    assert closed.exit_price == pytest.approx(1.12)
    assert "auto-closed" in closed.notes


def test_stale_position_without_price_stays_open(db):
    account = DemoAccount.get_or_create(db, "Stale No Mark", config.DEMO_STARTING_BALANCE)
    account.open_position(
        symbol="EURUSD=X", market="forex", side="Long", quantity=1.0,
        price=1.10, slot=1,
        when=config.utcnow() - timedelta(days=config.DEMO_MAX_OPEN_DAYS + 2),
    )
    results = account.close_stale({})
    assert results and results[0]["result"] == "skipped"
    assert len(account.open_positions()) == 1


# --------------------------------------------------------------------------- #
# Provider backoff
# --------------------------------------------------------------------------- #
def test_repeated_failures_trigger_cooldown(monkeypatch):
    calls = {"n": 0}

    def failing(symbol, period, interval):
        calls["n"] += 1
        return market_data.PriceData(
            symbol=symbol, period=period, interval=interval,
            frame=market_data._empty_frame(), source="test",
            fetched_at=config.utcnow(), error="provider down",
        )

    monkeypatch.setattr(market_data, "_fetch_live", failing)
    monkeypatch.setattr(market_data, "_BACKOFF_UNTIL", 0.0)
    monkeypatch.setattr(market_data, "_CONSECUTIVE_FAILURES", 0)
    monkeypatch.setattr(market_data, "_LAST_REQUEST_AT", 0.0)

    market_data.get_price_history("TEST=X", "5d", "1h", allow_sample=False, force_refresh=True)
    market_data.get_price_history("TEST=X", "5d", "1h", allow_sample=False, force_refresh=True)
    assert calls["n"] == 2

    blocked = market_data.get_price_history("TEST=X", "5d", "1h", allow_sample=False, ttl=0)
    assert blocked.ok is False
    assert "cooling down" in (blocked.error or "")
    assert calls["n"] == 2  # no third provider call
