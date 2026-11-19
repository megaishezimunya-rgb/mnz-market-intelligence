"""Trade plan: what a stored reading says to do now, and for how long."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from analysis import signals  # noqa: E402

NOW = datetime(2026, 1, 5, 10, 30)


def _row(**overrides) -> dict:
    row = {
        "symbol": "EURUSD=X", "market": "forex", "timeframe": "H1", "label": "BUY",
        "price": 1.085, "entry_ref": 1.085, "tp": 1.0911, "sl": 1.0817,
        "status": "Open", "outcome": "",
        "created_at": "2026-01-05T10:00:00", "bar_time": "2026-01-05T09:00:00",
    }
    row.update(overrides)
    return row


def test_a_fresh_reading_is_actionable_inside_its_window():
    plan = signals.plan(_row(), now=NOW)

    assert plan["state"] == "actionable"
    assert plan["action"] == "Buy"
    assert plan["entry"] == 1.085
    assert plan["stop"] == 1.0817
    assert plan["target"] == 1.0911
    assert plan["valid_until"] == datetime(2026, 1, 5, 16, 0)
    assert plan["countdown"] == "5h 30m"
    assert "Buy near 1.085" in plan["summary"]


def test_a_sell_reading_says_sell_with_its_own_levels():
    plan = signals.plan(
        _row(label="SELL", entry_ref=1.085, tp=1.0789, sl=1.0883), now=NOW
    )

    assert plan["state"] == "actionable"
    assert plan["action"] == "Sell"
    assert plan["target"] < plan["entry"] < plan["stop"]


def test_the_window_follows_the_timeframe():
    assert signals.valid_until(_row()) == datetime(2026, 1, 5, 16, 0)
    assert signals.valid_until(_row(timeframe="H4")) == datetime(2026, 1, 6, 10, 0)
    assert signals.valid_until(_row(timeframe="D1")) == datetime(2026, 1, 11, 10, 0)
    assert signals.valid_until(_row(timeframe="M15")) == datetime(2026, 1, 5, 11, 30)


def test_a_reading_past_its_window_is_expired():
    plan = signals.plan(_row(), now=datetime(2026, 1, 5, 16, 0))

    assert plan["state"] == "expired"
    assert plan["action"] == "Rescan"
    assert plan["countdown"] == "0m"
    assert "fresh scan" in plan["summary"]


def test_wait_is_not_a_trade_and_has_no_levels_to_follow():
    plan = signals.plan(
        _row(label="WAIT", status="No trade", entry_ref=None, tp=None, sl=None), now=NOW
    )

    assert plan["state"] == "waiting"
    assert plan["action"] == "Wait"
    assert plan["entry"] is None and plan["risk_reward"] is None
    assert plan["valid_until"] is None and plan["countdown"] == ""


def test_a_closed_reading_has_nothing_left_to_do():
    plan = signals.plan(_row(status="Closed", outcome="TP hit"), now=NOW)

    assert plan["state"] == "closed"
    assert plan["action"] == "Done"
    assert "TP hit" in plan["summary"]


def test_an_ambiguous_result_is_reported_not_guessed():
    plan = signals.plan(_row(status="Unresolved"), now=NOW)

    assert plan["state"] == "closed"
    assert "ambiguous" in plan["summary"]


def test_a_directional_reading_without_levels_is_not_actionable():
    plan = signals.plan(_row(tp=None), now=NOW)

    assert plan["state"] == "waiting"
    assert plan["action"] == "Wait"


def test_the_plan_only_repeats_the_stored_levels():
    row = _row()
    plan = signals.plan(row, now=NOW)

    assert (plan["entry"], plan["stop"], plan["target"]) == (
        row["entry_ref"], row["sl"], row["tp"]
    )
    expected = abs(row["tp"] - row["entry_ref"]) / abs(row["entry_ref"] - row["sl"])
    assert plan["risk_reward"] == pytest.approx(expected)


def test_the_window_falls_back_to_the_bar_time():
    plan = signals.plan(_row(created_at=None), now=NOW)

    assert plan["valid_until"] == datetime(2026, 1, 5, 15, 0)
    assert plan["countdown"] == "4h 30m"


def test_an_unparseable_timestamp_leaves_the_window_unknown():
    plan = signals.plan(_row(created_at="not-a-time", bar_time=""), now=NOW)

    assert plan["valid_until"] is None
    assert plan["countdown"] == ""
    assert plan["state"] == "actionable"


def test_planning_never_mutates_the_signal_row():
    row = _row()
    before = dict(row)
    signals.plan(row, now=NOW)
    assert row == before


def test_expiry_uses_naive_utc_like_the_rest_of_the_app():
    plan = signals.plan(_row(), now=config.utcnow() + timedelta(days=30))
    assert plan["state"] == "expired"
