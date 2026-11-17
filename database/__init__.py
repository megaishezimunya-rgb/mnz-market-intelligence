"""Persistence package: SQLite by default, PostgreSQL via DATABASE_URL."""

from database.database import Database

__all__ = ["Database"]
