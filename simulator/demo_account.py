"""Virtual demo account.

VERSION ONE IS DEMO-ONLY.

* Starting virtual balance: $10,000 (configurable in Settings).
* All trades are simulated and stored locally.
* No broker, no API keys, no live orders, no real money — ever.

Accounting model used here (documented so the numbers are auditable):
    cash       = starting balance − entry costs + realised gross P&L − exit costs
    equity     = cash + unrealised gross P&L of open positions
    realised   = sum of (gross P&L − entry cost − exit cost) for closed trades

Notional is never deducted from cash, because this is a notional demo rather
than a margin account.  Position size therefore limits how big a simulated
position can be, and the guard rails below stop absurd entries.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

import config
from analysis import indicators
from database.database import Database
from simulator.virtual_trades import VirtualTrade, validate_trade

MAX_NOTIONAL_MULTIPLE = 10.0  # simulated notional may not exceed 10x equity


class DemoAccount:
    """A single virtual trading account backed by SQLite."""

    def __init__(self, db: Database, row: dict) -> None:
        self.db = db
        self._row = dict(row)
        self.id = int(row["id"])
        self.name = row["name"]
        self.starting_balance = float(row["starting_balance"])
        self.cash = float(row["cash_balance"])
        self.created_at = row["created_at"]

    # -- loading ------------------------------------------------------------ #
    @classmethod
    def load(cls, db: Database, account_id: int | None = None) -> "DemoAccount":
        row = db.get_account(account_id) if account_id else None
        if row is None:
            row = db.get_or_create_account(config.DEMO_ACCOUNT_NAME, config.DEMO_STARTING_BALANCE)
        return cls(db, row)

    @classmethod
    def get_or_create(cls, db: Database, name: str = config.DEMO_ACCOUNT_NAME,
                      starting_balance: float = config.DEMO_STARTING_BALANCE) -> "DemoAccount":
        return cls(db, db.get_or_create_account(name, starting_balance))

    def refresh(self) -> "DemoAccount":
        row = self.db.get_account(self.id)
        if row:
            self._row = row
            self.cash = float(row["cash_balance"])
            self.starting_balance = float(row["starting_balance"])
        return self

    # -- positions ---------------------------------------------------------- #
    def open_positions(self) -> list[VirtualTrade]:
        return [VirtualTrade.from_row(row) for row in self.db.list_trades(self.id, status="open")]

    def closed_positions(self, limit: int | None = None) -> list[VirtualTrade]:
        return [VirtualTrade.from_row(row) for row in self.db.list_trades(self.id, status="closed", limit=limit)]

    def all_positions(self) -> list[VirtualTrade]:
        return [VirtualTrade.from_row(row) for row in self.db.list_trades(self.id)]

    def trade(self, trade_id: int) -> VirtualTrade | None:
        row = self.db.get_trade(trade_id)
        if row is None or int(row["account_id"]) != self.id:
            return None
        return VirtualTrade.from_row(row)

    # -- trading ------------------------------------------------------------ #
    def open_position(
        self,
        *,
        symbol: str,
        market: str,
        side: str,
        quantity: float,
        price: float,
        cost_bps: float = config.DEFAULT_SIM_COST_BPS,
        notes: str = "",
        strategy: str = "manual",
        when: datetime | None = None,
        tp: float | None = None,
        sl: float | None = None,
        slot: int | None = None,
        signal_id: int | None = None,
        timeframe: str = "",
    ) -> tuple[VirtualTrade | None, list[str]]:
        """Open a simulated position. Returns (trade, problems).

        A slot is only marked as occupied once this call succeeds, because the
        slot lives on the trade row that is inserted at the end.
        """
        problems = validate_trade(side, quantity, price, cost_bps)
        if not symbol:
            problems.append("A symbol is required.")
        if tp is not None and tp <= 0:
            problems.append("Take profit must be greater than zero.")
        if sl is not None and sl <= 0:
            problems.append("Stop loss must be greater than zero.")
        if tp is not None and sl is not None:
            if side.lower() == "long" and not (sl < price < tp):
                problems.append("For a long, the stop must be below entry and the target above it.")
            if side.lower() == "short" and not (tp < price < sl):
                problems.append("For a short, the target must be below entry and the stop above it.")
        if slot is not None:
            open_slots = {t.slot for t in self.open_positions() if t.slot}
            if slot in open_slots:
                problems.append(f"Slot {slot} is already occupied by an open simulated position.")
        notional = float(quantity) * float(price)
        equity = self.equity({})
        if notional > max(equity, 1.0) * MAX_NOTIONAL_MULTIPLE:
            problems.append(
                f"Simulated notional ${notional:,.2f} exceeds {MAX_NOTIONAL_MULTIPLE:.0f}x virtual equity. "
                "Reduce quantity — the demo does not simulate margin."
            )
        if problems:
            return None, problems

        entry_cost = notional * cost_bps / 10_000.0
        new_cash = self.cash - entry_cost
        stamp = (when or config.utcnow()).isoformat(timespec="seconds")
        row = self.db.insert_trade({
            "account_id": self.id,
            "symbol": symbol,
            "market": market,
            "side": "Long" if side.lower() == "long" else "Short",
            "quantity": float(quantity),
            "entry_price": float(price),
            "entry_time": stamp,
            "costs": entry_cost,
            "status": "open",
            "notes": notes,
            "strategy": strategy,
            "tp": tp,
            "sl": sl,
            "slot": slot,
            "signal_id": signal_id,
            "timeframe": timeframe,
        })
        self.db.update_cash(self.id, new_cash)
        self.refresh()
        return VirtualTrade.from_row(row), []

    def close_position(
        self,
        trade_id: int,
        price: float,
        *,
        cost_bps: float = config.DEFAULT_SIM_COST_BPS,
        reason: str = "",
        when: datetime | None = None,
    ) -> tuple[VirtualTrade | None, list[str]]:
        """Close a simulated position at ``price``. Returns (trade, problems)."""
        trade = self.trade(trade_id)
        if trade is None:
            return None, [f"Simulated position {trade_id} was not found."]
        if not trade.is_open:
            return None, [f"Simulated position {trade_id} is already closed."]
        if price <= 0:
            return None, ["Exit price must be greater than zero."]
        if not 0 <= cost_bps <= 500:
            return None, ["Transaction cost must be between 0 and 500 basis points."]

        gross = (float(price) - trade.entry_price) * trade.quantity * trade.direction
        exit_cost = trade.quantity * float(price) * cost_bps / 10_000.0
        entry_cost = trade.costs
        total_costs = entry_cost + exit_cost
        net = gross - total_costs
        new_cash = self.cash + gross - exit_cost
        closed_at = (when or config.utcnow()).isoformat(timespec="seconds")
        note = trade.notes
        if reason:
            note = f"{note} | exit: {reason}".strip(" |")

        row = self.db.update_trade(trade_id, {
            "exit_price": float(price),
            "exit_time": closed_at,
            "costs": total_costs,
            "realized_pnl": net,
            "status": "closed",
            "notes": note,
        })
        self.db.update_cash(self.id, new_cash)
        self.refresh()
        return VirtualTrade.from_row(row), []

    def close_by_signal_id(self, signal_id: int, price: float, *, reason: str = "signal") -> tuple[VirtualTrade | None, list[str]]:
        for trade in self.open_positions():
            if trade.signal_id == signal_id:
                return self.close_position(trade.id, price, reason=reason)
        return None, ["No open simulated position is linked to that signal."]

    def close_stale(
        self,
        marks: dict[str, float] | None = None,
        *,
        max_age_days: float = config.DEMO_MAX_OPEN_DAYS,
    ) -> list[dict]:
        """Close simulated positions that have been open too long.

        There is no scheduler on the host, so this runs when the Demo section is
        opened. A position without a current mark is left open rather than
        closed at an invented price.
        """
        marks = marks or {}
        results: list[dict] = []
        for trade in self.open_positions():
            age = trade.holding_days()
            if age is None or age < max_age_days:
                continue
            mark = marks.get(trade.symbol)
            if mark is None or mark <= 0:
                results.append({
                    "trade_id": trade.id, "symbol": trade.symbol,
                    "result": "skipped", "detail": "No current price available.",
                })
                continue
            done, problems = self.close_position(
                trade.id, mark,
                reason=f"auto-closed after {age:.1f} days (simulated)",
            )
            results.append({
                "trade_id": trade.id, "symbol": trade.symbol,
                "result": "closed" if done else "error",
                "pnl": done.net_pnl() if done else None,
                "detail": "; ".join(problems),
            })
        return results

    def process_protective_exits(
        self, marks: dict[str, float] | None = None,
    ) -> list[dict]:
        """Close open positions whose last price has crossed their TP or SL.

        Exits are simulated at the level itself. When a single price observation
        is beyond both levels it cannot be known which was touched first, so the
        position is left open and reported rather than guessed.
        """
        marks = marks or {}
        closed: list[dict] = []
        for trade in self.open_positions():
            mark = marks.get(trade.symbol)
            if mark is None or trade.tp is None or trade.sl is None:
                continue
            long_side = trade.direction > 0
            hit_tp = mark >= trade.tp if long_side else mark <= trade.tp
            hit_sl = mark <= trade.sl if long_side else mark >= trade.sl
            if hit_tp:
                done, problems = self.close_position(trade.id, trade.tp, reason="simulated TP")
            elif hit_sl:
                done, problems = self.close_position(trade.id, trade.sl, reason="simulated SL")
            else:
                continue
            if problems:
                closed.append({"trade_id": trade.id, "result": "error", "detail": "; ".join(problems)})
            else:
                closed.append({
                    "trade_id": trade.id, "symbol": trade.symbol,
                    "result": "TP" if hit_tp else "SL",
                    "pnl": done.net_pnl() if done else None,
                })
        return closed

    # -- valuation ---------------------------------------------------------- #
    def unrealized_pnl(self, marks: dict[str, float] | None = None) -> float:
        marks = marks or {}
        return float(sum(t.unrealized_pnl(marks.get(t.symbol)) for t in self.open_positions()))

    def realized_pnl(self) -> float:
        return float(sum(t.net_pnl() for t in self.closed_positions()))

    def total_costs(self) -> float:
        return float(sum(t.costs for t in self.all_positions()))

    def equity(self, marks: dict[str, float] | None = None) -> float:
        return float(self.cash + self.unrealized_pnl(marks))

    def total_return_pct(self) -> float:
        if not self.starting_balance:
            return 0.0
        return (self.equity({}) / self.starting_balance - 1) * 100

    # -- history ------------------------------------------------------------ #
    def snapshot(self, marks: dict[str, float] | None = None, note: str = "",
                 throttle_seconds: int = 45) -> dict:
        """Record virtual equity, throttled so page renders do not spam the table."""
        marks = marks or {}
        open_trades = self.open_positions()
        missing = sorted({t.symbol for t in open_trades if t.symbol not in marks})
        if missing:
            # Never record equity that silently ignores an open position: a partial
            # valuation would corrupt drawdown history.
            note = "equity snapshot skipped — no price for " + ", ".join(missing)
            latest = self.db.latest_snapshot(self.id)
            if latest:
                return latest
            return {
                "account_id": self.id, "equity": self.equity(marks), "cash": self.cash,
                "unrealized_pnl": 0.0, "realized_pnl": self.realized_pnl(),
                "note": note, "recorded": False,
            }
        unrealized = self.unrealized_pnl(marks)
        equity = self.cash + unrealized
        realized = self.realized_pnl()
        latest = self.db.latest_snapshot(self.id)
        if latest:
            try:
                age = (config.utcnow() - datetime.fromisoformat(latest["ts"])).total_seconds()
            except (TypeError, ValueError):
                age = 10_000
            if age < throttle_seconds and abs(float(latest["equity"]) - equity) < 0.01:
                return latest
        return self.db.add_snapshot({
            "account_id": self.id,
            "equity": equity,
            "cash": self.cash,
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "note": note,
        })

    def equity_history(self) -> pd.DataFrame:
        rows = self.db.list_snapshots(self.id)
        if not rows:
            return pd.DataFrame(columns=["ts", "equity", "cash", "unrealized_pnl", "realized_pnl"])
        frame = pd.DataFrame(rows)
        frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce")
        frame = frame.dropna(subset=["ts"]).sort_values("ts")
        return frame

    def maximum_drawdown(self) -> dict:
        """Peak-to-trough decline of recorded virtual equity, in percent."""
        history = self.equity_history()
        if history.empty:
            return {"pct": 0.0, "peak": self.starting_balance, "trough": self.starting_balance,
                    "points": 0, "note": "No equity snapshots recorded yet."}
        start_point = pd.Series([self.starting_balance], index=[history["ts"].iloc[0]])
        series = pd.concat([start_point, pd.Series(history["equity"].to_numpy(), index=history["ts"])])
        series = series.sort_index(kind="stable")
        peak = series.cummax()
        pct = (series / peak.replace(0, np.nan) - 1) * 100
        # Positional lookup: snapshots can share a timestamp, so labels are not unique.
        trough_position = int(pct.to_numpy().argmin())
        return {
            "pct": abs(float(pct.iloc[trough_position])),
            "peak": float(peak.iloc[trough_position]),
            "trough": float(series.iloc[trough_position]),
            "points": int(len(series)),
            "note": "Measured from recorded equity snapshots since the account was created.",
        }

    # -- statistics --------------------------------------------------------- #
    def stats(self) -> dict:
        closed = self.closed_positions()
        pnls = np.array([t.net_pnl() for t in closed], dtype=float)
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        return {
            "trades_closed": len(closed),
            "trades_open": len(self.open_positions()),
            "wins": int(wins.size),
            "losses": int(losses.size),
            "win_rate": float(wins.size / len(closed) * 100) if closed else float("nan"),
            "avg_win": float(wins.mean()) if wins.size else float("nan"),
            "avg_loss": float(losses.mean()) if losses.size else float("nan"),
            "best_trade": float(pnls.max()) if pnls.size else float("nan"),
            "worst_trade": float(pnls.min()) if pnls.size else float("nan"),
            "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.size and losses.sum() else float("nan"),
            "realized_pnl": float(pnls.sum()) if pnls.size else 0.0,
            "total_costs": self.total_costs(),
        }

    def reset(self) -> None:
        """Delete all simulated trades and restore the starting balance."""
        row = self.db.reset_account(self.id)
        self._row = row
        self.cash = float(row["cash_balance"])
        self.starting_balance = float(row["starting_balance"])

    def set_starting_balance(self, amount: float) -> list[str]:
        if amount <= 0:
            return ["Starting balance must be greater than zero."]
        self.db.reset_account(self.id, float(amount))
        self.refresh()
        return []
