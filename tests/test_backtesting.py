"""Tests for the backtesting engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import config
from analysis import backtesting


def make_frame(n: int = 700, seed: int = 11, drift: float = 0.0006, vol: float = 0.012) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rates = rng.normal(drift, vol, n)
    close = 100 * np.exp(np.cumsum(rates))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.006
    low = np.minimum(open_, close) * 0.994
    index = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close,
        "Volume": rng.integers(1_000_000, 2_000_000, n).astype(float),
    }, index=index)


def frame_from_close(close, start: str = "2020-01-01") -> pd.DataFrame:
    """Build an OHLCV frame from a close path, for deterministic signal tests."""
    values = np.asarray(close, dtype=float)
    return pd.DataFrame({
        "Open": values, "High": values * 1.002, "Low": values * 0.998,
        "Close": values, "Volume": 1_000_000.0,
    }, index=pd.date_range(start, periods=len(values), freq="D"))


def settings(**overrides) -> config.StrategySettings:
    base = dict(fast_ma=20, slow_ma=50, rsi_period=14, use_rsi_filter=False,
                cost_bps=5.0, position_size_pct=100.0, allow_short=False)
    base.update(overrides)
    return config.StrategySettings(**base)


def test_backtest_runs_and_reports_metrics():
    frame = make_frame()
    result = backtesting.run_backtest(frame, settings(), symbol="TEST", market="stocks")
    assert result.ok
    assert result.bars == len(frame)
    assert len(result.equity_curve) > 0
    assert result.metrics["num_trades"] > 0
    assert result.final_equity == pytest.approx(result.equity_curve.iloc[-1])
    assert result.metrics["max_drawdown_pct"] >= 0
    assert np.isfinite(result.metrics["total_return_pct"])
    assert result.metrics["total_costs"] > 0
    assert result.warnings


def test_costs_reduce_simulated_return():
    frame = make_frame()
    cheap = backtesting.run_backtest(frame, settings(cost_bps=0.0), symbol="TEST", market="stocks")
    expensive = backtesting.run_backtest(frame, settings(cost_bps=100.0), symbol="TEST", market="stocks")
    assert cheap.metrics["total_return_pct"] > expensive.metrics["total_return_pct"]
    assert expensive.metrics["total_costs"] > cheap.metrics["total_costs"]


def test_insufficient_history_is_reported_not_faked():
    frame = make_frame(n=40)
    result = backtesting.run_backtest(frame, settings(fast_ma=20, slow_ma=200), symbol="TEST")
    assert not result.ok
    assert result.metrics["num_trades"] == 0
    assert "Not enough history" in result.warnings[0]


def test_empty_frame_is_handled():
    result = backtesting.run_backtest(pd.DataFrame(), settings())
    assert not result.ok
    assert result.warnings


def test_win_rate_and_trade_frame_consistent():
    frame = make_frame()
    result = backtesting.run_backtest(frame, settings(), symbol="TEST")
    trades = result.trades_frame()
    assert len(trades) == result.metrics["num_trades"]
    if result.trades:
        wins = sum(1 for trade in result.trades if trade.net_pnl > 0)
        assert result.metrics["win_rate"] == pytest.approx(wins / len(result.trades) * 100)
        assert all(trade.costs > 0 for trade in result.trades)


def test_short_selling_is_optional():
    frame = make_frame(drift=-0.0008, seed=5)
    long_only = backtesting.run_backtest(frame, settings(), symbol="TEST")
    short_enabled = backtesting.run_backtest(frame, settings(allow_short=True), symbol="TEST")
    assert short_enabled.metrics["num_trades"] >= 0
    assert long_only.metrics["total_return_pct"] <= short_enabled.metrics["total_return_pct"] + 1e-6


def test_compare_periods_returns_windows():
    frame = make_frame(n=900)
    table = backtesting.compare_periods(frame, settings(), symbol="TEST", market="stocks")
    assert len(table) == 5
    assert {"Period", "Total return %", "Max drawdown %", "Trades"}.issubset(table.columns)
    full = table[table["Period"] == "Full history"].iloc[0]
    assert full["Bars"] == len(frame)


def test_rsi_entry_filter_is_an_armed_state_not_a_same_bar_gate():
    state = settings(use_rsi_filter=True, rsi_buy_max=62.0, rsi_sell_min=72.0)
    rsi = pd.Series([70.0, 60.0, 66.0, 71.0, 73.0, 66.0, 61.0])
    armed = backtesting._rsi_long_state(rsi, state)
    # Arms only below the ceiling, stays armed through the 62-72 band, and is
    # reset by an overbought reading at or above the exit level.
    assert list(armed) == [False, True, True, True, False, False, True]


def test_trend_entry_can_happen_above_the_rsi_ceiling_once_armed(monkeypatch):
    n, flat = 130, 40
    close = np.concatenate([
        np.full(flat, 100.0),
        100 * 1.003 ** np.arange(1, n - flat + 1),
    ])
    frame = frame_from_close(close, start="2021-01-01")
    strategy = settings(fast_ma=5, slow_ma=20, use_rsi_filter=True,
                        rsi_buy_max=62.0, rsi_sell_min=72.0, cost_bps=0.0)

    # RSI arms the filter early (55), then sits at 66 — above the 62 ceiling but
    # below the 72 reset — while the uptrend begins. A same-bar gate could never
    # enter here; the armed state should.
    values = np.full(n, 70.0)
    values[20:27] = 55.0
    values[27:n - 2] = 66.0
    values[n - 2:] = 75.0
    monkeypatch.setattr(backtesting.indicators, "rsi",
                        lambda close, period: pd.Series(values, index=frame.index))
    armed_run = backtesting.run_backtest(frame, strategy, symbol="TEST")
    assert armed_run.metrics["num_trades"] >= 1
    entry_position = frame.index.get_loc(armed_run.trades[0].entry_time)
    assert values[entry_position] > strategy.rsi_buy_max

    # Same prices, but RSI never dips below the ceiling: nothing arms, so no entry.
    never_armed = np.full(n, 70.0)
    never_armed[-2:] = 75.0
    monkeypatch.setattr(backtesting.indicators, "rsi",
                        lambda close, period: pd.Series(never_armed, index=frame.index))
    blocked_run = backtesting.run_backtest(frame, strategy, symbol="TEST")
    assert blocked_run.metrics["num_trades"] == 0


def test_short_window_after_warmup_is_flagged():
    frame = make_frame(n=260)
    result = backtesting.run_backtest(
        frame, settings(fast_ma=50, slow_ma=200, use_rsi_filter=True), symbol="TEST")
    assert result.ok
    assert any("warm-up" in warning for warning in result.warnings)


def test_long_window_does_not_emit_the_warmup_warning():
    frame = make_frame(n=900)
    result = backtesting.run_backtest(
        frame, settings(fast_ma=50, slow_ma=200, use_rsi_filter=True), symbol="TEST")
    assert result.ok
    assert not any("warm-up" in warning for warning in result.warnings)


def test_short_window_fits_a_structure_instead_of_reporting_zero_trades():
    frame = make_frame(n=300)  # less than twice the 200-bar slow MA
    result = backtesting.run_backtest(
        frame, settings(fast_ma=50, slow_ma=200, use_rsi_filter=True), symbol="TEST")
    assert result.ok
    assert result.fitted
    assert result.settings.slow_ma < 200
    assert result.settings.fast_ma < result.settings.slow_ma
    assert any("fitted" in w for w in result.warnings)
    assert any("warm-up" in w for w in result.warnings)


def test_long_window_keeps_the_configured_structure():
    frame = make_frame(n=900)
    result = backtesting.run_backtest(
        frame, settings(fast_ma=50, slow_ma=200, use_rsi_filter=True), symbol="TEST")
    assert result.ok
    assert not result.fitted
    assert (result.settings.fast_ma, result.settings.slow_ma) == (50, 200)


def test_compare_periods_labels_fitted_windows():
    frame = make_frame(n=900)
    table = backtesting.compare_periods(
        frame, settings(fast_ma=50, slow_ma=200, use_rsi_filter=True), symbol="TEST", market="stocks")
    twelve = table[table["Period"] == "Last 12 months"].iloc[0]
    assert twelve["Trades"] is not None
    assert "fitted" in twelve["Note"]
    full = table[table["Period"] == "Full history"].iloc[0]
    assert full["Note"] == ""


def test_latest_signal_uses_the_armed_rsi_state(monkeypatch):
    close = 100 * 1.002 ** np.arange(120)
    frame = frame_from_close(close)
    strategy = settings(fast_ma=5, slow_ma=20, use_rsi_filter=True,
                        rsi_buy_max=62.0, rsi_sell_min=72.0)

    # RSI armed below the ceiling earlier, and is now 66 — above the 62 ceiling
    # but below the 72 reset — while the uptrend is intact.
    armed_values = np.full(120, 66.0)
    armed_values[:30] = 55.0
    monkeypatch.setattr(backtesting.indicators, "rsi",
                        lambda close, period: pd.Series(armed_values, index=frame.index))
    armed = backtesting.latest_signal(frame, strategy)
    assert armed["state"] == "Long signal"
    assert "armed" in armed["reason"]

    # Same uptrend, but RSI never dipped below the ceiling: nothing arms it.
    unarmed_values = np.full(120, 70.0)
    monkeypatch.setattr(backtesting.indicators, "rsi",
                        lambda close, period: pd.Series(unarmed_values, index=frame.index))
    unarmed = backtesting.latest_signal(frame, strategy)
    assert unarmed["state"] == "Flat"
    assert "not armed" in unarmed["reason"]


def test_latest_signal_states():
    rising = make_frame(n=300, drift=0.002, seed=2)
    signal = backtesting.latest_signal(rising, settings())
    assert signal["state"] in {"Long signal", "Short signal", "Flat"}
    assert "Fast MA" in signal["detail"]

    empty = backtesting.latest_signal(pd.DataFrame(), settings())
    assert empty["state"] == "No data"
