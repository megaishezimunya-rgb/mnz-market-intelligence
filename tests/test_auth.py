"""Authentication and per-user isolation tests."""

from __future__ import annotations

import config
from auth import AuthService, hash_password, validate_registration, verify_password
from database.database import Database
from simulator.demo_account import DemoAccount


def _service(tmp_path) -> AuthService:
    return AuthService(Database(tmp_path / "auth.db"))


def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery")
    assert stored.startswith("pbkdf2_sha256$")
    assert "$correct" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong password", stored)
    assert not verify_password("x", "not-a-hash")


def test_registration_creates_demo_account_with_100(tmp_path):
    service = _service(tmp_path)
    user, problems = service.register("Ada", "Ada@Example.com", "password123")
    assert problems == []
    assert user is not None
    assert user["email"] == "ada@example.com"
    account = service.db.get_account(user["account_id"])
    assert account["starting_balance"] == config.DEMO_STARTING_BALANCE
    assert account["cash_balance"] == config.DEMO_STARTING_BALANCE
    assert DemoAccount(service.db, account).equity({}) == config.DEMO_STARTING_BALANCE


def test_registration_validation_and_duplicates(tmp_path):
    service = _service(tmp_path)
    assert service.register("A", "bad", "short")[1]
    user, _ = service.register("Ada", "ada@example.com", "password123")
    assert user is not None
    duplicate, problems = service.register("Other", "ada@example.com", "password123")
    assert duplicate is None
    assert any("already exists" in problem for problem in problems)
    assert validate_registration("Ada", "ada@example.com", "password123",
                                 confirm="different123")


def test_password_is_not_plain_text(tmp_path):
    service = _service(tmp_path)
    user, _ = service.register("Ada", "ada@example.com", "password123")
    assert "password123" not in user["password_hash"]


def test_login_and_session_lifecycle(tmp_path):
    service = _service(tmp_path)
    user, _ = service.register("Ada", "ada@example.com", "password123")

    assert service.authenticate("ada@example.com", "wrong")[0] is None
    found, error = service.authenticate("ADA@example.com", "password123")
    assert error is None and found["id"] == user["id"]

    token = service.start_session(user["id"])
    assert token and token not in str(service.db.path)
    assert service.user_for_token(token)["id"] == user["id"]
    service.end_session(token)
    assert service.user_for_token(token) is None
    assert service.user_for_token("bogus") is None


def test_signals_are_isolated_per_user(tmp_path):
    db = Database(tmp_path / "iso.db")
    service = AuthService(db)
    one, _ = service.register("One", "one@example.com", "password123")
    two, _ = service.register("Two", "two@example.com", "password123")

    db.insert_signal({
        "user_id": one["id"], "symbol": "EURUSD=X", "market": "forex", "label": "BUY",
        "timeframe": "H1", "price": 1.1, "quality": 70, "score": 0.4,
        "explanation": "test", "data_quality": "current",
    })
    assert len(db.list_signals(one["id"])) == 1
    assert db.list_signals(two["id"]) == []

    db.add_alert({"user_id": one["id"], "symbol": "EURUSD=X", "title": "t", "message": "m"})
    assert db.unread_alert_count(one["id"]) == 1
    assert db.unread_alert_count(two["id"]) == 0


def test_journal_is_isolated_per_user(tmp_path):
    db = Database(tmp_path / "journal.db")
    service = AuthService(db)
    one, _ = service.register("One", "one@example.com", "password123")
    two, _ = service.register("Two", "two@example.com", "password123")
    entry = db.add_journal({"user_id": one["id"], "note": "followed the plan"})
    assert db.list_journal(one["id"])[0]["id"] == entry["id"]
    assert db.list_journal(two["id"]) == []
