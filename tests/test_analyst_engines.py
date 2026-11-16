"""Tests for the analyst, the engine registry and market-engine context."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

import config
from analysis import market_analyst
from data.market_data import PriceData, _normalise, _sample_data
from engines import all_engines, base, get_engine
from engines import commodities, forex
from engines.stocks import _normalised_dividend_yield


def make_frame(n: int = 400, drift: float = 0.0015, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.008, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    index = pd.date_range("2022-01-03", periods=n, freq="D")
    return pd.DataFrame({
        "Open": open_,
        "High": np.maximum(open_, close) * 1.004,
        "Low": np.minimum(open_, close) * 0.996,
        "Close": close,
        "Volume": rng.integers(1_000_000, 3_000_000, n).astype(float),
    }, index=index)


def price_data(**overrides) -> PriceData:
    payload = dict(
        symbol="TEST", period="2y", interval="1d", frame=make_frame(),
        source="Test provider", fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        is_sample=False, delayed=True,
    )
    payload.update(overrides)
    return PriceData(**payload)


def test_engine_registry_and_distinct_defaults():
    assert [engine.key for engine in all_engines()] == ["forex", "crypto", "stocks", "commodities", "indices"]
    with pytest.raises(KeyError):
        get_engine("bonds")

    forex_settings = get_engine("forex").default_settings()
    crypto_settings = get_engine("crypto").default_settings()
    assert forex_settings.fast_ma != crypto_settings.fast_ma
    assert forex_settings.cost_bps < crypto_settings.cost_bps
    for engine in all_engines():
        assert engine.instruments(), engine.key
        assert engine.default_settings().validate() == []


def test_analyst_produces_explainable_report():
    data = price_data()
    settings = config.StrategySettings(fast_ma=20, slow_ma=60)
    report = market_analyst.analyze("stocks", data, settings)
    assert report.label in {"BUY BIAS", "SELL BIAS", "WAIT"}
    assert -1.0 <= report.score <= 1.0
    assert 0 <= report.confidence <= 95
    assert "TEST" in report.summary
    assert report.readings and report.reasons
    assert any("Test provider" in note for note in report.data_notes)
    assert report.bars == len(data.frame)
    assert report.trend in {"Strong uptrend", "Uptrend", "Sideways / range", "Downtrend", "Strong downtrend"}


def test_sample_data_reduces_conviction():
    settings = config.StrategySettings(fast_ma=20, slow_ma=60)
    real = market_analyst.analyze("stocks", price_data(), settings)
    sample = market_analyst.analyze("stocks", price_data(is_sample=True), settings)
    assert sample.is_sample is True
    assert sample.confidence <= 40
    assert sample.confidence <= max(real.confidence, 40)


def test_missing_data_produces_no_data_label():
    data = price_data(frame=pd.DataFrame(), error="Provider unreachable")
    report = market_analyst.analyze("stocks", data, config.StrategySettings())
    assert report.label == "NO DATA"
    assert report.confidence == 0
    assert "does not estimate prices" in report.summary
    assert report.data_notes


def test_overall_market_view_handles_empty_list():
    view = market_analyst.overall_market_view([])
    assert view["headline"] == "No analysable data"


def test_forex_context_exposes_sessions_and_events():
    engine = forex.ENGINE
    data = price_data(symbol="EURUSD=X")
    context = engine.context(data, engine.default_settings())
    assert context.headline
    assert len(context.extras["sessions"]) == 4
    assert context.events
    assert any("Liquidity" in fact[0] or "Sessions" in fact[0] for fact in context.facts)
    rows = base.session_rows()
    assert all(row["Status"] in {"Open", "Closed"} for row in rows)


def test_commodities_context_has_supply_demand_notes():
    engine = commodities.ENGINE
    data = price_data(symbol="GC=F")
    context = engine.context(data, engine.default_settings())
    assert "supply_demand" in context.extras
    assert context.extras["supply_demand"]["drivers"]
    assert context.events


def test_engine_context_handles_missing_data():
    for engine in all_engines():
        data = price_data(symbol=engine.instruments()[0].symbol, frame=pd.DataFrame(),
                          error="no data")
        context = engine.context(data, engine.default_settings())
        assert context.warnings


def test_sample_generator_is_labelled_and_consistent():
    sample = _sample_data("EURUSD=X", "1y", "1d")
    assert sample.is_sample is True
    assert sample.ok
    assert sample.bars >= 200
    assert "Sample" in sample.source_label
    frame = sample.frame
    assert (frame["High"] >= frame["Low"]).all()
    assert (frame["High"] >= frame["Close"]).all()
    assert (frame["Low"] <= frame["Close"]).all()
    assert "NOT real market data" in sample.notes[0]


def test_dividend_yield_units_are_normalised_to_a_fraction():
    # Annual rate divided by price is unambiguous.
    assert _normalised_dividend_yield({"dividendRate": 1.0, "currentPrice": 100.0}) == pytest.approx(0.01)
    # yfinance's trailing field is already a fraction.
    assert _normalised_dividend_yield({"trailingAnnualDividendYield": 0.002986}) == pytest.approx(0.002986)
    # Newer releases report dividendYield in percent, older ones as a fraction.
    assert _normalised_dividend_yield({"dividendYield": 3.5}) == pytest.approx(0.035)
    assert _normalised_dividend_yield({"dividendYield": 0.3}) == pytest.approx(0.003)
    assert _normalised_dividend_yield({}) is None


def test_normalise_handles_empty_and_duplicate_rows():
    assert _normalise(None).empty
    frame = make_frame(10)
    frame = pd.concat([frame, frame.tail(1)])
    cleaned = _normalise(frame)
    assert not cleaned.empty
    assert cleaned.index.is_monotonic_increasing
    assert not cleaned.index.duplicated().any()
