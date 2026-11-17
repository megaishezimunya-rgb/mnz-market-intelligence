"""One-time SQLite-to-PostgreSQL migration.

The live test runs only when MNZ_TEST_DATABASE_URL points at a PostgreSQL
server where the test user may create databases.
"""

import os
import uuid

import pytest

import config
from database.database import Database
from database.migrate import insert_columns, migrate


def test_insert_columns_ignores_sqlite_only_columns():
    assert insert_columns(
        ["id", "user_id", "channel", "created_at"],
        {"id", "user_id", "created_at"},
    ) == ["id", "user_id", "created_at"]


def test_migration_requires_an_existing_sqlite_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        migrate(tmp_path / "missing.db", "postgresql://example/db")


def test_migration_requires_a_postgres_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "")
    source = Database(tmp_path / "source.db")
    with pytest.raises(ValueError):
        migrate(source.path, "")


def _fresh_database(base_url: str) -> tuple[str, str, str]:
    """Create an empty database on the test server; return (url, admin url, name)."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    info = conninfo_to_dict(base_url)
    name = f"mnz_mig_{uuid.uuid4().hex[:12]}"
    admin = make_conninfo(**info)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    info["dbname"] = name
    return make_conninfo(**info), admin, name


def _drop_database(admin_url: str, name: str) -> None:
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.mark.skipif(
    not os.environ.get("MNZ_TEST_DATABASE_URL"),
    reason="set MNZ_TEST_DATABASE_URL to run against a real PostgreSQL server",
)
def test_sqlite_data_is_migrated_once(tmp_path):
    source = Database(tmp_path / "source.db")
    account = source.create_account("Migrated Demo", 100.0)
    user = source.create_user(
        email="migrate@test.local", name="Migrate", password_hash="hash",
        account_id=account["id"],
    )
    source.create_session("session-token", user["id"], "2099-01-01T00:00:00")
    source.set_user_setting(user["id"], "notifications", {"telegram": True})
    trade = source.insert_trade({
        "account_id": account["id"], "symbol": "EURUSD", "market": "forex",
        "side": "BUY", "quantity": 1, "entry_price": 1.1, "tp": 1.2, "sl": 1.0,
    })
    source.add_snapshot({
        "account_id": account["id"], "equity": 105, "cash": 105,
        "unrealized_pnl": 0, "realized_pnl": 5,
    })
    signal = source.insert_signal({
        "user_id": user["id"], "symbol": "EURUSD", "market": "forex",
        "label": "BUY", "timeframe": "1h", "price": 1.1,
    })
    source.add_alert({
        "user_id": user["id"], "symbol": "EURUSD", "title": "Alert", "message": "Message",
    })
    source.add_delivery_attempt({"user_id": user["id"], "alert_id": signal["id"], "ok": False})
    source.add_journal({"user_id": user["id"], "note": "Migrated journal entry"})
    source.save_backtest({
        "market": "forex", "symbol": "EURUSD", "period": "1y",
        "interval": "1d", "user_id": user["id"],
    })
    source.set_setting("legacy", {"kept": True})

    fresh_url, admin_url, name = _fresh_database(os.environ["MNZ_TEST_DATABASE_URL"])
    try:
        counts = migrate(source.path, fresh_url)
        assert counts["users"] == 1 and counts["trades"] == 1
        assert counts["delivery_attempts"] == 1

        target = Database(url=fresh_url)
        assert target.backend == "PostgreSQL"
        assert target.get_user_by_email("migrate@test.local")["id"] == user["id"]
        assert target.get_trade(trade["id"])["symbol"] == "EURUSD"
        assert target.get_session_user("session-token")["id"] == user["id"]
        assert target.get_user_setting(user["id"], "notifications") == {"telegram": True}
        assert target.get_setting("legacy") == {"kept": True}
        assert len(target.list_journal(user["id"])) == 1
        assert len(target.list_delivery_attempts(user["id"])) == 1

        # Sequences must continue after the preserved ids.
        assert target.create_account("Second", 100.0)["id"] > account["id"]
        assert target.create_user(
            email="second@test.local", name="Second", password_hash="hash",
            account_id=account["id"],
        )["id"] > user["id"]

        with pytest.raises(RuntimeError, match="not empty"):
            migrate(source.path, fresh_url)
        assert target.count_users() == 2
    finally:
        _drop_database(admin_url, name)
