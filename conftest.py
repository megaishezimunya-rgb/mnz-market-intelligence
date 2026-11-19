"""Pytest bootstrap: make the project root importable and share fixtures."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.database import Database  # noqa: E402  (after sys.path setup)


@pytest.fixture()
def db(tmp_path):
    """A throwaway SQLite database per test."""
    return Database(tmp_path / "mnz_test.db")


@pytest.fixture(autouse=True)
def _clear_login_throttle(monkeypatch):
    """Failed-login state is process-wide, so every test starts from zero.

    The stored counter is detached for the test run: unit tests must never
    clear rows in a developer's real database, and tests that check durable
    counters build their own ``AttemptThrottle(store=db)``.
    """
    from auth import throttle

    monkeypatch.setattr(throttle, "_store", None)
    throttle.reset()
    yield
    throttle.reset()
