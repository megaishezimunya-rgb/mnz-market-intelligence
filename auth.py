"""Authentication for MNZ BOT.

Local email/password accounts with PBKDF2-HMAC-SHA256 hashing and opaque
session tokens stored (hashed) in SQLite. No third-party identity provider and
no brokerage credentials are involved.

Sessions survive a browser refresh because the raw token is kept in the URL
query string and exchanged for the user record on every run.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

import config
from database.database import Database

PBKDF2_ITERATIONS = 210_000
SESSION_DAYS = 30
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, salt: bytes | None = None,
                  iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_registration(name: str, email: str, password: str,
                         confirm: str | None = None) -> list[str]:
    problems: list[str] = []
    if len((name or "").strip()) < 2:
        problems.append("Enter your name (at least two characters).")
    if not _EMAIL_RE.match(normalise_email(email)):
        problems.append("Enter a valid email address.")
    if len(password or "") < 8:
        problems.append("Password must be at least 8 characters.")
    if confirm is not None and password != confirm:
        problems.append("The two passwords do not match.")
    return problems


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
class AuthService:
    """Registration, login and session handling backed by SQLite."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def register(self, name: str, email: str, password: str) -> tuple[dict | None, list[str]]:
        name = (name or "").strip()
        email = normalise_email(email)
        problems = validate_registration(name, email, password)
        if problems:
            return None, problems
        if self.db.get_user_by_email(email):
            return None, ["An account with that email already exists. Sign in instead."]

        account = self.db.create_account(f"MNZ Demo — {email}", config.DEMO_STARTING_BALANCE)
        user = self.db.create_user(email=email, name=name,
                                   password_hash=hash_password(password),
                                   account_id=int(account["id"]))
        self.db.set_user_setting(user["id"], "profile", {
            "name": name,
            "email": email,
            "experience": "Beginner",
            "joined": config.utcnow().isoformat(timespec="seconds"),
        })
        self.db.set_user_setting(user["id"], "notifications", {
            "enabled": True,
            "min_strength": "Moderate",
            "min_quality": config.ALERT_MIN_QUALITY,
            "in_app": True,
        })
        self.db.set_user_setting(user["id"], "display", {
            "timeframe": config.DEFAULT_TIMEFRAME,
            "categories": ["forex", "indices", "stocks"],
            "compact": False,
            "allow_sample": False,
        })
        return user, []

    def authenticate(self, email: str, password: str) -> tuple[dict | None, str | None]:
        user = self.db.get_user_by_email(normalise_email(email))
        if not user or not verify_password(password or "", user["password_hash"]):
            return None, "Email or password is incorrect."
        return user, None

    def start_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        expiry = (config.utcnow() + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
        self.db.create_session(_token_hash(token), user_id, expiry)
        self.db.purge_expired_sessions()
        return token

    def user_for_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        return self.db.get_session_user(_token_hash(token))

    def end_session(self, token: str | None) -> None:
        if token:
            self.db.delete_session(_token_hash(token))
