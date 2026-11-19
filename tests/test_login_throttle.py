"""The login and register screens honour the failed-attempt backoff."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import auth  # noqa: E402
import config  # noqa: E402
import state  # noqa: E402
from auth import hash_password  # noqa: E402
from database.database import Database  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(_ROOT / "app.py")


@pytest.fixture()
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "throttle.db")
    state.get_database.clear()
    db = Database(config.DB_PATH)
    account = db.create_account("Throttle Demo", config.DEMO_STARTING_BALANCE)
    db.create_user(
        email="blocked@example.com", name="Blocked User",
        password_hash=hash_password("password123"), account_id=int(account["id"]),
    )
    at = AppTest.from_file(APP, default_timeout=60)
    yield at, db
    auth.throttle.reset()
    state.get_database.clear()


def _block(email: str) -> None:
    for _ in range(6):
        auth.throttle.record_failure(email)
    assert auth.throttle.retry_after(email) == 30


def _warnings(at: AppTest) -> str:
    return " ".join(str(widget.value) for widget in at.warning)


def test_login_screen_pauses_after_repeated_failures(site):
    at, _ = site
    at.session_state["public_page"] = "Login"
    at.run()
    _block("blocked@example.com")

    next(w for w in at.text_input if w.label == "Email").set_value("blocked@example.com")
    next(w for w in at.text_input if w.label == "Password").set_value("password123")
    next(b for b in at.button if b.label == "Sign in").click().run()

    assert not at.exception, at.exception
    assert "Too many failed sign-in attempts" in _warnings(at)
    assert "mnz_user" not in at.session_state


def test_register_screen_pauses_after_repeated_failures(site):
    at, db = site
    at.session_state["public_page"] = "Register"
    at.run()
    _block("new@example.com")

    next(w for w in at.text_input if w.label == "Name").set_value("New User")
    next(w for w in at.text_input if w.label == "Email").set_value("new@example.com")
    next(w for w in at.text_input if w.label == "Password").set_value("password123")
    next(w for w in at.text_input if w.label == "Confirm password").set_value("password123")
    at.checkbox[0].set_value(True)
    next(b for b in at.button if b.label == "Create demo account").click().run()

    assert not at.exception, at.exception
    assert "Too many failed attempts" in _warnings(at)
    assert db.get_user_by_email("new@example.com") is None


def test_a_successful_login_clears_the_backoff(site):
    at, _ = site
    at.session_state["public_page"] = "Login"
    at.run()
    for _ in range(3):
        auth.throttle.record_failure("blocked@example.com")

    next(w for w in at.text_input if w.label == "Email").set_value("blocked@example.com")
    next(w for w in at.text_input if w.label == "Password").set_value("password123")
    next(b for b in at.button if b.label == "Sign in").click().run()

    assert not at.exception, at.exception
    assert at.session_state["mnz_user"]["email"] == "blocked@example.com"
    assert auth.throttle.retry_after("blocked@example.com") == 0
