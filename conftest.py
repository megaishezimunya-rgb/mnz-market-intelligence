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
def _clear_login_throttle():
    """Failed-login state is process-wide, so every test starts from zero."""
    from auth import throttle

    throttle.reset()
    yield
    throttle.reset()
