"""SQLite persistence for MNZ MARKET INTELLIGENCE.

Tables
------
accounts          virtual demo accounts (cash balance, starting balance)
trades            every simulated position, open and closed
equity_snapshots  recorded virtual equity over time (drawdown history)
settings          JSON key/value store (engine settings, preferences)
backtest_runs     saved backtest summaries for the reports page

The schema is account-scoped so the same storage can later serve individual
customer accounts without a redesign.  No credentials or personal data are
stored anywhere in this schema.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    starting_balance REAL NOT NULL,
    cash_balance     REAL NOT NULL,
    is_demo          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol        TEXT NOT NULL,
    market        TEXT NOT NULL,
    side          TEXT NOT NULL,
    quantity      REAL NOT NULL,
    entry_price   REAL NOT NULL,
    entry_time    TEXT NOT NULL,
    exit_price    REAL,
    exit_time     TEXT,
    costs         REAL NOT NULL DEFAULT 0,
    realized_pnl  REAL,
    status        TEXT NOT NULL DEFAULT 'open',
    notes         TEXT DEFAULT '',
    strategy      TEXT DEFAULT 'manual',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_account_status ON trades(account_id, status);
CREATE INDEX IF NOT EXISTS idx_trades_account_market ON trades(account_id, market);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    ts             TEXT NOT NULL,
    equity         REAL NOT NULL,
    cash           REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    realized_pnl   REAL NOT NULL,
    note           TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_equity_account_ts ON equity_snapshots(account_id, ts);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL,
    market         TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    period         TEXT NOT NULL,
    interval       TEXT NOT NULL,
    settings_json  TEXT NOT NULL,
    metrics_json   TEXT NOT NULL,
    is_sample      INTEGER NOT NULL DEFAULT 0
);
"""

TRADE_FIELDS = [
    "id", "account_id", "symbol", "market", "side", "quantity", "entry_price",
    "entry_time", "exit_price", "exit_time", "costs", "realized_pnl", "status",
    "notes", "strategy", "created_at",
]


def _now() -> str:
    return config.utcnow().isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


class Database:
    """Small, dependency-free SQLite wrapper with explicit transactions."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or config.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    # -- connection --------------------------------------------------------- #
    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialise(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)

    # -- accounts ----------------------------------------------------------- #
    def create_account(self, name: str, starting_balance: float) -> dict:
        stamp = _now()
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO accounts (name, starting_balance, cash_balance, is_demo, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (name, float(starting_balance), float(starting_balance), stamp, stamp),
            )
            account_id = int(cursor.lastrowid)
        account = self.get_account(account_id)
        assert account is not None
        return account

    def get_account(self, account_id: int) -> dict | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return _row_to_dict(row)

    def get_or_create_account(self, name: str, starting_balance: float) -> dict:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE name = ? ORDER BY id LIMIT 1", (name,)
            ).fetchone()
        if row:
            return dict(row)
        return self.create_account(name, starting_balance)

    def list_accounts(self) -> list[dict]:
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def update_cash(self, account_id: int, cash_balance: float) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE accounts SET cash_balance = ?, updated_at = ? WHERE id = ?",
                (float(cash_balance), _now(), account_id),
            )

    def reset_account(self, account_id: int, starting_balance: float | None = None) -> dict:
        with self.session() as conn:
            row = conn.execute("SELECT starting_balance FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                raise ValueError(f"Account {account_id} does not exist.")
            balance = float(starting_balance if starting_balance is not None else row["starting_balance"])
            conn.execute("DELETE FROM trades WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM equity_snapshots WHERE account_id = ?", (account_id,))
            conn.execute(
                "UPDATE accounts SET cash_balance = ?, starting_balance = ?, updated_at = ? WHERE id = ?",
                (balance, balance, _now(), account_id),
            )
        account = self.get_account(account_id)
        assert account is not None
        return account

    # -- trades ------------------------------------------------------------- #
    def insert_trade(self, payload: dict) -> dict:
        stamp = _now()
        values = {
            "account_id": payload["account_id"],
            "symbol": payload["symbol"],
            "market": payload["market"],
            "side": payload["side"],
            "quantity": float(payload["quantity"]),
            "entry_price": float(payload["entry_price"]),
            "entry_time": payload.get("entry_time") or stamp,
            "exit_price": payload.get("exit_price"),
            "exit_time": payload.get("exit_time"),
            "costs": float(payload.get("costs", 0.0)),
            "realized_pnl": payload.get("realized_pnl"),
            "status": payload.get("status", "open"),
            "notes": payload.get("notes", ""),
            "strategy": payload.get("strategy", "manual"),
            "created_at": stamp,
        }
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self.session() as conn:
            cursor = conn.execute(
                f"INSERT INTO trades ({columns}) VALUES ({placeholders})", tuple(values.values())
            )
            trade_id = int(cursor.lastrowid)
        trade = self.get_trade(trade_id)
        assert trade is not None
        return trade

    def get_trade(self, trade_id: int) -> dict | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        return _row_to_dict(row)

    def update_trade(self, trade_id: int, fields: dict) -> dict:
        allowed = {k: v for k, v in fields.items() if k in TRADE_FIELDS and k not in {"id", "created_at"}}
        if not allowed:
            return self.get_trade(trade_id) or {}
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        with self.session() as conn:
            conn.execute(
                f"UPDATE trades SET {assignments} WHERE id = ?",
                (*allowed.values(), trade_id),
            )
        trade = self.get_trade(trade_id)
        assert trade is not None
        return trade

    def list_trades(
        self,
        account_id: int,
        *,
        status: str | None = None,
        market: str | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM trades WHERE account_id = ?"
        params: list[Any] = [account_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        if market:
            query += " AND market = ?"
            params.append(market)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY entry_time DESC, id DESC"
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        with self.session() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def delete_trade(self, trade_id: int) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))

    # -- equity snapshots --------------------------------------------------- #
    def add_snapshot(self, payload: dict) -> dict:
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO equity_snapshots (account_id, ts, equity, cash, unrealized_pnl, realized_pnl, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    payload["account_id"], payload.get("ts") or _now(), float(payload["equity"]),
                    float(payload["cash"]), float(payload["unrealized_pnl"]),
                    float(payload["realized_pnl"]), payload.get("note", ""),
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM equity_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        return dict(row) if row else {}

    def list_snapshots(self, account_id: int, limit: int = config.EQUITY_HISTORY_LIMIT) -> list[dict]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM equity_snapshots WHERE account_id = ? ORDER BY ts ASC, id ASC LIMIT ?",
                (account_id, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_snapshot(self, account_id: int) -> dict | None:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM equity_snapshots WHERE account_id = ? ORDER BY ts DESC, id DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        return _row_to_dict(row)

    # -- settings ----------------------------------------------------------- #
    def set_setting(self, key: str, value: Any) -> None:
        payload = json.dumps(value)
        with self.session() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, payload, _now()),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.session() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return default

    def all_settings(self) -> dict:
        with self.session() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        out = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                out[row["key"]] = row["value"]
        return out

    def delete_setting(self, key: str) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    # -- backtests ---------------------------------------------------------- #
    def save_backtest(self, payload: dict) -> int:
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO backtest_runs (created_at, market, symbol, period, interval, settings_json, metrics_json, is_sample) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(), payload["market"], payload["symbol"], payload["period"],
                    payload["interval"], json.dumps(payload.get("settings", {})),
                    json.dumps(payload.get("metrics", {}), default=str),
                    1 if payload.get("is_sample") else 0,
                ),
            )
            return int(cursor.lastrowid)

    def list_backtests(self, limit: int = 50) -> list[dict]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in rows]
