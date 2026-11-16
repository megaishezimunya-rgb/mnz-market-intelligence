"""Strategy backtesting for the MNZ market engines.

The backtester is deliberately transparent:

* signals are evaluated on **bar closes** (no intrabar look-ahead),
* costs are charged in basis points on both entry and exit notional,
* every result carries the data source, the period tested and the assumption
  warnings, including the fact that historical results do not guarantee future
  performance.

Each engine supplies its own :class:`config.StrategySettings`, so the same
mechanics do not imply the same strategy across markets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config
from analysis import indicators


@dataclass
class SimTrade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    notional: float
    gross_pnl: float
    costs: float
    net_pnl: float
    return_pct: float
    bars_held: int
    exit_reason: str

    def to_row(self) -> dict:
        return {
            "Entry": self.entry_time,
            "Exit": self.exit_time,
            "Side": self.side,
            "Entry price": round(self.entry_price, 4),
            "Exit price": round(self.exit_price, 4),
            "Bars held": self.bars_held,
            "Gross P&L": round(self.gross_pnl, 2),
            "Costs": round(self.costs, 2),
            "Net P&L": round(self.net_pnl, 2),
            "Return %": round(self.return_pct, 2),
            "Exit reason": self.exit_reason,
        }


@dataclass
class BacktestResult:
    symbol: str
    market: str
    settings: config.StrategySettings
    initial_balance: float
    final_equity: float
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    trades: list[SimTrade] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    source: str = ""
    is_sample: bool = False
    bars: int = 0
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None

    @property
    def ok(self) -> bool:
        return self.bars > 0 and not self.equity_curve.empty

    def trades_frame(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(
                columns=["Entry", "Exit", "Side", "Entry price", "Exit price", "Bars held",
                         "Gross P&L", "Costs", "Net P&L", "Return %", "Exit reason"]
            )
        return pd.DataFrame([t.to_row() for t in self.trades])

    def metrics_frame(self) -> pd.DataFrame:
        labels = {
            "total_return_pct": "Total simulated return",
            "buy_hold_return_pct": "Buy & hold return (same bars)",
            "final_equity": "Final simulated equity",
            "num_trades": "Simulated trades",
            "win_rate": "Win rate",
            "max_drawdown_pct": "Maximum drawdown",
            "total_costs": "Total simulated costs",
            "profit_factor": "Profit factor",
            "avg_trade_pct": "Average trade return",
            "exposure_pct": "Time in market",
            "annualised_return_pct": "Annualised return (simulated)",
            "sharpe": "Simulated Sharpe (bar returns)",
        }
        rows = []
        for key, label in labels.items():
            if key in self.metrics:
                rows.append({"Metric": label, "Value": self.metrics[key]})
        return pd.DataFrame(rows)


def _ensure_datetime_index(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.index, pd.DatetimeIndex):
        return frame
    frame = frame.copy()
    frame.index = pd.date_range(end=pd.Timestamp.utcnow().normalize(), periods=len(frame), freq="D")
    return frame


def _rsi_long_state(rsi_series: pd.Series, settings: config.StrategySettings) -> pd.Series:
    """Armed/disarmed state for the long RSI entry filter.

    The filter is a *state*, not a same-bar threshold: it arms when RSI falls
    below the entry ceiling and stays armed until RSI reaches the exit level.
    A trend can therefore be entered on a later bar even if RSI has already
    drifted back above the ceiling, instead of requiring the pullback and the
    trend signal to land on the exact same close.
    """
    armed = np.zeros(len(rsi_series), dtype=bool)
    state = False
    for position, value in enumerate(rsi_series.to_numpy(dtype=float)):
        if np.isfinite(value):
            if value < settings.rsi_buy_max:
                state = True
            elif value >= settings.rsi_sell_min:
                state = False
        armed[position] = state
    return pd.Series(armed, index=rsi_series.index, dtype=bool)


def _empty_result(symbol: str, market: str, settings, initial: float, warning: str) -> BacktestResult:
    return BacktestResult(
        symbol=symbol, market=market, settings=settings, initial_balance=initial,
        final_equity=initial, warnings=[warning],
        metrics={"num_trades": 0, "total_return_pct": 0.0, "max_drawdown_pct": 0.0,
                 "win_rate": float("nan"), "total_costs": 0.0, "final_equity": initial},
    )


def run_backtest(
    frame: pd.DataFrame,
    settings: config.StrategySettings,
    *,
    symbol: str = "",
    market: str = "",
    initial_balance: float = config.DEMO_STARTING_BALANCE,
    source: str = "",
    is_sample: bool = False,
) -> BacktestResult:
    """Run a long (optionally short) moving-average + RSI strategy on OHLCV data."""
    if frame is None or frame.empty or "Close" not in frame:
        return _empty_result(symbol, market, settings, initial_balance,
                             "No price data available for this instrument.")
    frame = _ensure_datetime_index(frame).dropna(subset=["Close"])
    min_bars = max(settings.slow_ma, settings.rsi_period) + 10
    if len(frame) < min_bars:
        return _empty_result(
            symbol, market, settings, initial_balance,
            f"Not enough history: {len(frame)} bars available, {min_bars} needed for these settings.",
        )

    close = frame["Close"].astype(float)
    fast = indicators.sma(close, settings.fast_ma)
    slow = indicators.sma(close, settings.slow_ma)
    rsi_series = indicators.rsi(close, settings.rsi_period)
    rsi_armed = _rsi_long_state(rsi_series, settings)

    warmup = max(settings.slow_ma, settings.rsi_period + 1)
    cash = float(initial_balance)
    units = 0.0
    side = 0  # +1 long, -1 short, 0 flat
    entry_price = 0.0
    entry_time = frame.index[0]
    entry_cost = 0.0
    entry_notional = 0.0
    bars_held = 0
    trades: list[SimTrade] = []
    equity_values: list[float] = []
    equity_index: list[pd.Timestamp] = []
    bars_in_market = 0

    warn: list[str] = []
    if settings.use_rsi_filter is False:
        warn.append("The RSI entry filter is disabled for this run, so entries rely on trend alone.")
    tested_bars = len(frame) - warmup
    if tested_bars < settings.slow_ma:
        warn.append(
            f"Only {tested_bars} bars remain after the {settings.slow_ma}-bar moving-average warm-up, "
            f"so a {settings.fast_ma}/{settings.slow_ma} structure has little room to produce signals. "
            "Test a longer history (2 years or more) for a meaningful read."
        )

    for i in range(warmup, len(frame)):
        price = float(close.iloc[i])
        fast_value = fast.iloc[i]
        slow_value = slow.iloc[i]
        rsi_value = rsi_series.iloc[i]
        if not np.isfinite(price) or not np.isfinite(fast_value) or not np.isfinite(slow_value):
            equity_values.append(cash + (price - entry_price) * units * side if side else cash)
            equity_index.append(frame.index[i])
            continue

        if side != 0:
            bars_held += 1
            bars_in_market += 1

        # -- exit rules (evaluated on this bar's close) --------------------- #
        exit_reason = None
        if side == 1:
            if fast_value < slow_value:
                exit_reason = "Trend exit (fast MA crossed below slow MA)"
            elif settings.use_rsi_filter and np.isfinite(rsi_value) and rsi_value >= settings.rsi_sell_min:
                exit_reason = f"RSI exit (RSI {rsi_value:.0f} ≥ {settings.rsi_sell_min:.0f})"
            elif settings.max_hold_bars and bars_held >= settings.max_hold_bars:
                exit_reason = "Time stop"
        elif side == -1:
            if fast_value > slow_value:
                exit_reason = "Trend exit (fast MA crossed above slow MA)"
            elif settings.use_rsi_filter and np.isfinite(rsi_value) and rsi_value <= 100 - settings.rsi_sell_min:
                exit_reason = f"RSI exit (RSI {rsi_value:.0f} ≤ {100 - settings.rsi_sell_min:.0f})"
            elif settings.max_hold_bars and bars_held >= settings.max_hold_bars:
                exit_reason = "Time stop"

        if side != 0 and exit_reason:
            gross = (price - entry_price) * units * side
            exit_cost = units * price * settings.cost_bps / 10_000.0
            cash += gross - exit_cost
            total_costs = entry_cost + exit_cost
            net = gross - total_costs
            trades.append(SimTrade(
                entry_time=entry_time, exit_time=frame.index[i],
                side="Long" if side == 1 else "Short",
                entry_price=entry_price, exit_price=price, quantity=units,
                notional=entry_notional, gross_pnl=gross, costs=total_costs,
                net_pnl=net,
                return_pct=(net / entry_notional * 100.0) if entry_notional else 0.0,
                bars_held=bars_held, exit_reason=exit_reason,
            ))
            side, units, bars_held, entry_cost, entry_notional = 0, 0.0, 0, 0.0, 0.0

        # -- entry rules ---------------------------------------------------- #
        if side == 0 and price > 0:
            long_signal = fast_value > slow_value and (
                not settings.use_rsi_filter or bool(rsi_armed.iloc[i])
            )
            short_signal = (
                settings.allow_short and fast_value < slow_value
                and (not settings.use_rsi_filter or (np.isfinite(rsi_value) and rsi_value > 50))
            )
            if long_signal or short_signal:
                equity_now = cash
                notional = equity_now * settings.position_size_pct / 100.0
                units = notional / price
                side = 1 if long_signal else -1
                entry_price, entry_time = price, frame.index[i]
                entry_notional = notional
                entry_cost = notional * settings.cost_bps / 10_000.0
                cash -= entry_cost
                bars_held = 0

        equity = cash + ((price - entry_price) * units * side if side else 0.0)
        equity_values.append(equity)
        equity_index.append(frame.index[i])

    equity_curve = pd.Series(equity_values, index=pd.DatetimeIndex(equity_index), name="Equity")
    final_equity = float(equity_curve.iloc[-1]) if len(equity_curve) else float(initial_balance)

    closed = trades
    net_pnls = np.array([t.net_pnl for t in closed], dtype=float)
    wins = net_pnls[net_pnls > 0]
    losses = net_pnls[net_pnls < 0]
    rets = np.array([t.return_pct for t in closed], dtype=float)
    tested = close.iloc[warmup:]

    equity_with_start = pd.concat([
        pd.Series([initial_balance], index=[frame.index[warmup]]),
        equity_curve,
    ])
    drawdown = indicators.max_drawdown(equity_with_start)

    periods = indicators.bars_per_year(frame.index)
    eq_rets = equity_with_start.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    sharpe = float(eq_rets.mean() / eq_rets.std(ddof=1) * np.sqrt(periods)) if len(eq_rets) > 2 and eq_rets.std(ddof=1) > 0 else float("nan")

    elapsed_days = max((frame.index[-1] - frame.index[warmup]).total_seconds() / 86400.0, 1e-9)
    cagr = float(((final_equity / initial_balance) ** (365.25 / elapsed_days) - 1) * 100) if final_equity > 0 else float("nan")

    metrics = {
        "total_return_pct": (final_equity / initial_balance - 1) * 100,
        "buy_hold_return_pct": float((tested.iloc[-1] / tested.iloc[0] - 1) * 100) if len(tested) > 1 else float("nan"),
        "final_equity": final_equity,
        "num_trades": len(closed),
        "win_rate": float(len(wins) / len(closed) * 100) if closed else float("nan"),
        "max_drawdown_pct": drawdown,
        "total_costs": float(sum(t.costs for t in closed)),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.size and losses.sum() != 0 else (float("inf") if wins.size else float("nan")),
        "avg_trade_pct": float(rets.mean()) if rets.size else float("nan"),
        "exposure_pct": (bars_in_market / max(len(equity_curve), 1)) * 100,
        "annualised_return_pct": cagr,
        "sharpe": sharpe,
        "bars": len(frame),
        "start": frame.index[warmup],
        "end": frame.index[-1],
    }

    result = BacktestResult(
        symbol=symbol or "series",
        market=market,
        settings=settings,
        initial_balance=float(initial_balance),
        final_equity=final_equity,
        equity_curve=equity_curve,
        trades=closed,
        metrics=metrics,
        source=source,
        is_sample=is_sample,
        bars=len(frame),
        start=frame.index[warmup],
        end=frame.index[-1],
    )
    result.warnings = warn + [
        "Simulated results use bar-close fills and no intrabar stop execution; real fills would differ.",
        f"Costs of {settings.cost_bps:.1f} bps are applied to both entry and exit notional.",
        "Historical results do not guarantee future performance. Backtests are research, not forecasts.",
        "The strategy is applied mechanically with no discretion, news awareness or risk management beyond position size.",
    ]
    if is_sample:
        result.warnings.insert(0, "SAMPLE DATA: these results come from synthetic offline data and mean nothing for real markets.")
    return result


def compare_periods(
    frame: pd.DataFrame,
    settings: config.StrategySettings,
    *,
    symbol: str = "",
    market: str = "",
    initial_balance: float = config.DEMO_STARTING_BALANCE,
    source: str = "",
    is_sample: bool = False,
) -> pd.DataFrame:
    """Run the same strategy across several trailing market periods."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = _ensure_datetime_index(frame).dropna(subset=["Close"])
    end = frame.index[-1]
    windows = [
        ("Last 3 months", pd.DateOffset(months=3)),
        ("Last 12 months", pd.DateOffset(years=1)),
        ("Last 3 years", pd.DateOffset(years=3)),
        ("Last 5 years", pd.DateOffset(years=5)),
        ("Full history", None),
    ]
    rows = []
    min_bars = max(settings.slow_ma, settings.rsi_period) + 10
    for label, offset in windows:
        subset = frame if offset is None else frame[frame.index >= end - offset]
        if len(subset) < min_bars:
            rows.append({
                "Period": label, "Bars": len(subset), "Total return %": None,
                "Buy & hold %": None, "Max drawdown %": None, "Win rate %": None,
                "Trades": None, "Costs": None, "Note": f"insufficient history ({len(subset)} bars)",
            })
            continue
        res = run_backtest(subset, settings, symbol=symbol, market=market,
                           initial_balance=initial_balance, source=source, is_sample=is_sample)
        rows.append({
            "Period": label,
            "Bars": res.bars,
            "Total return %": round(res.metrics["total_return_pct"], 2),
            "Buy & hold %": round(res.metrics["buy_hold_return_pct"], 2)
            if np.isfinite(res.metrics["buy_hold_return_pct"]) else None,
            "Max drawdown %": round(res.metrics["max_drawdown_pct"], 2),
            "Win rate %": round(res.metrics["win_rate"], 1) if np.isfinite(res.metrics["win_rate"]) else None,
            "Trades": res.metrics["num_trades"],
            "Costs": round(res.metrics["total_costs"], 2),
            "Note": "sample data" if is_sample else "",
        })
    return pd.DataFrame(rows)


def latest_signal(frame: pd.DataFrame, settings: config.StrategySettings) -> dict:
    """Current mechanical strategy state for an instrument (not a recommendation)."""
    if frame is None or frame.empty or "Close" not in frame:
        return {"state": "No data", "detail": "No usable history.", "reason": "n/a"}
    close = frame["Close"].astype(float)
    if len(close) < max(settings.slow_ma, settings.rsi_period) + 2:
        return {
            "state": "Insufficient history",
            "detail": f"{len(close)} bars available; {settings.slow_ma + 2} needed.",
            "reason": "n/a",
        }
    fast = indicators.sma(close, settings.fast_ma).iloc[-1]
    slow = indicators.sma(close, settings.slow_ma).iloc[-1]
    rsi_series = indicators.rsi(close, settings.rsi_period)
    rsi_value = rsi_series.iloc[-1]
    rsi_armed = settings.use_rsi_filter and bool(_rsi_long_state(rsi_series, settings).iloc[-1])
    if not (np.isfinite(fast) and np.isfinite(slow)):
        return {"state": "No reading", "detail": "Moving averages not yet formed.", "reason": "n/a"}

    long_ok = fast > slow and (not settings.use_rsi_filter or rsi_armed)
    short_ok = settings.allow_short and fast < slow and (not settings.use_rsi_filter or (np.isfinite(rsi_value) and rsi_value > 50))
    if long_ok:
        state = "Long signal"
        if settings.use_rsi_filter:
            reason = (
                f"Fast MA above slow MA and the RSI entry state is armed "
                f"(RSI {rsi_value:.0f}; armed below {settings.rsi_buy_max:.0f}, reset at {settings.rsi_sell_min:.0f})."
            )
        else:
            reason = "Fast MA above slow MA; the RSI entry filter is disabled for this engine."
    elif short_ok:
        state = "Short signal"
        reason = f"Fast MA below slow MA and RSI {rsi_value:.0f} above 50."
    else:
        state = "Flat"
        if fast > slow:
            reason = (
                f"Trend is up but the RSI entry state is not armed: RSI {rsi_value:.0f} is above the "
                f"{settings.rsi_buy_max:.0f} ceiling and has not reset below it since the last "
                f"{settings.rsi_sell_min:.0f} reading."
            )
        else:
            reason = "Fast MA is below the slow MA, so the trend rule is not long."
    return {
        "state": state,
        "detail": f"Fast MA {fast:,.4f} · Slow MA {slow:,.4f} · RSI {rsi_value:,.1f}",
        "reason": reason,
    }
