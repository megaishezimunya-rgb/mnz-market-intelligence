"""The temporary-storage warning must be visible exactly when records can be wiped.

Without ``DATABASE_URL`` the app writes to a local SQLite file that a host may
erase on restart, so Login, Register and every signed-in section warn about it.
With PostgreSQL behind the app the warning must disappear.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
import state  # noqa: E402
from auth import hash_password  # noqa: E402
from database.database import Database  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(_ROOT / "app.py")
WARNING = "Temporary storage"


@pytest.fixture()
def sqlite_env(tmp_path, monkeypatch):
    """A signed-in user on the SQLite fallback, i.e. no DATABASE_URL."""
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "storage.db")
    state.get_database.clear()

    db = Database(config.DB_PATH)
    account = db.create_account("Storage Demo", config.DEMO_STARTING_BALANCE)
    user = db.create_user(
        email="storage@example.com", name="Storage User",
        password_hash=hash_password("password123"), account_id=int(account["id"]),
    )
    yield db, user
    state.get_database.clear()


def _markdown(at: AppTest) -> str:
    return "\n".join(str(element.value) for element in at.markdown)


def _signed_in(user: dict) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["mnz_user"] = user
    at.session_state["_mnz_bootstrapped"] = True
    return at


def test_storage_is_durable_tracks_the_database_backend(monkeypatch):
    monkeypatch.setattr(state, "get_database",
                        lambda: SimpleNamespace(backend="PostgreSQL"))
    assert state.storage_is_durable() is True

    monkeypatch.setattr(state, "get_database",
                        lambda: SimpleNamespace(backend="SQLite"))
    assert state.storage_is_durable() is False


@pytest.mark.parametrize("page", ["Login", "Register"])
def test_warning_shown_before_signing_in(sqlite_env, page):
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["public_page"] = page
    at.run()

    assert not at.exception, at.exception
    rendered = _markdown(at)
    assert WARNING in rendered
    assert "can be erased" in rendered


def test_warning_stays_off_marketing_pages(sqlite_env):
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["public_page"] = "Home"
    at.run()

    assert not at.exception, at.exception
    assert WARNING not in _markdown(at)


@pytest.mark.parametrize("page", ["Home", "Demo", "Settings"])
def test_warning_shown_on_signed_in_pages(sqlite_env, page):
    _, user = sqlite_env
    at = _signed_in(user)
    at.session_state["mnz_page"] = page
    at.session_state["nav_radio"] = page
    at.run()

    assert not at.exception, at.exception
    assert WARNING in _markdown(at)


def test_warning_hidden_when_postgres_backs_the_app(sqlite_env, monkeypatch):
    _, user = sqlite_env
    monkeypatch.setattr(state, "storage_is_durable", lambda: True)

    public = AppTest.from_file(APP, default_timeout=90)
    public.session_state["public_page"] = "Login"
    public.run()
    assert not public.exception, public.exception
    assert WARNING not in _markdown(public)

    signed_in = _signed_in(user)
    signed_in.run()
    assert not signed_in.exception, signed_in.exception
    assert WARNING not in _markdown(signed_in)
