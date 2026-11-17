"""One-time copy of a local SQLite database into PostgreSQL.

Run this once, from a machine that still has the SQLite file, before pointing
the app at PostgreSQL:

    DATABASE_URL="postgresql://..." python -m database.migrate --sqlite mnz_data/mnz.db

The target must be empty. Row ids are preserved, the copy runs in a single
transaction (all or nothing), and sequences are advanced so new rows do not
reuse ids. Running it again is refused because the target is no longer empty.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import config
from database.database import Database

# Parent tables first: PostgreSQL enforces the foreign keys SQLite declared.
TABLES = (
    "accounts", "users", "sessions", "user_settings", "trades",
    "equity_snapshots", "signals", "alerts", "delivery_attempts",
    "journal", "backtest_runs", "settings",
)
SERIAL_TABLES = (
    "accounts", "users", "trades", "equity_snapshots", "signals", "alerts",
    "delivery_attempts", "journal", "backtest_runs",
)


def insert_columns(source_columns: list[str], target_columns: set[str]) -> list[str]:
    """Keep columns that exist on both sides (older SQLite files lack newer ones)."""
    return [column for column in source_columns if column in target_columns]


def migrate(sqlite_path: str | Path, database_url: str | None = None) -> dict[str, int]:
    """Copy every table into an empty PostgreSQL database. Returns row counts."""
    source = Path(sqlite_path)
    if not source.exists():
        raise FileNotFoundError(f"SQLite database not found: {source}")
    url = (database_url or config.DATABASE_URL or "").strip()
    if not url:
        raise ValueError("Set DATABASE_URL (or pass --database-url) to the PostgreSQL target.")

    db = Database(url=url)
    if db.backend != "PostgreSQL":
        raise ValueError("Migration target must be PostgreSQL.")

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        existing = {
            row["name"]
            for row in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "users" not in existing:
            raise RuntimeError(f"{source} does not look like an MNZ BOT database.")

        counts: dict[str, int] = {}
        with db.session() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('mnz_sqlite_migration'))")
            target_columns: dict[str, set[str]] = defaultdict(set)
            for row in conn.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            ).fetchall():
                target_columns[row["table_name"]].add(row["column_name"])

            copied = [table for table in TABLES if table in existing]
            occupied = [
                table for table in copied
                if conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            ]
            if occupied:
                raise RuntimeError(
                    "Target database is not empty (rows in "
                    + ", ".join(occupied)
                    + "). Migration only runs into an empty database."
                )

            for table in copied:
                columns = insert_columns(
                    [row["name"] for row in src.execute(f"PRAGMA table_info({table})")],
                    target_columns[table],
                )
                if not columns:
                    raise RuntimeError(f"No shared columns for table {table}.")
                names = ", ".join(columns)
                placeholders = ", ".join("?" for _ in columns)
                rows = src.execute(f"SELECT {names} FROM {table}").fetchall()
                for row in rows:
                    conn.execute(
                        f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
                        tuple(row[column] for column in columns),
                    )
                counts[table] = len(rows)

            for table in SERIAL_TABLES:
                if counts.get(table):
                    conn.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"(SELECT MAX(id) FROM {table}))"
                    )

            for table, expected in counts.items():
                actual = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                if actual != expected:
                    raise RuntimeError(
                        f"Verification failed for {table}: copied {expected}, found {actual}."
                    )
        return counts
    finally:
        src.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sqlite", default=str(config.DB_PATH),
        help="Path to the existing SQLite file (default: %(default)s)",
    )
    parser.add_argument(
        "--database-url", default=config.DATABASE_URL,
        help="PostgreSQL connection string (default: DATABASE_URL)",
    )
    args = parser.parse_args(argv)
    try:
        counts = migrate(args.sqlite, args.database_url)
    except Exception as exc:  # report cleanly; the transaction already rolled back
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    print(f"Copied {sum(counts.values())} rows from {args.sqlite} into PostgreSQL:")
    for table, count in counts.items():
        print(f"  {table:<18} {count}")
    print("Done. Point the app at the same DATABASE_URL; this only needs to run once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
