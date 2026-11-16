"""Tests for the technical indicator calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis import indicators


def make_close(n: int = 300, trend: float = 0.001, seed: int = 7, vol: float = 0.008) -> pd.Series:
    rng = np.random.default_rng(seed)
    rates = rng.normal(trend, vol, n)
    prices = 100.0 * np.exp(np.cumsum(rates))
    index = pd.date_range("2022-01-03", periods=n, freq="D")
    return pd.Series(prices, index=index, name="Close")


def make_frame(n: int = 300, trend: float = 0.001, seed: int = 7) -> pd.DataFrame:
    close = make_close(n=n, trend=trend, seed=seed)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    volume = pd.Series(np.linspace(1e6, 2e6, n), index=close.index)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume})


def test_sma_matches_manual_mean():
    series = make_close(50)
    result = indicators.sma(series, 10)
    assert result.iloc[-1] == pytest.approx(series.tail(10).mean())
    assert result.iloc[:9].isna().all()


def test_ema_tracks_price_and_reacts_faster_than_sma():
    series = pd.Series(np.linspace(100, 200, 120))
    ema = indicators.ema(series, 20)
    assert ema.iloc[-1] > indicators.sma(series, 20).iloc[-1]


def test_rsi_bounds_and_direction():
    rising = pd.Series(np.linspace(100, 200, 100))
    falling = pd.Series(np.linspace(200, 100, 100))
    up = indicators.rsi(rising, 14).dropna()
    down = indicators.rsi(falling, 14).dropna()
    assert not up.empty and not down.empty
    assert up.iloc[-1] > 70
    assert down.iloc[-1] < 30
    assert ((up >= 0) & (up <= 100)).all()
    assert ((down >= 0) & (down <= 100)).all()


def test_rsi_handles_flat_series_without_error():
    flat = pd.Series([50.0] * 40)
    result = indicators.rsi(flat, 14).dropna()
    assert (result == 50).all()


def test_macd_histogram_identity():
    series = make_close(200)
    frame = indicators.macd(series)
    assert list(frame.columns) == ["macd", "signal", "hist"]
    assert frame["hist"].iloc[-1] == pytest.approx(frame["macd"].iloc[-1] - frame["signal"].iloc[-1])


def test_atr_is_positive_and_scales_with_range():
    frame = make_frame(120)
    values = indicators.atr(frame, 14).dropna()
    assert not values.empty
    assert (values > 0).all()
    wide = frame.copy()
    wide["High"] = wide["High"] * 1.05
    wide["Low"] = wide["Low"] * 0.95
    assert indicators.atr(wide, 14).iloc[-1] > indicators.atr(frame, 14).iloc[-1]


def test_max_drawdown_known_values():
    equity = pd.Series([100.0, 110.0, 90.0, 100.0, 120.0])
    assert indicators.max_drawdown(equity) == pytest.approx((110 - 90) / 110 * 100)
    assert indicators.max_drawdown(pd.Series([100.0, 101.0, 102.0])) == pytest.approx(0.0)
    assert indicators.max_drawdown(pd.Series(dtype=float)) == 0.0


def test_bollinger_band_ordering():
    series = make_close(120)
    bands = indicators.bollinger(series, 20, 2.0).dropna()
    assert (bands["upper"] >= bands["mid"]).all()
    assert (bands["mid"] >= bands["lower"]).all()


def test_bars_per_year_for_daily_data():
    index = pd.date_range("2023-01-01", periods=200, freq="B")
    assert 250 < indicators.bars_per_year(index) < 260
    weekly = pd.date_range("2020-01-01", periods=100, freq="W")
    assert indicators.bars_per_year(weekly) == pytest.approx(52.0)


def test_snapshot_reflects_uptrend():
    frame = make_frame(400, trend=0.002, seed=3)
    snap = indicators.snapshot(frame, fast=20, slow=60, rsi_period=14)
    assert snap.bars == len(frame)
    assert snap.trend_label in {"Strong uptrend", "Uptrend", "Sideways / range", "Downtrend", "Strong downtrend"}
    assert -1.0 <= snap.trend_score <= 1.0
    assert -1.0 <= snap.momentum_score <= 1.0
    assert -1.0 <= snap.rsi_score <= 1.0
    assert snap.atr_pct > 0
    assert snap.annual_vol > 0


def test_snapshot_and_primitives_handle_missing_data():
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    snap = indicators.snapshot(empty)
    assert snap.bars == 0
    assert snap.trend_label == "Insufficient data"

    short = pd.Series([1.0, 2.0])
    assert indicators.rsi(short, 14).dropna().empty
    assert indicators.sma(pd.Series(dtype=float), 20).empty
