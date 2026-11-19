"""MNZ AI grounding tests: no invented prices, no invented connections."""

from __future__ import annotations

import numpy as np
import pandas as pd

import ai
import config
from analysis import indicators
from analysis.signals import Signal
from data.market_data import PriceData


def _data() -> PriceData:
    n = 320
    closes = np.linspace(100, 120, n)
    frame = pd.DataFrame({
        "Open": closes, "High": closes * 1.002, "Low": closes * 0.998,
        "Close": closes, "Volume": np.full(n, 1e5),
    }, index=pd.date_range("2025-01-01", periods=n, freq="h"))
    return PriceData(symbol="EURUSD=X", period="3mo", interval="1h", frame=frame,
                     source="test feed", fetched_at=config.utcnow(), timeframe="H1")


def _context(**overrides) -> ai.AssistantContext:
    data = overrides.pop("data", _data())
    snapshot = indicators.snapshot(data.frame) if data.ok else None
    return ai.AssistantContext(
        mode=overrides.pop("mode", "Beginner"), symbol=overrides.pop("symbol", "EURUSD=X"),
        data=data, snapshot=snapshot, equity=104.5, starting_balance=100.0,
        open_positions=1, closed_positions=2, **overrides,
    )


def test_price_answer_uses_the_loaded_bar():
    ctx = _context()
    answer = ai.answer("What is the price doing?", ctx)
    assert f"{ctx.data.last_price:,.5g}" in answer
    assert "delayed feed" in answer


def test_no_data_never_invents_a_price():
    empty = PriceData(symbol="V75", period="1mo", interval="1h", frame=pd.DataFrame(),
                      source="none", fetched_at=config.utcnow(), error="no connection")
    answer = ai.answer("What is the price of V75?", _context(data=empty, symbol="V75"))
    assert "don't have a verified price" in answer
    assert "SAMPLE" not in answer


def test_indicator_question_explains_and_reads_current_value():
    ctx = _context()
    answer = ai.answer("What is ADX?", ctx)
    assert "trend" in answer.lower()
    assert "ADX is" in answer


def test_signal_explanation_quotes_stored_signal():
    signal = Signal(symbol="EURUSD=X", market="forex", timeframe="H1", label="SELL",
                    price=1.09, score=-0.4, quality=66, strength="Moderate",
                    entry_ref=1.09, tp=1.08, sl=1.10, explanation="Bearish weighted evidence.")
    answer = ai.answer("Explain the signal", _context(signal=signal))
    assert "SELL" in answer and "66/100" in answer
    assert "1.08" in answer and "1.1" in answer


def test_broker_question_is_honest():
    answer = ai.answer("Is MT5 connected?", _context())
    assert "no broker connection" in answer.lower()
    assert "planned" in answer.lower()


def test_demo_answer_labels_everything_virtual():
    answer = ai.answer("How is my demo balance?", _context())
    assert "DEMO" in answer
    assert "$104.50" in answer
    assert "simulated" in answer.lower()


def test_professional_mode_adds_component_detail_when_signal_present():
    signal = Signal(symbol="EURUSD=X", market="forex", timeframe="H1", label="BUY",
                    price=110.0, score=0.35, quality=70, strength="Moderate",
                    entry_ref=110.0, tp=113.0, sl=108.0, explanation="Constructive.",
                    metrics={"components": {"trend": 0.5}, "weights": {"trend": 0.4}})
    pro = ai.answer("Explain the signal", _context(signal=signal, mode="Professional"))
    assert "Component scores" in pro


def test_best_setup_answer_ranks_verified_signals_only():
    rows = [
        {"symbol": "EURUSD=X", "timeframe": "H1", "label": "BUY", "strength": "Strong",
         "quality": 88, "score": 0.55, "entry_ref": 1.10, "tp": 1.13, "sl": 1.08,
         "data_quality": "current", "is_sample": 0},
        {"symbol": "AAPL", "timeframe": "H1", "label": "SELL", "strength": "Moderate",
         "quality": 71, "score": -0.35, "entry_ref": 190.0, "tp": 185.0, "sl": 195.0,
         "data_quality": "current", "is_sample": 0},
        {"symbol": "BTC-USD", "timeframe": "H1", "label": "BUY", "strength": "Strong",
         "quality": 95, "score": 0.9, "entry_ref": 1.0, "tp": 2.0, "sl": 0.5,
         "data_quality": "sample", "is_sample": 1},
    ]
    answer = ai.answer("Which setup is the best right now?", _context(recent_signals=rows))
    assert "EURUSD=X" in answer and "AAPL" in answer
    assert "BTC-USD" not in answer
    assert answer.index("EURUSD=X") < answer.index("AAPL")
    assert "88/100" in answer
    assert "not recommendations" in answer.lower() or "not a probability" in answer.lower()


def test_best_setup_answer_asks_for_a_scan_when_nothing_is_stored():
    answer = ai.answer("What is the best setup?", _context(recent_signals=[]))
    assert "Scan instrument" in answer or "Scan all" in answer
    assert "no stored BUY/SELL" in answer
