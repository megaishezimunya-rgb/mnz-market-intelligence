"""Scanner persistence, alert gating and safety-guard tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import config
import scanner
from data.market_data import PriceData


@pytest.fixture()
def user_id(db):
    account = db.create_account("Scanner Demo", config.DEMO_STARTING_BALANCE)
    user = db.create_user(email="scan@example.com", name="Scan",
                          password_hash="x", account_id=int(account["id"]))
    return int(user["id"])


def _data(symbol: str = "EURUSD=X", *, sample: bool = False, stale: bool = False) -> PriceData:
    n = 320
    closes = np.linspace(100, 130, n)
    end = config.utcnow() - pd.Timedelta(days=30) if stale else config.utcnow()
    index = pd.date_range(end=end, periods=n, freq="h")
    frame = pd.DataFrame({
        "Open": closes, "High": closes * 1.002, "Low": closes * 0.998,
        "Close": closes, "Volume": 1e5,
    }, index=index)
    return PriceData(symbol=symbol, period="3mo", interval="1h", frame=frame,
                     source="test" if not sample else "sample", fetched_at=config.utcnow(),
                     is_sample=sample, delayed=not sample, timeframe="H1")


def test_persist_signal_is_idempotent_per_bar(db, user_id):
    from analysis.signals import build_signal

    data = _data()
    signal = build_signal(symbol="EURUSD=X", market="forex", timeframe="H1",
                          data=data, settings=config.StrategySettings())
    row, created = scanner.persist_signal(db, user_id, signal)
    assert created and row["id"]
    again, created_again = scanner.persist_signal(db, user_id, signal)
    assert not created_again
    assert again["id"] == row["id"]
    assert len(db.list_signals(user_id)) == 1


def test_alert_only_for_current_directional_signal(db, user_id):
    prefs = {"enabled": True, "in_app": True, "min_strength": "Moderate",
             "min_quality": 50}
    base = {
        "symbol": "EURUSD=X", "market": "forex", "label": "BUY", "timeframe": "H1",
        "price": 1.1, "strength": "Strong", "quality": 80, "data_quality": "current",
        "is_sample": 0, "bar_time": "2026-01-01T10:00:00", "id": 1,
    }
    assert scanner.maybe_alert(db, user_id, base, prefs, timeframe="H1") is not None
    # Same bar is not alerted twice.
    assert scanner.maybe_alert(db, user_id, base, prefs, timeframe="H1") is None

    sample = dict(base, bar_time="2026-01-02T10:00:00", is_sample=1, data_quality="sample")
    assert scanner.maybe_alert(db, user_id, sample, prefs, timeframe="H1") is None

    stale = dict(base, bar_time="2026-01-03T10:00:00", data_quality="delayed")
    assert scanner.maybe_alert(db, user_id, stale, prefs, timeframe="H1") is None

    wait = dict(base, bar_time="2026-01-04T10:00:00", label="WAIT")
    assert scanner.maybe_alert(db, user_id, wait, prefs, timeframe="H1") is None

    low_quality = dict(base, bar_time="2026-01-05T10:00:00", quality=10)
    assert scanner.maybe_alert(db, user_id, low_quality, prefs, timeframe="H1") is None

    disabled = {"enabled": False, "in_app": True, "min_strength": "Moderate", "min_quality": 0}
    assert scanner.maybe_alert(db, user_id, dict(base, bar_time="2026-01-06T10:00:00"),
                               disabled, timeframe="H1") is None


def test_market_conditions_counts_scanned_results():
    from scanner import ScanResult

    data = _data()
    results = [
        ScanResult("A", "A", "forex", "H1", signal=_Fake("BUY", 70), data=data),
        ScanResult("B", "B", "forex", "H1", signal=_Fake("BUY", 80), data=data),
        ScanResult("C", "C", "forex", "H1", signal=_Fake("SELL", 60), data=data),
        ScanResult("D", "D", "forex", "H1", signal=_Fake("WAIT", 40), data=data),
        ScanResult("E", "E", "forex", "H1", data=None, error="failed"),
    ]
    conditions = scanner.market_conditions(results)
    assert conditions["scanned"] == 5
    assert conditions["usable"] == 4
    assert conditions["bullish"] == 2
    assert conditions["bearish"] == 1
    assert conditions["waiting"] == 1
    assert conditions["avg_quality"] == pytest.approx(62.5)


class _Fake:
    def __init__(self, label: str, quality: int):
        self.label = label
        self.quality = quality
        self.strength = "Moderate"
        self.score = 0.4
        self.is_sample = False
        self.price = 1.0
        self.data_quality = "current"


def test_safety_guard_blocks_sample_and_stale_data():
    sample = scanner.safety_guard(_data(sample=True), {"quality": 80})
    stale = scanner.safety_guard(_data(stale=True), {"quality": 80})
    clean = scanner.safety_guard(_data(), {"quality": 80})
    assert any(not check["ok"] for check in sample)
    assert any(not check["ok"] for check in stale)
    assert all(check["ok"] for check in clean)
