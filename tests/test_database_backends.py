"""Backend selection and Postgres dialect translation.

The live Postgres round-trip runs only when MNZ_TEST_DATABASE_URL is set, so
the normal suite stays SQLite-only and dependency-free.
"""

import os

import pytest

import config
from database.database import Database, _pg_ddl, _pg_sql


def test_explicit_path_always_uses_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://not-used")
    db = Database(tmp_path / "local.db")
    assert db.backend == "SQLite"
    assert db.path == tmp_path / "local.db"


def test_postgres_translation_adds_returning_id_for_inserts():
    sql, returns_id = _pg_sql("INSERT INTO signals (a, b) VALUES (?, ?)")
    assert "%s" in sql and "?" not in sql
    assert returns_id is True
    assert sql.endswith("RETURNING id")


def test_postgres_translation_handles_upserts():
    session_sql, session_id = _pg_sql(
        "INSERT OR REPLACE INTO sessions (token_hash, user_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)"
    )
    assert "ON CONFLICT (token_hash) DO UPDATE" in session_sql
    assert session_id is False and "RETURNING" not in session_sql

    setting_sql, setting_id = _pg_sql(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    assert setting_id is False and "RETURNING" not in setting_sql


def test_postgres_ddl_translation():
    ddl = _pg_ddl("id INTEGER PRIMARY KEY AUTOINCREMENT, balance REAL NOT NULL")
    assert "BIGSERIAL PRIMARY KEY" in ddl
    assert "DOUBLE PRECISION" in ddl
    assert "AUTOINCREMENT" not in ddl


@pytest.mark.skipif(
    not os.environ.get("MNZ_TEST_DATABASE_URL"),
    reason="set MNZ_TEST_DATABASE_URL to run against a real PostgreSQL server",
)
def test_postgres_round_trip(monkeypatch):
    import time

    monkeypatch.setattr(config, "DATABASE_URL", os.environ["MNZ_TEST_DATABASE_URL"])
    db = Database()
    assert db.backend == "PostgreSQL"

    account = db.create_account("PG Test", 100.0)
    user = db.create_user(
        email=f"pg{int(time.time() * 1000)}@test.local", name="PG Test",
        password_hash="hash", account_id=account["id"],
    )
    db.create_session("token", user["id"], "2099-01-01T00:00:00")
    db.create_session("token", user["id"], "2099-02-01T00:00:00")
    assert db.get_session_user("token")["id"] == user["id"]

    db.set_user_setting(user["id"], "notifications", {"telegram": True})
    assert db.get_user_setting(user["id"], "notifications") == {"telegram": True}

    trade = db.insert_trade({
        "account_id": account["id"], "symbol": "EURUSD", "market": "forex",
        "side": "BUY", "quantity": 1, "entry_price": 1.1, "tp": 1.2, "sl": 1.0,
    })
    assert db.update_trade(trade["id"], {"status": "closed"})["status"] == "closed"

    signal = db.insert_signal({
        "user_id": user["id"], "symbol": "EURUSD", "market": "forex",
        "label": "BUY", "timeframe": "1h", "price": 1.1,
    })
    db.update_signal(signal["id"], {"outcome": "TP"})
    assert db.get_signal(signal["id"])["outcome"] == "TP"

    alert = db.add_alert({
        "user_id": user["id"], "symbol": "EURUSD", "title": "t", "message": "m",
    })
    assert alert["id"]
    for index in range(55):
        db.add_delivery_attempt({"user_id": user["id"], "alert_id": index, "ok": index % 2})
    rows = db.list_delivery_attempts(user["id"], limit=100)
    assert len(rows) == 50 and rows[0]["alert_id"] == "54"

    db.add_journal({"user_id": user["id"], "note": "note"})
    assert len(db.list_journal(user["id"])) == 1
    assert db.save_backtest({
        "market": "forex", "symbol": "EURUSD", "period": "1y",
        "interval": "1d", "user_id": user["id"],
    })
    db.reset_account(account["id"])
    assert db.list_trades(account["id"]) == []

    db.delete_session("token")
    assert db.get_session_user("token") is None
