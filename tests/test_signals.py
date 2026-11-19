"""Tests for the signal engine: labels, quality, targets and measured outcomes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import config
from analysis.signals import Signal, build_signal, evaluate_outcome, signal_performance
from data.market_data import PriceData


def _frame(closes: np.ndarray, *, freq: str = "h", start: str | None = None) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    spread = closes * 0.0015 + 1e-6
    # End at the current hour so the bars are fresh, not stale.
    index = pd.date_range(end=pd.Timestamp.utcnow().floor("h"), periods=len(closes), freq=freq)
    return pd.DataFrame({
        "Open": closes, "High": closes + spread, "Low": closes - spread,
        "Close": closes, "Volume": np.full(len(closes), 100_000.0),
    }, index=index)


def _data(frame: pd.DataFrame, *, sample: bool = False, timeframe: str = "H1") -> PriceData:
    return PriceData(
        symbol="TEST", period="3mo", interval="1h", frame=frame,
        source="test feed" if not sample else "sample", fetched_at=config.utcnow(),
        is_sample=sample, delayed=not sample, timeframe=timeframe,
    )


def test_uptrend_produces_buy_with_ordered_targets():
    # A trend with periodic pullbacks. A perfectly straight line pins RSI at 100
    # and can correctly resolve to WAIT (overbought, momentum flattening).
    closes = np.linspace(100, 150, 320) + np.sin(np.linspace(0, 30, 320)) * 3
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1",
                          data=_data(_frame(closes)), settings=config.StrategySettings())
    assert signal.label == "BUY"
    assert signal.tp is not None and signal.sl is not None
    assert signal.sl < signal.price < signal.tp
    assert 0 <= signal.quality <= 100
    assert signal.strength in {"Strong", "Moderate", "Weak"}
    assert "trend" in signal.metrics["components"]


def test_downtrend_produces_sell_with_ordered_targets():
    closes = np.linspace(150, 100, 320)
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1",
                          data=_data(_frame(closes)), settings=config.StrategySettings())
    assert signal.label == "SELL"
    assert signal.tp < signal.price < signal.sl


def test_flat_market_is_wait_and_has_no_targets():
    closes = 100 + np.sin(np.linspace(0, 40, 320)) * 0.05
    signal = build_signal(symbol="TEST", market="index", timeframe="H1",
                          data=_data(_frame(closes)), settings=config.StrategySettings())
    assert signal.label == "WAIT"
    assert signal.tp is None and signal.sl is None


def test_sample_data_can_never_be_directional():
    closes = np.linspace(100, 150, 320)
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1",
                          data=_data(_frame(closes), sample=True),
                          settings=config.StrategySettings())
    assert signal.label == "WAIT"
    assert signal.quality <= 30
    assert any("sample" in warning.lower() for warning in signal.warnings)


def test_missing_data_produces_wait_and_no_targets():
    empty = PriceData(symbol="TEST", period="1mo", interval="1h",
                      frame=pd.DataFrame(), source="none", fetched_at=config.utcnow(),
                      error="provider down")
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1", data=empty,
                          settings=config.StrategySettings())
    assert signal.label == "WAIT"
    assert signal.quality == 0
    assert signal.status == "No data"
    assert signal.tp is None


def _long_signal() -> Signal:
    return Signal(
        symbol="TEST", market="forex", timeframe="H1", label="BUY", price=100.0,
        score=0.5, quality=80, strength="Strong", entry_ref=100.0, tp=110.0, sl=90.0,
        explanation="test", bar_time="2025-01-05T00:00:00", created_at="2025-01-05T00:00:00",
    )


def test_outcome_tp_first_touch():
    frame = _frame([100, 105, 111])
    frame.index = pd.date_range("2025-01-05 00:00", periods=3, freq="h")
    outcome = evaluate_outcome(_long_signal(), _data(frame))
    assert outcome is not None
    assert outcome["outcome"] == "TP hit"
    assert outcome["outcome_price"] == 110.0


def test_outcome_sl_first_touch():
    frame = _frame([100, 95, 89])
    frame.index = pd.date_range("2025-01-05 00:00", periods=3, freq="h")
    outcome = evaluate_outcome(_long_signal(), _data(frame))
    assert outcome is not None
    assert outcome["outcome"] == "SL hit"
    assert outcome["outcome_price"] == 90.0


def test_ambiguous_bar_is_unresolved_not_guessed():
    frame = pd.DataFrame({
        "Open": [100, 100], "High": [101, 120], "Low": [99, 80],
        "Close": [100, 100], "Volume": [1, 1],
    }, index=pd.date_range("2025-01-05 00:00", periods=2, freq="h"))
    outcome = evaluate_outcome(_long_signal(), _data(frame))
    assert outcome is not None
    assert outcome["status"] == "Unresolved"
    assert outcome["outcome_price"] is None


def test_wait_signal_has_no_outcome():
    signal = _long_signal()
    signal.label = "WAIT"
    frame = _frame([100, 105, 111])
    frame.index = pd.date_range("2025-01-05 00:00", periods=3, freq="h")
    assert evaluate_outcome(signal, _data(frame)) is None


def test_signal_performance_counts_only_resolved():
    rows = [
        {"label": "BUY", "status": "Closed", "outcome": "TP hit"},
        {"label": "SELL", "status": "Closed", "outcome": "SL hit"},
        {"label": "BUY", "status": "Open"},
        {"label": "WAIT", "status": "No trade"},
    ]
    stats = signal_performance(rows)
    assert stats["resolved"] == 2
    assert stats["tp_hits"] == 1
    assert stats["hit_rate"] == pytest.approx(50.0)
    assert stats["open"] == 1
    assert stats["directional"] == 3


def test_components_must_agree_before_a_direction_is_published():
    from analysis import signals as engine

    supporting, opposing = engine._confirmations(
        {"trend": 0.6, "momentum": 0.05, "rsi": -0.4, "structure": 0.3}, 1
    )
    assert supporting == ["trend", "structure"]
    assert opposing == ["rsi"]


def test_signal_records_its_confirmation_evidence():
    closes = np.linspace(100, 150, 320) + np.sin(np.linspace(0, 30, 320)) * 3
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1",
                          data=_data(_frame(closes)), settings=config.StrategySettings())
    assert signal.metrics["confirmations"] >= config.SIGNAL_MIN_CONFIRMATIONS
    assert "trend" in signal.metrics["supporting"]
    assert signal.metrics["threshold"] == pytest.approx(config.SIGNAL_BUY_THRESHOLD)


def test_direction_needs_two_confirming_components(monkeypatch):
    monkeypatch.setattr(config, "SIGNAL_MIN_CONFIRMATIONS", 4)
    closes = np.linspace(100, 150, 320) + np.sin(np.linspace(0, 30, 320)) * 3
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1",
                          data=_data(_frame(closes)), settings=config.StrategySettings())
    assert signal.label == "WAIT"
    assert any("are required" in warning for warning in signal.warnings)


def test_a_ranging_market_demands_a_stronger_score(monkeypatch):
    monkeypatch.setattr(config, "SIGNAL_RANGE_ADX", 100.0)
    monkeypatch.setattr(config, "SIGNAL_RANGE_THRESHOLD", 0.99)
    closes = np.linspace(100, 150, 320) + np.sin(np.linspace(0, 30, 320)) * 3
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1",
                          data=_data(_frame(closes)), settings=config.StrategySettings())
    assert signal.label == "WAIT"
    assert signal.metrics["adx_weak"] is True
    assert signal.metrics["threshold"] == pytest.approx(0.99)


def test_higher_timeframe_alignment_is_recorded(monkeypatch):
    from analysis import signals as engine

    monkeypatch.setattr(engine, "_higher_trend", lambda data, timeframe: 0.6)
    closes = np.linspace(100, 150, 320) + np.sin(np.linspace(0, 30, 320)) * 3
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1",
                          data=_data(_frame(closes)), settings=config.StrategySettings())
    assert signal.label == "BUY"
    assert signal.metrics["higher_alignment"] == "aligned"
    assert signal.metrics["higher_timeframe"] == "D1"


def test_a_direction_that_fights_the_higher_timeframe_is_wait(monkeypatch):
    from analysis import signals as engine

    monkeypatch.setattr(engine, "_higher_trend", lambda data, timeframe: -0.9)
    closes = np.linspace(100, 150, 320) + np.sin(np.linspace(0, 30, 320)) * 3
    signal = build_signal(symbol="TEST", market="forex", timeframe="H1",
                          data=_data(_frame(closes)), settings=config.StrategySettings())
    assert signal.label == "WAIT"
    assert signal.metrics["higher_alignment"] == "against"
    assert any("higher timeframe" in warning for warning in signal.warnings)


def test_higher_timeframe_trend_is_built_from_the_loaded_bars():
    from analysis import signals as engine

    closes = np.linspace(100, 200, 420)
    frame = _frame(closes, freq="D")
    data = _data(frame, timeframe="D1")
    weekly = engine._higher_trend(data, "D1")
    assert np.isfinite(weekly)
    assert weekly > 0.2


def test_evidence_line_reports_recorded_confirmations():
    import ui

    line = ui._evidence_line({
        "metrics_json": '{"confirmations": 3, "higher_alignment": "aligned", "higher_timeframe": "D1"}'
    })
    assert "3/4 components agree" in line
    assert "D1 trend aligned" in line
    assert ui._evidence_line({"metrics_json": "{}"}) == ""
