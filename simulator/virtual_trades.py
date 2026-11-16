"""Virtual trade model for the MNZ demo simulator.

A trade is a record of a simulated position.  Nothing here talks to a broker,
holds credentials or places orders — prices are supplied by the caller and the
result is stored in the local SQLite database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

COST_BPS_LIMIT = 500.0


@dataclass
class VirtualTrade:
    """One simulated position (open or closed)."""

    id: int | None
    account_id: int
    symbol: str
    market: str
    side: str
    quantity: float
    entry_price: float
    entry_time: str
    exit_price: float | None = None
    exit_time: str | None = None
    costs: float = 0.0
    realized_pnl: float | None = None
    status: str = "open"
    notes: str = ""
    strategy: str = "manual"

    # -- construction ------------------------------------------------------- #
    @classmethod
    def from_row(cls, row: dict) -> "VirtualTrade":
        return cls(
            id=row.get("id"),
            account_id=int(row["account_id"]),
            symbol=row["symbol"],
            market=row["market"],
            side=row["side"],
            quantity=float(row["quantity"]),
            entry_price=float(row["entry_price"]),
            entry_time=row["entry_time"],
            exit_price=row.get("exit_price"),
            exit_time=row.get("exit_time"),
            costs=float(row.get("costs") or 0.0),
            realized_pnl=row.get("realized_pnl"),
            status=row.get("status", "open"),
            notes=row.get("notes") or "",
            strategy=row.get("strategy") or "manual",
        )

    # -- derived values ----------------------------------------------------- #
    @property
    def direction(self) -> int:
        return 1 if self.side.lower() == "long" else -1

    @property
    def is_open(self) -> bool:
        return self.status.lower() == "open"

    @property
    def notional(self) -> float:
        return abs(self.quantity * self.entry_price)

    def unrealized_pnl(self, mark: float | None) -> float:
        """Gross mark-to-market P&L (entry costs are already in the cash balance)."""
        if mark is None or not self.is_open:
            return 0.0
        return (float(mark) - self.entry_price) * self.quantity * self.direction

    def unrealized_pct(self, mark: float | None) -> float:
        if mark is None or not self.notional:
            return 0.0
        return self.unrealized_pnl(mark) / self.notional * 100.0

    def net_pnl(self) -> float:
        return float(self.realized_pnl or 0.0)

    def return_pct(self) -> float:
        if not self.notional:
            return 0.0
        return self.net_pnl() / self.notional * 100.0

    def holding_days(self, as_of: str | None = None) -> float | None:
        try:
            start = datetime.fromisoformat(self.entry_time)
            end = datetime.fromisoformat(self.exit_time or as_of or "") if (self.exit_time or as_of) else datetime.utcnow()
        except (TypeError, ValueError):
            return None
        return max((end - start).total_seconds() / 86400.0, 0.0)

    def to_row(self, mark: float | None = None) -> dict:
        row = {
            "ID": self.id,
            "Symbol": self.symbol,
            "Market": self.market,
            "Side": self.side,
            "Quantity": round(self.quantity, 6),
            "Entry": round(self.entry_price, 4),
            "Entry time": self.entry_time.replace("T", " "),
            "Costs": round(self.costs, 2),
            "Strategy": self.strategy,
        }
        if self.is_open:
            row.update({
                "Mark": round(float(mark), 4) if mark is not None else None,
                "Unrealised P&L": round(self.unrealized_pnl(mark), 2),
                "Unrealised %": round(self.unrealized_pct(mark), 2),
                "Status": "Open",
            })
        else:
            row.update({
                "Exit": round(float(self.exit_price), 4) if self.exit_price is not None else None,
                "Exit time": (self.exit_time or "").replace("T", " "),
                "Realised P&L": round(self.net_pnl(), 2),
                "Return %": round(self.return_pct(), 2),
                "Status": "Closed",
            })
        return row


def trades_frame(trades: list[VirtualTrade], marks: dict[str, float] | None = None) -> pd.DataFrame:
    """Render a list of trades as a display table."""
    marks = marks or {}
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame([t.to_row(marks.get(t.symbol)) for t in trades])


def validate_trade(side: str, quantity: float, price: float, cost_bps: float) -> list[str]:
    """Validate user input for a new simulated position."""
    problems: list[str] = []
    if side.lower() not in {"long", "short"}:
        problems.append("Side must be Long or Short.")
    if quantity <= 0:
        problems.append("Quantity must be greater than zero.")
    if price <= 0:
        problems.append("Entry price must be greater than zero.")
    if not 0 <= cost_bps <= COST_BPS_LIMIT:
        problems.append("Transaction cost must be between 0 and 500 basis points.")
    return problems
