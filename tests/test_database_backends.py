"""Backend selection and Postgres dialect translation.

The live Postgres round-trip runs only when MNZ_TEST_DATABASE_URL is set, so
the normal suite stays SQLite-only and dependency-free.
"""

import os

import pytest

import config
from database import database as database_module
from database.database import (
    Database,
    _normalise_url,
    _pg_candidates,
    _pg_conninfo,
    _pg_ddl,
    _pg_retry,
    _pg_sql,
)

NEON_POOLED = (
    "postgresql://mnz:secret@ep-cool-darkness-a1b2c3d4-pooler.eu-central-1.aws.neon.tech"
    "/neondb?sslmode=require&channel_binding=require"
)


@pytest.fixture()
def pg_state():
    """Clear the module-level pool caches around each Postgres unit test."""
    database_module._PG_POOLS.clear()
    database_module._PG_READY.clear()
    database_module._PG_EFFECTIVE.clear()
    yield
    database_module._PG_POOLS.clear()
    database_module._PG_READY.clear()
    database_module._PG_EFFECTIVE.clear()


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


def test_normalise_url_accepts_the_quoted_value_from_the_docs():
    pasted = f'  "{NEON_POOLED}"  '
    assert _normalise_url(pasted) == NEON_POOLED
    assert _normalise_url("postgres://u:p@host/db") == "postgresql://u:p@host/db"


def test_pg_conninfo_keeps_the_neon_pooled_options():
    """The exact Neon string must reach libpq with its pooling and TLS intact."""
    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(_pg_conninfo(NEON_POOLED))
    assert info["host"].endswith("-pooler.eu-central-1.aws.neon.tech")
    assert info["sslmode"] == "require"
    assert info["channel_binding"] == "require"
    assert info["dbname"] == "neondb"
    assert info["connect_timeout"] == str(database_module._PG_CONNECT_TIMEOUT)
    assert info["application_name"] == "mnz-bot"


def test_pg_conninfo_never_overrides_explicit_options():
    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(
        _pg_conninfo("postgresql://u:p@h/db?sslmode=verify-full&connect_timeout=3")
    )
    assert info["sslmode"] == "verify-full"
    assert info["connect_timeout"] == "3"


def test_pg_conninfo_passes_unparseable_strings_through():
    broken = "postgresql://u:p@host/db?not_an_option=1"
    assert _pg_conninfo(broken) == broken


def test_pg_candidates_relax_channel_binding_only_as_a_fallback():
    candidates = _pg_candidates(NEON_POOLED)
    assert candidates[0] == NEON_POOLED
    assert len(candidates) == 2
    assert "channel_binding=prefer" in candidates[1]
    assert "channel_binding=require" not in candidates[1]
    assert "sslmode=require" in candidates[1]

    assert _pg_candidates("postgresql://u:p@h/db") == ["postgresql://u:p@h/db"]


def test_pg_pool_validates_and_recycles_connections(pg_state, monkeypatch):
    """A suspended provider kills idle connections; the pool must replace them."""
    import psycopg_pool

    recorded = {}
    real_check = psycopg_pool.ConnectionPool.check_connection

    class FakePool:
        check_connection = staticmethod(real_check)

        def __init__(self, conninfo, **kwargs):
            recorded["conninfo"] = conninfo
            recorded.update(kwargs)

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", FakePool)
    monkeypatch.setattr(database_module, "_pg_probe", lambda conninfo: None)

    pool = database_module._pg_pool(NEON_POOLED)
    assert isinstance(pool, FakePool)
    assert recorded["check"] is real_check
    assert recorded["min_size"] == 1 and recorded["max_size"] == 4
    assert recorded["max_lifetime"] == database_module._PG_MAX_LIFETIME
    assert recorded["reconnect_timeout"] == database_module._PG_POOL_TIMEOUT
    # Transaction-mode pooling: no server-side prepared statements.
    assert recorded["kwargs"]["prepare_threshold"] is None
    assert "-pooler" in recorded["conninfo"]
    # A second call reuses the cached pool instead of reconnecting.
    assert database_module._pg_pool(NEON_POOLED) is pool


def test_pg_pool_keeps_prepared_statements_for_a_direct_host(pg_state, monkeypatch):
    import psycopg_pool

    recorded = {}

    class FakePool:
        check_connection = staticmethod(lambda conn: None)

        def __init__(self, conninfo, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", FakePool)
    monkeypatch.setattr(database_module, "_pg_probe", lambda conninfo: None)

    database_module._pg_pool("postgresql://u:p@db.example.com/app")
    assert "prepare_threshold" not in recorded["kwargs"]


def test_pg_pool_retries_without_channel_binding_when_rejected(pg_state, monkeypatch):
    import psycopg
    import psycopg_pool

    tried = []
    recorded = {}

    class FakePool:
        check_connection = staticmethod(lambda conn: None)

        def __init__(self, conninfo, **kwargs):
            recorded["conninfo"] = conninfo

    def probe(conninfo):
        tried.append(conninfo)
        if "channel_binding=require" in conninfo:
            raise psycopg.OperationalError(
                "channel binding required, but the server does not support it"
            )

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", FakePool)
    monkeypatch.setattr(database_module, "_pg_probe", probe)
    monkeypatch.setattr(database_module, "_pg_retry", lambda action, **kw: action())

    database_module._pg_pool(NEON_POOLED)
    assert len(tried) == 2
    assert "channel_binding=prefer" in recorded["conninfo"]
    assert database_module._PG_EFFECTIVE[NEON_POOLED] == recorded["conninfo"]


def test_pg_pool_reports_a_clear_error_when_unreachable(pg_state, monkeypatch):
    import psycopg
    import psycopg_pool

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", lambda *a, **k: None)

    def probe(conninfo):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(database_module, "_pg_probe", probe)
    monkeypatch.setattr(database_module, "_pg_retry", lambda action, **kw: action())

    with pytest.raises(database_module.DatabaseUnavailable, match="Check DATABASE_URL"):
        database_module._pg_pool(NEON_POOLED)
    assert not database_module._PG_POOLS


def test_pg_retry_recovers_from_a_transient_failure():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("server closed the connection unexpectedly")
        return "ok"

    assert _pg_retry(flaky, base_delay=0) == "ok"
    assert len(calls) == 3


def test_pg_retry_gives_up_after_the_last_attempt():
    calls = []

    def always_fails():
        calls.append(1)
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        _pg_retry(always_fails, base_delay=0)
    assert len(calls) == database_module._PG_ATTEMPTS


def test_session_turns_a_pool_timeout_into_a_readable_error(pg_state, monkeypatch):
    from psycopg_pool import PoolTimeout

    class FailingPool:
        def connection(self):
            raise PoolTimeout("couldn't get a connection after 20.00 sec")

    monkeypatch.setattr(database_module, "_pg_pool", lambda url: FailingPool())

    db = Database.__new__(Database)
    db.url = NEON_POOLED
    db.backend = "PostgreSQL"
    db.path = None

    with pytest.raises(database_module.DatabaseUnavailable,
                       match="did not accept a connection in time"):
        with db.session():
            pass


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
