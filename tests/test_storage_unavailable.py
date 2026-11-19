"""An unreachable database must not become a traceback on Login or Register.

The public site has to stay up, show one short sentence, offer a retry, and log
the real failure once. These tests drive the real Streamlit app with a broken
storage layer, so they cover the same path a visitor sees.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
import state  # noqa: E402
from database.database import DatabaseUnavailable  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(_ROOT / "app.py")
MESSAGE = "Cannot reach the account database"


class BrokenAuth:
    """Every account operation fails as if Postgres were suspended."""

    def authenticate(self, *args, **kwargs):
        raise DatabaseUnavailable("connection refused while waking up")

    def register(self, *args, **kwargs):
        raise DatabaseUnavailable("connection refused while waking up")

    def start_session(self, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("start_session must not run without a user")

    def user_for_token(self, *args, **kwargs):
        raise DatabaseUnavailable("connection refused while waking up")


@pytest.fixture()
def sqlite_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "unavailable.db")
    state.get_database.clear()
    state._LOGGED_STORAGE_ERRORS.clear()
    yield
    # A test may have replaced get_database with a plain function; the real
    # cached resource is restored when its monkeypatch is undone.
    clear = getattr(state.get_database, "clear", None)
    if callable(clear):
        clear()
    state._LOGGED_STORAGE_ERRORS.clear()


def _markdown(at: AppTest) -> str:
    return "\n".join(str(element.value) for element in at.markdown)


def _text(at: AppTest) -> str:
    """Everything a visitor can read, including st.error/st.caption output."""
    parts = [_markdown(at)]
    for collection in (at.error, at.warning, at.caption):
        parts.extend(str(element.value) for element in collection)
    return "\n".join(parts)


def _buttons(at: AppTest) -> list[str]:
    return [str(button.label) for button in at.button]


def test_storage_state_is_safe_and_logs_the_real_error(monkeypatch, caplog):
    state._LOGGED_STORAGE_ERRORS.clear()

    def boom():
        raise DatabaseUnavailable("could not connect to ep-x-pooler")

    monkeypatch.setattr(state, "get_database", boom)

    with caplog.at_level(logging.ERROR, logger="mnz.storage"):
        assert state.storage_state() == "unavailable"
        assert state.storage_is_durable() is False
        # A Streamlit rerun repeats the call; the traceback is logged once.
        assert state.storage_state() == "unavailable"

    records = [r for r in caplog.records if "Account database unavailable" in r.getMessage()]
    assert len(records) == 1
    assert "could not connect to ep-x-pooler" in records[0].getMessage()
    assert records[0].exc_info is not None  # the real traceback, not just the text


@pytest.mark.parametrize("page", ["Login", "Register"])
def test_message_is_shown_before_the_visitor_submits(sqlite_env, monkeypatch, page):
    def boom():
        raise DatabaseUnavailable("host is suspended")

    monkeypatch.setattr(state, "get_database", boom)

    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["public_page"] = page
    at.run()

    assert not at.exception, at.exception
    assert MESSAGE in _text(at)
    assert "Retry" in _buttons(at)

    # The retry button reruns the page and re-attempts the connection.
    next(b for b in at.button if b.label == "Retry").click()
    at.run()
    assert not at.exception, at.exception
    assert MESSAGE in _text(at)


def test_login_shows_a_short_message_and_a_retry(sqlite_env, monkeypatch, caplog):
    monkeypatch.setattr(state, "auth", lambda: BrokenAuth())

    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["public_page"] = "Login"
    at.run()

    at.text_input[0].set_value("someone@example.com")
    at.text_input[1].set_value("password123")
    next(b for b in at.button if b.label == "Sign in").click()
    with caplog.at_level(logging.ERROR, logger="mnz.storage"):
        at.run()

    assert not at.exception, at.exception
    assert MESSAGE in _text(at)
    assert "Retry" in _buttons(at)
    # No raw psycopg/psycopg_pool traceback text leaks onto the page.
    assert "Traceback" not in _text(at)
    assert "DatabaseUnavailable" not in _text(at)
    assert any("Account database unavailable" in r.getMessage() for r in caplog.records)


def test_login_retry_button_reruns_the_form(sqlite_env, monkeypatch):
    calls = {"authenticate": 0}

    class FlakyAuth(BrokenAuth):
        def authenticate(self, *args, **kwargs):
            calls["authenticate"] += 1
            raise DatabaseUnavailable("still waking up")

    monkeypatch.setattr(state, "auth", lambda: FlakyAuth())

    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["public_page"] = "Login"
    at.run()
    at.text_input[0].set_value("someone@example.com")
    at.text_input[1].set_value("password123")
    next(b for b in at.button if b.label == "Sign in").click()
    at.run()
    assert calls["authenticate"] == 1

    next(b for b in at.button if b.label == "Retry").click()
    at.run()
    assert not at.exception, at.exception
    # The retry reaches storage again rather than reusing a broken handle.
    assert calls["authenticate"] == 2


def test_register_shows_a_short_message_and_a_retry(sqlite_env, monkeypatch):
    monkeypatch.setattr(state, "auth", lambda: BrokenAuth())

    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["public_page"] = "Register"
    at.run()

    at.text_input[0].set_value("New Person")
    at.text_input[1].set_value("new@example.com")
    at.text_input[2].set_value("password123")
    at.text_input[3].set_value("password123")
    at.checkbox[0].check()
    next(b for b in at.button if b.label == "Create demo account").click()
    at.run()

    assert not at.exception, at.exception
    assert MESSAGE in _text(at)
    assert "Retry" in _buttons(at)


def test_a_waking_database_does_not_take_the_public_site_down(sqlite_env, monkeypatch):
    """Session restore hits storage before any page renders; it must not crash."""
    monkeypatch.setattr(state, "auth", lambda: BrokenAuth())

    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["session"] = "stale-token"
    at.run()

    assert not at.exception, at.exception
    assert "Read the market" in _markdown(at)
    # The bootstrap flag is cleared so the next run retries the restore.
    assert "_mnz_bootstrapped" not in at.session_state
