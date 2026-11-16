"""Portfolio analytics for the MNZ demo account.

Everything here is derived from the local SQLite records: open positions, closed
trades and recorded equity snapshots.  No performance figure is ever invented —
if there is not enough history, the function says so instead of filling a number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
from analysis import indicators
from database.database import Database
from simulator.demo_account import DemoAccount
from simulator.virtual_trades import VirtualTrade


# --------------------------------------------------------------------------- #
# Equity history
# --------------------------------------------------------------------------- #
def record_snapshot(db: Database, account: DemoAccount, marks: dict[str, float] | None = None,
                    note: str = "") -> dict:
    """Persist current virtual equity (throttled inside DemoAccount)."""
    return account.snapshot(marks or {}, note=note)


def equity_curve(account: DemoAccount) -> pd.DataFrame:
    """Recorded equity as a time-indexed frame including the starting balance."""
    history = account.equity_history()
    if history.empty:
        return pd.DataFrame({
            "ts": [pd.Timestamp.utcnow()],
            "equity": [account.starting_balance],
            "cash": [account.starting_balance],
            "unrealized_pnl": [0.0],
            "realized_pnl": [0.0],
        })
    start = pd.DataFrame({
        "ts": [history["ts"].iloc[0]],
        "equity": [account.starting_balance],
        "cash": [account.starting_balance],
        "unrealized_pnl": [0.0],
        "realized_pnl": [0.0],
    })
    return pd.concat([start, history], ignore_index=True).sort_values("ts", kind="stable").reset_index(drop=True)


def drawdown_series(account: DemoAccount) -> pd.DataFrame:
    curve = equity_curve(account)
    if curve.empty:
        return curve
    series = pd.Series(curve["equity"].to_numpy(), index=curve["ts"])
    return pd.DataFrame({"equity": series, "drawdown_pct": indicators.rolling_drawdown(series)})


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
def portfolio_summary(account: DemoAccount, marks: dict[str, float] | None = None) -> dict:
    """Current virtual account snapshot plus honest performance statistics."""
    marks = marks or {}
    open_trades = account.open_positions()
    closed_trades = account.closed_positions()
    unrealized = account.unrealized_pnl(marks)
    equity = account.cash + unrealized
    realized = account.realized_pnl()
    drawdown = account.maximum_drawdown()
    stats = account.stats()

    total_return = ((equity / account.starting_balance - 1) * 100) if account.starting_balance else 0.0
    return {
        "equity": equity,
        "cash": account.cash,
        "starting_balance": account.starting_balance,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "total_return_pct": total_return,
        "total_pnl": equity - account.starting_balance,
        "max_drawdown_pct": drawdown["pct"],
        "drawdown_points": drawdown["points"],
        "open_positions": len(open_trades),
        "closed_positions": len(closed_trades),
        "win_rate": stats["win_rate"],
        "profit_factor": stats["profit_factor"],
        "total_costs": stats["total_costs"],
        "wins": stats["wins"],
        "losses": stats["losses"],
        "avg_win": stats["avg_win"],
        "avg_loss": stats["avg_loss"],
        "best_trade": stats["best_trade"],
        "worst_trade": stats["worst_trade"],
        "exposure": sum(t.notional for t in open_trades),
        "exposure_pct": (sum(t.notional for t in open_trades) / equity * 100) if equity else 0.0,
    }


def performance_stats(account: DemoAccount) -> dict:
    """Time-based statistics from the recorded equity history."""
    history = account.equity_history()
    if len(history) < 2:
        return {
            "available": False,
            "note": "At least two equity snapshots are needed for time-based statistics.",
        }
    series = pd.Series(history["equity"].to_numpy(), index=pd.to_datetime(history["ts"]))
    returns = series.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    elapsed_days = max((series.index[-1] - series.index[0]).total_seconds() / 86400.0, 1e-9)
    total_return = (series.iloc[-1] / series.iloc[0] - 1) * 100 if series.iloc[0] else 0.0
    annualised = float(
        ((series.iloc[-1] / series.iloc[0]) ** (365.25 / elapsed_days) - 1) * 100
    ) if series.iloc[0] > 0 and series.iloc[-1] > 0 else float("nan")
    return {
        "available": True,
        "snapshots": len(history),
        "first": series.index[0],
        "last": series.index[-1],
        "total_return_pct": float(total_return),
        "annualised_return_pct": annualised,
        "max_drawdown_pct": indicators.max_drawdown(series),
        "volatility_pct": float(returns.std(ddof=1) * 100) if len(returns) > 1 else float("nan"),
        "note": "Derived from recorded equity snapshots, not from broker data.",
    }


# --------------------------------------------------------------------------- #
# Allocation and trade analysis
# --------------------------------------------------------------------------- #
def market_allocation(account: DemoAccount, marks: dict[str, float] | None = None) -> pd.DataFrame:
    """Open exposure grouped by market engine."""
    marks = marks or {}
    open_trades = account.open_positions()
    if not open_trades:
        return pd.DataFrame(columns=["Market", "Open positions", "Notional", "Unrealised P&L", "Share of equity %"])
    equity = max(account.equity(marks), 1e-9)
    rows: dict[str, dict] = {}
    for trade in open_trades:
        bucket = rows.setdefault(trade.market.title(), {
            "Market": trade.market.title(), "Open positions": 0, "Notional": 0.0, "Unrealised P&L": 0.0,
        })
        bucket["Open positions"] += 1
        bucket["Notional"] += trade.notional
        bucket["Unrealised P&L"] += trade.unrealized_pnl(marks.get(trade.symbol))
    frame = pd.DataFrame(list(rows.values()))
    frame["Share of equity %"] = frame["Notional"] / equity * 100
    return frame.sort_values("Notional", ascending=False).reset_index(drop=True)


def trade_statistics(trades: list[VirtualTrade]) -> pd.DataFrame:
    """Closed-trade statistics table (empty when there are no closed trades)."""
    closed = [t for t in trades if not t.is_open]
    if not closed:
        return pd.DataFrame()
    pnls = np.array([t.net_pnl() for t in closed], dtype=float)
    returns = np.array([t.return_pct() for t in closed], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    holding = [t.holding_days() for t in closed if t.holding_days() is not None]
    rows = [
        ("Closed simulated trades", f"{len(closed)}"),
        ("Winning trades", f"{wins.size}"),
        ("Losing trades", f"{losses.size}"),
        ("Win rate", f"{wins.size / len(closed) * 100:.1f}%"),
        ("Average win", f"${wins.mean():,.2f}" if wins.size else "n/a"),
        ("Average loss", f"${losses.mean():,.2f}" if losses.size else "n/a"),
        ("Average trade return", f"{returns.mean():+.2f}%"),
        ("Largest win", f"${pnls.max():,.2f}"),
        ("Largest loss", f"${pnls.min():,.2f}"),
        ("Profit factor", f"{wins.sum() / abs(losses.sum()):.2f}" if losses.size and losses.sum() else "n/a"),
        ("Total simulated costs", f"${sum(t.costs for t in closed):,.2f}"),
        ("Median holding period", f"{np.median(holding):.1f} days" if holding else "n/a"),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def monthly_returns(account: DemoAccount) -> pd.DataFrame:
    """Month-by-month percentage change of recorded virtual equity."""
    history = account.equity_history()
    if len(history) < 2:
        return pd.DataFrame()
    series = pd.Series(history["equity"].to_numpy(), index=pd.to_datetime(history["ts"])).sort_index()
    # Group by calendar month instead of resample("ME"): the "ME" frequency alias
    # only exists in pandas >= 2.2, while requirements.txt allows every pandas 2.x.
    monthly = series.groupby([series.index.year, series.index.month]).last().sort_index()
    if len(monthly) < 2:
        return pd.DataFrame()
    changes = monthly.pct_change().dropna() * 100
    table = pd.DataFrame({
        "Year": changes.index.get_level_values(0),
        "Month": changes.index.get_level_values(1),
        "Return %": changes.to_numpy().round(2),
    })
    pivot = table.pivot_table(index="Year", columns="Month", values="Return %", aggfunc="last")
    pivot = pivot.reindex(columns=range(1, 13))
    pivot.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return pivot.round(2)


def engine_breakdown(account: DemoAccount) -> pd.DataFrame:
    """Realised simulated P&L grouped by market engine."""
    trades = account.all_positions()
    if not trades:
        return pd.DataFrame()
    rows: dict[str, dict] = {}
    for trade in trades:
        bucket = rows.setdefault(trade.market.title(), {
            "Market": trade.market.title(), "Trades": 0, "Open": 0,
            "Realised P&L": 0.0, "Costs": 0.0, "Wins": 0, "Losses": 0,
        })
        bucket["Trades"] += 1
        bucket["Costs"] += trade.costs
        if trade.is_open:
            bucket["Open"] += 1
        else:
            bucket["Realised P&L"] += trade.net_pnl()
            if trade.net_pnl() > 0:
                bucket["Wins"] += 1
            elif trade.net_pnl() < 0:
                bucket["Losses"] += 1
    frame = pd.DataFrame(list(rows.values()))
    closed = frame["Wins"] + frame["Losses"]
    frame["Win rate %"] = np.where(closed > 0, frame["Wins"] / closed.replace(0, np.nan) * 100, np.nan)
    return frame.round(2).sort_values("Realised P&L", ascending=False).reset_index(drop=True)


def export_trades_csv(account: DemoAccount, marks: dict[str, float] | None = None) -> str:
    """CSV text of all simulated trades for download."""
    from simulator.virtual_trades import trades_frame

    frame = trades_frame(account.all_positions(), marks or {})
    if frame.empty:
        return "id,symbol,market,side,status\n"
    return frame.to_csv(index=False)
