"""Signal calibration: measured hit rate and expectancy per group."""

from __future__ import annotations

import pytest

from analysis import signals


def _row(*, market="forex", timeframe="H1", quality=90, outcome="TP hit",
         status="Closed", label="BUY"):
    return {
        "label": label, "status": status, "outcome": outcome, "quality": quality,
        "timeframe": timeframe, "symbol": "EURUSD=X", "market": market,
        "entry_ref": 100.0, "tp": 110.0, "sl": 95.0,
    }


def test_calibration_measures_resolved_signals_only():
    rows = [
        _row(outcome="TP hit", quality=92),
        _row(outcome="SL hit", quality=92),
        _row(outcome="TP hit", quality=70, market="indices", timeframe="H4"),
        _row(label="WAIT", status="No trade", outcome=""),
        _row(outcome="", status="Open"),
        _row(outcome="Ambiguous bar (both levels touched)", status="Unresolved"),
    ]
    result = signals.calibration(rows, min_sample=2)
    assert result["resolved"] == 3
    assert result["signals"] == 6
    assert result["directional"] == 5
    overall = result["overall"]
    assert overall["tp_hits"] == 2 and overall["sl_hits"] == 1
    assert overall["hit_rate"] == pytest.approx(2 / 3 * 100)
    assert overall["expectancy_r"] == pytest.approx(1.0)
    assert overall["profit_factor"] == pytest.approx(4.0)


def test_calibration_groups_by_market_timeframe_and_quality():
    rows = [
        _row(outcome="TP hit", quality=92),
        _row(outcome="SL hit", quality=92),
        _row(outcome="TP hit", quality=70, market="indices", timeframe="H4"),
    ]
    result = signals.calibration(rows, min_sample=2)

    markets = {item["name"]: item for item in result["by_market"]}
    assert markets["forex"]["resolved"] == 2
    assert markets["forex"]["hit_rate"] == pytest.approx(50.0)
    assert markets["forex"]["expectancy_r"] == pytest.approx(0.5)
    assert markets["forex"]["reliable"] is True
    assert markets["indices"]["reliable"] is False

    timeframes = {item["name"]: item for item in result["by_timeframe"]}
    assert set(timeframes) == {"H1", "H4"}

    bands = {item["name"]: item for item in result["by_quality"]}
    assert bands["90–100"]["resolved"] == 2
    assert bands["60–74"]["resolved"] == 1


def test_calibration_without_resolved_outcomes_is_empty_not_invented():
    result = signals.calibration([_row(label="WAIT", status="No trade", outcome="")])
    assert result["resolved"] == 0
    assert result["by_market"] == [] and result["by_timeframe"] == []
    assert result["overall"]["hit_rate"] != result["overall"]["hit_rate"]  # NaN


def test_min_sample_controls_the_reliable_flag():
    rows = [_row() for _ in range(3)]
    assert signals.calibration(rows, min_sample=3)["by_market"][0]["reliable"] is True
    assert signals.calibration(rows, min_sample=4)["by_market"][0]["reliable"] is False
