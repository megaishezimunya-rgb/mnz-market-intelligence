"""In-app password change: service rules and the Settings form."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
import state  # noqa: E402
from auth import AuthService, hash_password  # noqa: E402
from database.database import Database  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(_ROOT / "app.py")


@pytest.fixture()
def account(db):
    demo = db.create_account("Password Demo", config.DEMO_STARTING_BALANCE)
    user = db.create_user(
        email="change@example.com", name="Change User",
        password_hash=hash_password("password123"), account_id=int(demo["id"]),
    )
    return db, user


def test_change_password_rejects_a_wrong_current_password(account):
    db, user = account
    service = AuthService(db)
    problems = service.change_password(int(user["id"]), "not-my-password",
                                       "newpassword456", "newpassword456")
    assert problems == ["Your current password is incorrect."]
    assert service.authenticate("change@example.com", "password123")[0] is not None


def test_change_password_validates_the_new_password(account):
    db, user = account
    service = AuthService(db)
    problems = service.change_password(int(user["id"]), "password123", "short", "short")
    assert any("at least 8 characters" in problem for problem in problems)

    problems = service.change_password(int(user["id"]), "password123",
                                       "newpassword456", "newpassword789")
    assert any("do not match" in problem for problem in problems)


def test_change_password_updates_the_hash(account):
    db, user = account
    service = AuthService(db)
    assert service.change_password(int(user["id"]), "password123",
                                   "newpassword456", "newpassword456") == []

    assert service.authenticate("change@example.com", "newpassword456")[0] is not None
    assert service.authenticate("change@example.com", "password123")[0] is None


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "password.db")
    state.get_database.clear()
    db = Database(config.DB_PATH)
    demo = db.create_account("Password App", config.DEMO_STARTING_BALANCE)
    user = db.create_user(
        email="settings@example.com", name="Settings User",
        password_hash=hash_password("password123"), account_id=int(demo["id"]),
    )
    yield db, user
    state.get_database.clear()


def _settings(db, user) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["mnz_user"] = user
    at.session_state["_mnz_bootstrapped"] = True
    at.session_state["mnz_page"] = "Settings"
    at.session_state["nav_radio"] = "Settings"
    at.run()
    assert not at.exception, at.exception
    return at


def test_settings_form_changes_the_password(app_env):
    db, user = app_env
    at = _settings(db, user)

    at.text_input(key="password_current").set_value("password123")
    at.text_input(key="password_new").set_value("newpassword456")
    at.text_input(key="password_confirm").set_value("newpassword456")
    next(button for button in at.button if button.label == "Change password").click().run()

    assert not at.exception, at.exception
    assert any("Password changed" in str(s.value) for s in at.success)
    assert AuthService(db).authenticate("settings@example.com", "newpassword456")[0] is not None


def test_settings_form_reports_a_wrong_current_password(app_env):
    db, user = app_env
    at = _settings(db, user)

    at.text_input(key="password_current").set_value("wrong-password")
    at.text_input(key="password_new").set_value("newpassword456")
    at.text_input(key="password_confirm").set_value("newpassword456")
    next(button for button in at.button if button.label == "Change password").click().run()

    assert not at.exception, at.exception
    assert any("current password is incorrect" in str(e.value) for e in at.error)
    assert AuthService(db).authenticate("settings@example.com", "password123")[0] is not None
