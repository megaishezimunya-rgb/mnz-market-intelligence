"""SQLite persistence for MNZ BOT.

Tables
------
users             local accounts (email, name, PBKDF2 hash, demo account link)
sessions          hashed session tokens with expiry
accounts          virtual demo accounts (cash balance, starting balance)
trades            every simulated position, open and closed
equity_snapshots  recorded virtual equity over time (drawdown history)
settings          legacy JSON key/value store
user_settings     per-user JSON settings (profile, notifications, display)
signals           persisted scanner / signal-centre signals with outcomes
alerts            smart-alert history and in-app notifications
journal           intelligent trading journal entries
backtest_runs     saved backtest summaries for the strategy lab
delivery_attempts outbound alert-delivery outcomes (survives restarts, capped)
login_attempts    failed sign-in / registration counters per email (backoff)

Every user-owned row is scoped by ``user_id`` (signals, alerts, journal,
settings) or by ``account_id`` (trades, snapshots), so one account can never
read another's data.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    account_id    INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

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
    created_at    TEXT NOT NULL,
    tp            REAL,
    sl            REAL,
    slot          INTEGER,
    signal_id     INTEGER,
    timeframe     TEXT DEFAULT ''
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

CREATE TABLE IF NOT EXISTS user_settings (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol        TEXT NOT NULL,
    market        TEXT NOT NULL,
    label         TEXT NOT NULL,
    timeframe     TEXT NOT NULL,
    price         REAL NOT NULL,
    entry_ref     REAL,
    tp            REAL,
    sl            REAL,
    strength      TEXT NOT NULL DEFAULT 'Weak',
    quality       INTEGER NOT NULL DEFAULT 0,
    score         REAL NOT NULL DEFAULT 0,
    explanation   TEXT DEFAULT '',
    metrics_json  TEXT DEFAULT '{}',
    data_quality  TEXT DEFAULT 'unavailable',
    source        TEXT DEFAULT '',
    is_sample     INTEGER NOT NULL DEFAULT 0,
    bar_time      TEXT,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'Open',
    outcome       TEXT DEFAULT '',
    outcome_price REAL,
    outcome_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_user_created ON signals(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_signals_user_symbol ON signals(user_id, symbol);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol     TEXT NOT NULL,
    market     TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'signal',
    severity   TEXT NOT NULL DEFAULT 'info',
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    signal_id  INTEGER,
    created_at TEXT NOT NULL,
    read_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_user_created ON alerts(user_id, created_at);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    alert_id   TEXT,
    ok         INTEGER NOT NULL DEFAULT 0,
    error      TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delivery_user_created ON delivery_attempts(user_id, created_at);

CREATE TABLE IF NOT EXISTS journal (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trade_id   INTEGER,
    symbol     TEXT DEFAULT '',
    note       TEXT NOT NULL,
    tags       TEXT DEFAULT '',
    mood       TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_user ON journal(user_id, created_at);

CREATE TABLE IF NOT EXISTS login_attempts (
    email_key    TEXT PRIMARY KEY,
    failures     INTEGER NOT NULL DEFAULT 0,
    last_failure REAL NOT NULL,
    updated_at   TEXT NOT NULL
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
    is_sample      INTEGER NOT NULL DEFAULT 0,
    user_id        INTEGER
);
"""

# Delivery history is a diagnostic, not an audit log: keep it small.
DELIVERY_HISTORY_LIMIT = 50

# A failed-attempt counter older than this is noise; it is pruned on write.
LOGIN_ATTEMPT_RETENTION_SECONDS = 7 * 24 * 60 * 60

TRADE_FIELDS = [
    "id", "account_id", "symbol", "market", "side", "quantity", "entry_price",
    "entry_time", "exit_price", "exit_time", "costs", "realized_pnl", "status",
    "notes", "strategy", "created_at", "tp", "sl", "slot", "signal_id", "timeframe",
]

_SIGNAL_FIELDS = [
    "id", "user_id", "symbol", "market", "label", "timeframe", "price", "entry_ref",
    "tp", "sl", "strength", "quality", "score", "explanation", "metrics_json",
    "data_quality", "source", "is_sample", "bar_time", "created_at", "status",
    "outcome", "outcome_price", "outcome_at",
]


def _now() -> str:
    return config.utcnow().isoformat(timespec="seconds")


def _row_to_dict(row: Any) -> dict | None:
    return dict(row) if row is not None else None


# --------------------------------------------------------------------------- #
# PostgreSQL support
#
# The rest of the app speaks one dialect: ``?`` placeholders, SQLite DDL and
# ``cursor.lastrowid``. A small connection wrapper translates that to psycopg
# on the way out, so every query and the whole public Database API stay in one
# place. SQLite remains the default; Postgres is used only when DATABASE_URL
# is configured (or a test passes MNZ_TEST_DATABASE_URL).
# --------------------------------------------------------------------------- #
class DatabaseUnavailable(RuntimeError):
    """The configured PostgreSQL database cannot be reached right now.

    Raised for an unreachable host, a suspended compute and a pool timeout —
    never for a schema or query bug — so the UI can offer a retry.
    """


_PG_POOLS: dict[str, Any] = {}
_PG_READY: set[str] = set()
_PG_EFFECTIVE: dict[str, str] = {}
_PG_LOCK = threading.Lock()
_PG_BUILD_LOCK = threading.Lock()
_PG_INIT_LOCK = threading.Lock()

# A hosted Postgres (Neon, Supabase, RDS) suspends an idle compute and closes
# its connections. The pool must hand out a live connection instead of a dead
# one, so it validates each connection before use, recycles connections before
# the provider ages them out, and bounds how long a request waits.
_PG_POOL_TIMEOUT = 20.0      # seconds to wait for a connection from the pool
_PG_CONNECT_TIMEOUT = 10     # seconds for a single TCP/TLS/auth handshake
_PG_MAX_LIFETIME = 300.0     # recycle before a provider idle timeout can kill it
_PG_MAX_IDLE = 120.0
_PG_ATTEMPTS = 3


def _normalise_url(url: str) -> str:
    """Clean up a pasted connection string without changing its meaning."""
    url = (url or "").strip()
    if len(url) >= 2 and url[0] == url[-1] and url[0] in "\"'":
        # People often paste the quoted TOML value from the docs.
        url = url[1:-1].strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _pg_conninfo(url: str) -> str:
    """Add the options a hosted Postgres needs, keeping the provider's own.

    Neon hands out ``...?sslmode=require&channel_binding=require`` and a
    ``-pooler`` hostname. Both are preserved exactly as sent; this only fills
    in a connect timeout and an application name when they are missing, and
    requires TLS for a Neon host if the string somehow lacks it.
    """
    try:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
    except ImportError:  # pragma: no cover - psycopg is in requirements
        return url
    try:
        info = conninfo_to_dict(url)
    except Exception:
        # Not parseable by libpq: hand it over untouched so psycopg reports
        # the real problem instead of a rewritten one.
        return url
    info.setdefault("connect_timeout", str(_PG_CONNECT_TIMEOUT))
    info.setdefault("application_name", "mnz-bot")
    if (info.get("host") or "").endswith(".neon.tech"):
        info.setdefault("sslmode", "require")
    try:
        return make_conninfo(**info)
    except Exception:
        return url


def _pg_is_pooled(conninfo: str) -> bool:
    """True for a PgBouncer endpoint (Neon's pooled ``-pooler`` hostname)."""
    try:
        from psycopg.conninfo import conninfo_to_dict

        host = conninfo_to_dict(conninfo).get("host") or ""
    except Exception:
        host = conninfo
    return "-pooler" in host


def _pg_candidates(conninfo: str) -> list[str]:
    """Connection strings to try, strictest first.

    ``channel_binding=require`` fails outright against a pooler or a driver
    build that cannot negotiate SCRAM channel binding, so the second candidate
    relaxes it to ``prefer`` while keeping TLS mandatory.
    """
    candidates = [conninfo]
    try:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        info = conninfo_to_dict(conninfo)
    except Exception:
        return candidates
    if info.get("channel_binding") == "require":
        relaxed = dict(info)
        relaxed["channel_binding"] = "prefer"
        try:
            candidates.append(make_conninfo(**relaxed))
        except Exception:
            pass
    return candidates


def _pg_retry(action, *, attempts: int = _PG_ATTEMPTS, base_delay: float = 0.4):
    """Run ``action`` again on a transient failure, with a short backoff."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if attempt < attempts:
                time.sleep(base_delay * attempt)
    assert last is not None
    raise last


def _pg_probe(conninfo: str) -> None:
    """Open and close one connection so config errors surface immediately."""
    import psycopg

    kwargs: dict[str, Any] = {}
    if _pg_is_pooled(conninfo):
        # PgBouncer in transaction mode does not keep a backend session, so
        # protocol-level prepared statements must stay off.
        kwargs["prepare_threshold"] = None
    with psycopg.connect(conninfo, **kwargs):
        pass


def _pg_make_pool(conninfo: str):
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    kwargs: dict[str, Any] = {"row_factory": dict_row}
    if _pg_is_pooled(conninfo):
        kwargs["prepare_threshold"] = None
    return ConnectionPool(
        conninfo,
        min_size=1,
        max_size=4,
        open=True,
        # Validates each connection before it is handed out, which is how a
        # connection killed by a suspended compute is discarded and replaced.
        check=ConnectionPool.check_connection,
        timeout=_PG_POOL_TIMEOUT,
        reconnect_timeout=_PG_POOL_TIMEOUT,
        max_lifetime=_PG_MAX_LIFETIME,
        max_idle=_PG_MAX_IDLE,
        kwargs=kwargs,
    )


def _pg_pool(url: str):
    try:
        import psycopg_pool  # noqa: F401 - dependency check
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise RuntimeError(
            "PostgreSQL storage requires psycopg[binary,pool]. "
            "Install requirements.txt or unset DATABASE_URL."
        ) from exc
    with _PG_LOCK:
        pool = _PG_POOLS.get(url)
    if pool is not None:
        return pool

    # Building a pool talks to the network, so it happens outside _PG_LOCK.
    with _PG_BUILD_LOCK:
        with _PG_LOCK:
            pool = _PG_POOLS.get(url)
            if pool is not None:
                return pool

        chosen = None
        failure: Exception | None = None
        for candidate in _pg_candidates(_pg_conninfo(url)):
            try:
                _pg_retry(lambda c=candidate: _pg_probe(c))
            except Exception as exc:  # noqa: BLE001 - reported below
                failure = exc
                if "channel binding" in str(exc).lower():
                    continue  # try the relaxed candidate
                raise DatabaseUnavailable(
                    "Could not connect to the PostgreSQL database. "
                    f"Check DATABASE_URL ({exc.__class__.__name__}: {exc})."
                ) from exc
            chosen = candidate
            break

        if chosen is None:
            raise DatabaseUnavailable(
                "Could not connect to the PostgreSQL database. "
                f"Check DATABASE_URL ({failure.__class__.__name__}: {failure})."
            ) from failure

        pool = _pg_make_pool(chosen)
        with _PG_LOCK:
            _PG_POOLS[url] = pool
            _PG_EFFECTIVE[url] = chosen
        return pool


def _pg_ddl(statement: str) -> str:
    """Convert the SQLite schema fragments Postgres spells differently."""
    statement = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY",
        statement, flags=re.IGNORECASE,
    )
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", statement, flags=re.IGNORECASE)


# Tables whose rows expose ``cursor.lastrowid`` after an insert.
_ID_TABLES = frozenset({
    "users", "accounts", "trades", "equity_snapshots", "signals", "alerts",
    "delivery_attempts", "journal", "backtest_runs",
})


def _pg_sql(sql: str) -> tuple[str, bool]:
    """Translate one statement and say whether it returns a new row id."""
    text = sql.replace("?", "%s")
    upper = text.lstrip().upper()
    if "INSERT OR REPLACE INTO SESSIONS" in upper:
        text = re.sub(
            r"INSERT\s+OR\s+REPLACE\s+INTO\s+sessions", "INSERT INTO sessions",
            text, flags=re.IGNORECASE,
        )
        text += (
            " ON CONFLICT (token_hash) DO UPDATE SET user_id = EXCLUDED.user_id,"
            " created_at = EXCLUDED.created_at, expires_at = EXCLUDED.expires_at"
        )
        return text, False
    match = re.match(r"INSERT\s+INTO\s+([A-Za-z_]+)", upper)
    returns_id = (
        bool(match)
        and match.group(1).lower() in _ID_TABLES
        and "ON CONFLICT" not in upper
        and "RETURNING" not in upper
    )
    if returns_id:
        text += " RETURNING id"
    return text, returns_id


class _PgCursor:
    def __init__(self, cursor: Any, lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list:
        return self._cursor.fetchall()


class _PgConnection:
    """Connection-shaped facade that accepts the app's SQLite-style calls."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Any = ()) -> _PgCursor:
        text, returns_id = _pg_sql(sql)
        cursor = self._conn.execute(text, params)
        row_id = None
        if returns_id:
            row = cursor.fetchone()
            row_id = int(row["id"]) if row else None
        return _PgCursor(cursor, row_id)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self._conn.execute(_pg_ddl(statement))


class Database:
    """Persistence facade: SQLite by default, PostgreSQL via DATABASE_URL."""

    def __init__(self, path: str | Path | None = None, *, url: str | None = None) -> None:
        url = "" if path is not None else _normalise_url(url or config.DATABASE_URL)
        self.url = url
        self.backend = "PostgreSQL" if url else "SQLite"
        self.path = None if url else Path(path or config.DB_PATH)
        if url:
            self._initialise_postgres()
        else:
            assert self.path is not None
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialise()

    # -- connection --------------------------------------------------------- #
    @contextmanager
    def session(self) -> Iterator[Any]:
        if self.url:
            from psycopg_pool import PoolTimeout

            try:
                with _pg_pool(self.url).connection() as conn:
                    yield _PgConnection(conn)
            except PoolTimeout as exc:
                raise DatabaseUnavailable(
                    "The PostgreSQL database did not accept a connection in time. "
                    "It may be waking up, or DATABASE_URL may be wrong. Try again."
                ) from exc
            return
        assert self.path is not None
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
            self._migrate(conn)

    def _initialise_postgres(self) -> None:
        with _PG_INIT_LOCK:  # schema and migrations run once, without races
            with _PG_LOCK:
                ready = self.url in _PG_READY
            if ready:
                return

            def create() -> None:
                with _pg_pool(self.url).connection() as conn:
                    _PgConnection(conn).executescript(SCHEMA)
                    self._migrate_postgres(conn)

            # A suspended compute or a dropped first connection is retried
            # rather than turned into a login error page. The schema uses
            # IF NOT EXISTS, and a failed attempt is rolled back by the pool.
            try:
                _pg_retry(create)
            except DatabaseUnavailable:
                raise  # already readable; do not nest the same message twice
            except Exception as exc:  # noqa: BLE001 - reported below
                raise DatabaseUnavailable(
                    "PostgreSQL storage could not be prepared. "
                    f"Check DATABASE_URL ({exc.__class__.__name__}: {exc})."
                ) from exc
            with _PG_LOCK:
                _PG_READY.add(self.url)

    def _migrate_postgres(self, conn: Any) -> None:
        def columns(table: str) -> set[str]:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (table,),
            ).fetchall()
            return {row["column_name"] for row in rows}

        existing = columns("trades")
        for column, ddl in {
            "tp": "REAL", "sl": "REAL", "slot": "INTEGER",
            "signal_id": "INTEGER", "timeframe": "TEXT DEFAULT ''",
        }.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {column} {_pg_ddl(ddl)}")
        if "user_id" not in columns("backtest_runs"):
            conn.execute("ALTER TABLE backtest_runs ADD COLUMN user_id INTEGER")

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after the first schema, safely."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(trades)")}
        for column, ddl in {
            "tp": "REAL", "sl": "REAL", "slot": "INTEGER",
            "signal_id": "INTEGER", "timeframe": "TEXT DEFAULT ''",
        }.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {column} {ddl}")
        run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(backtest_runs)")}
        if "user_id" not in run_columns:
            conn.execute("ALTER TABLE backtest_runs ADD COLUMN user_id INTEGER")

    # ------------------------------------------------------------------ #
    # Users and sessions
    # ------------------------------------------------------------------ #
    def create_user(self, *, email: str, name: str, password_hash: str, account_id: int) -> dict:
        stamp = _now()
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO users (email, name, password_hash, account_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (email.strip().lower(), name.strip(), password_hash, int(account_id), stamp, stamp),
            )
            user_id = int(cursor.lastrowid)
        user = self.get_user(user_id)
        assert user is not None
        return user

    def get_user(self, user_id: int) -> dict | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        return _row_to_dict(row)

    def get_user_by_email(self, email: str) -> dict | None:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)
            ).fetchone()
        return _row_to_dict(row)

    def update_user(self, user_id: int, *, name: str | None = None, password_hash: str | None = None) -> None:
        fields: dict[str, Any] = {}
        if name:
            fields["name"] = name.strip()
        if password_hash:
            fields["password_hash"] = password_hash
        if not fields:
            return
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.session() as conn:
            conn.execute(f"UPDATE users SET {assignments} WHERE id = ?",
                         (*fields.values(), int(user_id)))

    def count_users(self) -> int:
        with self.session() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"]) if row else 0

    def create_session(self, token_hash: str, user_id: int, expires_at: str) -> None:
        with self.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token_hash, int(user_id), _now(), expires_at),
            )

    def get_session_user(self, token_hash: str) -> dict | None:
        with self.session() as conn:
            row = conn.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.expires_at > ?",
                (token_hash, _now()),
            ).fetchone()
        return _row_to_dict(row)

    def delete_session(self, token_hash: str) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_user_sessions(self, user_id: int,
                             keep_token_hash: str | None = None) -> None:
        """Drop a user's sessions, optionally sparing the one still in use.

        Used when a password changes so a stolen session cannot outlive it.
        """
        with self.session() as conn:
            if keep_token_hash:
                conn.execute(
                    "DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?",
                    (int(user_id), keep_token_hash),
                )
            else:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))

    def purge_expired_sessions(self) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_now(),))

    # ------------------------------------------------------------------ #
    # Failed sign-in attempts (login and registration backoff)
    # ------------------------------------------------------------------ #
    def get_login_attempt(self, email_key: str) -> dict | None:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM login_attempts WHERE email_key = ?",
                ((email_key or "").strip().lower(),),
            ).fetchone()
        return _row_to_dict(row)

    def save_login_attempt(self, email_key: str, *, failures: int, last_failure: float) -> None:
        key = (email_key or "").strip().lower()
        cutoff = last_failure - LOGIN_ATTEMPT_RETENTION_SECONDS
        with self.session() as conn:
            conn.execute(
                "INSERT INTO login_attempts (email_key, failures, last_failure, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(email_key) DO UPDATE SET "
                "failures = excluded.failures, last_failure = excluded.last_failure, "
                "updated_at = excluded.updated_at",
                (key, int(failures), float(last_failure), _now()),
            )
            # Bounded table: counters nobody has triggered for a week are dropped.
            conn.execute("DELETE FROM login_attempts WHERE last_failure < ?", (float(cutoff),))

    def clear_login_attempt(self, email_key: str) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM login_attempts WHERE email_key = ?",
                         ((email_key or "").strip().lower(),))

    def clear_login_attempts(self) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM login_attempts")

    # ------------------------------------------------------------------ #
    # Per-user settings
    # ------------------------------------------------------------------ #
    def set_user_setting(self, user_id: int, key: str, value: Any) -> None:
        with self.session() as conn:
            conn.execute(
                "INSERT INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (int(user_id), key, json.dumps(value), _now()),
            )

    def get_user_setting(self, user_id: int, key: str, default: Any = None) -> Any:
        with self.session() as conn:
            row = conn.execute(
                "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
                (int(user_id), key),
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return default

    def all_user_settings(self, user_id: int) -> dict:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT key, value FROM user_settings WHERE user_id = ?", (int(user_id),)
            ).fetchall()
        out: dict[str, Any] = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                out[row["key"]] = row["value"]
        return out

    # ------------------------------------------------------------------ #
    # Accounts
    # ------------------------------------------------------------------ #
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
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (int(account_id),)).fetchone()
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
                (float(cash_balance), _now(), int(account_id)),
            )

    def reset_account(self, account_id: int, starting_balance: float | None = None) -> dict:
        with self.session() as conn:
            row = conn.execute("SELECT starting_balance FROM accounts WHERE id = ?",
                               (int(account_id),)).fetchone()
            if row is None:
                raise ValueError(f"Account {account_id} does not exist.")
            balance = float(starting_balance if starting_balance is not None else row["starting_balance"])
            conn.execute("DELETE FROM trades WHERE account_id = ?", (int(account_id),))
            conn.execute("DELETE FROM equity_snapshots WHERE account_id = ?", (int(account_id),))
            conn.execute(
                "UPDATE accounts SET cash_balance = ?, starting_balance = ?, updated_at = ? WHERE id = ?",
                (balance, balance, _now(), int(account_id)),
            )
        account = self.get_account(account_id)
        assert account is not None
        return account

    # ------------------------------------------------------------------ #
    # Trades
    # ------------------------------------------------------------------ #
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
            "tp": payload.get("tp"),
            "sl": payload.get("sl"),
            "slot": payload.get("slot"),
            "signal_id": payload.get("signal_id"),
            "timeframe": payload.get("timeframe", ""),
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
            row = conn.execute("SELECT * FROM trades WHERE id = ?", (int(trade_id),)).fetchone()
        return _row_to_dict(row)

    def update_trade(self, trade_id: int, fields: dict) -> dict:
        allowed = {k: v for k, v in fields.items()
                   if k in TRADE_FIELDS and k not in {"id", "created_at"}}
        if not allowed:
            return self.get_trade(trade_id) or {}
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        with self.session() as conn:
            conn.execute(f"UPDATE trades SET {assignments} WHERE id = ?",
                         (*allowed.values(), int(trade_id)))
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
        params: list[Any] = [int(account_id)]
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
            conn.execute("DELETE FROM trades WHERE id = ?", (int(trade_id),))

    # ------------------------------------------------------------------ #
    # Equity snapshots
    # ------------------------------------------------------------------ #
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
            row = conn.execute("SELECT * FROM equity_snapshots WHERE id = ?",
                               (snapshot_id,)).fetchone()
        return dict(row) if row else {}

    def list_snapshots(self, account_id: int,
                       limit: int = config.EQUITY_HISTORY_LIMIT) -> list[dict]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM equity_snapshots WHERE account_id = ? ORDER BY ts ASC, id ASC LIMIT ?",
                (int(account_id), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_snapshot(self, account_id: int) -> dict | None:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM equity_snapshots WHERE account_id = ? ORDER BY ts DESC, id DESC LIMIT 1",
                (int(account_id),),
            ).fetchone()
        return _row_to_dict(row)

    # ------------------------------------------------------------------ #
    # Signals
    # ------------------------------------------------------------------ #
    def insert_signal(self, payload: dict) -> dict:
        values = {
            "user_id": int(payload["user_id"]),
            "symbol": payload["symbol"],
            "market": payload.get("market", ""),
            "label": payload["label"],
            "timeframe": payload.get("timeframe", config.DEFAULT_TIMEFRAME),
            "price": float(payload["price"]),
            "entry_ref": payload.get("entry_ref"),
            "tp": payload.get("tp"),
            "sl": payload.get("sl"),
            "strength": payload.get("strength", "Weak"),
            "quality": int(payload.get("quality", 0)),
            "score": float(payload.get("score", 0.0)),
            "explanation": payload.get("explanation", ""),
            "metrics_json": json.dumps(payload.get("metrics", {}), default=str),
            "data_quality": payload.get("data_quality", "unavailable"),
            "source": payload.get("source", ""),
            "is_sample": 1 if payload.get("is_sample") else 0,
            "bar_time": payload.get("bar_time"),
            "created_at": payload.get("created_at") or _now(),
            "status": payload.get("status", "Open"),
            "outcome": payload.get("outcome", ""),
            "outcome_price": payload.get("outcome_price"),
            "outcome_at": payload.get("outcome_at"),
        }
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self.session() as conn:
            cursor = conn.execute(
                f"INSERT INTO signals ({columns}) VALUES ({placeholders})", tuple(values.values())
            )
            signal_id = int(cursor.lastrowid)
        signal = self.get_signal(signal_id)
        assert signal is not None
        return signal

    def get_signal(self, signal_id: int) -> dict | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM signals WHERE id = ?", (int(signal_id),)).fetchone()
        return _row_to_dict(row)

    def list_signals(
        self,
        user_id: int,
        *,
        symbol: str | None = None,
        market: str | None = None,
        label: str | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        query = "SELECT * FROM signals WHERE user_id = ?"
        params: list[Any] = [int(user_id)]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if market:
            query += " AND market = ?"
            params.append(market)
        if label:
            query += " AND label = ?"
            params.append(label)
        if status:
            query += " AND status = ?"
            params.append(status)
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        if until:
            query += " AND created_at <= ?"
            params.append(until + "T23:59:59")
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        with self.session() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def latest_signal_for(self, user_id: int, symbol: str, timeframe: str) -> dict | None:
        with self.session() as conn:
            row = conn.execute(
                "SELECT * FROM signals WHERE user_id = ? AND symbol = ? AND timeframe = ? "
                "ORDER BY id DESC LIMIT 1",
                (int(user_id), symbol, timeframe),
            ).fetchone()
        return _row_to_dict(row)

    def update_signal(self, signal_id: int, fields: dict) -> None:
        allowed = {k: v for k, v in fields.items()
                   if k in _SIGNAL_FIELDS and k not in {"id", "user_id", "created_at"}}
        if not allowed:
            return
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        with self.session() as conn:
            conn.execute(f"UPDATE signals SET {assignments} WHERE id = ?",
                         (*allowed.values(), int(signal_id)))

    def delete_signals(self, user_id: int) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM signals WHERE user_id = ?", (int(user_id),))

    def signal_counts(self, user_id: int) -> dict:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT label, COUNT(*) AS n FROM signals WHERE user_id = ? GROUP BY label",
                (int(user_id),),
            ).fetchall()
        return {row["label"]: int(row["n"]) for row in rows}

    # ------------------------------------------------------------------ #
    # Alerts
    # ------------------------------------------------------------------ #
    def add_alert(self, payload: dict) -> dict:
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO alerts (user_id, symbol, market, kind, severity, title, message, "
                "signal_id, created_at, read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(payload["user_id"]), payload.get("symbol", ""), payload.get("market", ""),
                    payload.get("kind", "signal"), payload.get("severity", "info"),
                    payload["title"], payload["message"], payload.get("signal_id"),
                    payload.get("created_at") or _now(), payload.get("read_at"),
                ),
            )
            alert_id = int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return dict(row) if row else {}

    def list_alerts(self, user_id: int, *, unread_only: bool = False, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM alerts WHERE user_id = ?"
        params: list[Any] = [int(user_id)]
        if unread_only:
            query += " AND read_at IS NULL"
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        with self.session() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def unread_alert_count(self, user_id: int) -> int:
        with self.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM alerts WHERE user_id = ? AND read_at IS NULL",
                (int(user_id),),
            ).fetchone()
        return int(row["n"]) if row else 0

    def mark_alerts_read(self, user_id: int) -> None:
        with self.session() as conn:
            conn.execute("UPDATE alerts SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
                         (_now(), int(user_id)))

    def clear_alerts(self, user_id: int) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM alerts WHERE user_id = ?", (int(user_id),))

    def alert_exists(self, user_id: int, symbol: str, bar_time: str | None) -> bool:
        if not bar_time:
            return False
        with self.session() as conn:
            row = conn.execute(
                "SELECT id FROM alerts WHERE user_id = ? AND symbol = ? AND created_at >= ? LIMIT 1",
                (int(user_id), symbol, bar_time),
            ).fetchone()
        return row is not None

    def alerts_since(self, user_id: int, since_iso: str) -> int:
        with self.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM alerts WHERE user_id = ? AND created_at >= ?",
                (int(user_id), since_iso),
            ).fetchone()
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------ #
    # Outbound delivery attempts
    # ------------------------------------------------------------------ #
    def add_delivery_attempt(self, payload: dict) -> dict:
        user_id = int(payload["user_id"])
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO delivery_attempts (user_id, alert_id, ok, error, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    user_id,
                    None if payload.get("alert_id") is None else str(payload["alert_id"]),
                    1 if payload.get("ok") else 0, payload.get("error", ""),
                    payload.get("created_at") or _now(),
                ),
            )
            # Trim older rows for this account so the table stays bounded.
            conn.execute(
                "DELETE FROM delivery_attempts WHERE user_id = ? AND id NOT IN "
                "(SELECT id FROM delivery_attempts WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
                (user_id, user_id, DELIVERY_HISTORY_LIMIT),
            )
            row = conn.execute("SELECT * FROM delivery_attempts WHERE id = ?",
                               (int(cursor.lastrowid),)).fetchone()
        return dict(row) if row else {}

    def list_delivery_attempts(self, user_id: int, limit: int = 10) -> list[dict]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM delivery_attempts WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (int(user_id), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Journal
    # ------------------------------------------------------------------ #
    def add_journal(self, payload: dict) -> dict:
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO journal (user_id, trade_id, symbol, note, tags, mood, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    int(payload["user_id"]), payload.get("trade_id"), payload.get("symbol", ""),
                    payload["note"], payload.get("tags", ""), payload.get("mood", ""),
                    payload.get("created_at") or _now(),
                ),
            )
            entry_id = int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM journal WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else {}

    def list_journal(self, user_id: int, limit: int = 100) -> list[dict]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM journal WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (int(user_id), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_journal(self, user_id: int, entry_id: int) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM journal WHERE id = ? AND user_id = ?",
                         (int(entry_id), int(user_id)))

    # ------------------------------------------------------------------ #
    # Legacy global settings
    # ------------------------------------------------------------------ #
    def set_setting(self, key: str, value: Any) -> None:
        with self.session() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, json.dumps(value), _now()),
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

    # ------------------------------------------------------------------ #
    # Backtests
    # ------------------------------------------------------------------ #
    def save_backtest(self, payload: dict) -> int:
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO backtest_runs (created_at, market, symbol, period, interval, "
                "settings_json, metrics_json, is_sample, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(), payload["market"], payload["symbol"], payload["period"],
                    payload["interval"], json.dumps(payload.get("settings", {})),
                    json.dumps(payload.get("metrics", {}), default=str),
                    1 if payload.get("is_sample") else 0, payload.get("user_id"),
                ),
            )
            return int(cursor.lastrowid)

    def list_backtests(self, limit: int = 50, user_id: int | None = None) -> list[dict]:
        query = "SELECT * FROM backtest_runs"
        params: list[Any] = []
        if user_id is not None:
            query += " WHERE user_id = ?"
            params.append(int(user_id))
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self.session() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
