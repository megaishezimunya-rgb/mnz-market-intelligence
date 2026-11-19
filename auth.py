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
import math
import re
import secrets
import threading
import time
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


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalise_email(email)))


# --------------------------------------------------------------------------- #
# Failed-attempt throttling
# --------------------------------------------------------------------------- #
def live_database() -> Database | None:
    """The app's shared database, resolved late to avoid a circular import."""
    try:
        import state

        return state.get_database()
    except Exception:  # noqa: BLE001 - memory fallback is the documented behaviour
        return None


class AttemptThrottle:
    """Exponential backoff after repeated failed sign-in or registration attempts.

    Counts are keyed by the normalised email address and written to the
    ``login_attempts`` table, so a redeploy or a second worker shares the same
    backoff instead of handing an attacker a fresh set of free attempts. When
    the database is unreachable the counter falls back to process memory for
    that attempt; the stored rows remain the source of truth.
    """

    free_attempts = 5
    base_delay = 30.0
    max_delay = 900.0
    decay = 900.0

    def __init__(self, clock=time.time, store: Database | None = None) -> None:
        self._clock = clock
        self._store = store
        self._memory: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(email: str) -> str:
        return normalise_email(email) or "unknown"

    def _database(self) -> Database | None:
        store = self._store
        if store is None:
            return None
        try:
            return store() if callable(store) else store  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - unreadable storage is not a login failure
            return None

    def _load(self, key: str) -> tuple[int, float]:
        database = self._database()
        if database is not None:
            try:
                row = database.get_login_attempt(key)
            except Exception:  # noqa: BLE001 - fall back to memory for this call
                row = None
            else:
                if row is None:
                    return 0, 0.0
                return int(row.get("failures") or 0), float(row.get("last_failure") or 0.0)
        with self._lock:
            return self._memory.get(key, (0, 0.0))

    def _save(self, key: str, failures: int, moment: float) -> None:
        with self._lock:
            self._memory[key] = (failures, moment)
        database = self._database()
        if database is None:
            return
        try:
            database.save_login_attempt(key, failures=failures, last_failure=moment)
        except Exception:  # noqa: BLE001 - the in-memory count still applies
            pass

    def _delay(self, failures: int) -> float:
        if failures <= self.free_attempts:
            return 0.0
        return min(self.base_delay * 2 ** (failures - self.free_attempts - 1), self.max_delay)

    def retry_after(self, email: str) -> int:
        """Seconds the caller must wait, or 0 when the attempt may proceed."""
        failures, last = self._load(self._key(email))
        if failures <= self.free_attempts:
            return 0
        remaining = self._delay(failures) - (self._clock() - last)
        return int(math.ceil(remaining)) if remaining > 0 else 0

    def record_failure(self, email: str) -> int:
        """Count one failure and return the new wait time in seconds."""
        key = self._key(email)
        now = self._clock()
        failures, last = self._load(key)
        if failures and now - last > self.decay:
            failures = 0
        failures += 1
        self._save(key, failures, now)
        delay = self._delay(failures)
        return int(math.ceil(delay)) if delay > 0 else 0

    def clear(self, email: str) -> None:
        key = self._key(email)
        with self._lock:
            self._memory.pop(key, None)
        database = self._database()
        if database is None:
            return
        try:
            database.clear_login_attempt(key)
        except Exception:  # noqa: BLE001 - a stale count expires on its own
            pass

    def reset(self) -> None:
        with self._lock:
            self._memory.clear()
        database = self._database()
        if database is None:
            return
        try:
            database.clear_login_attempts()
        except Exception:  # noqa: BLE001 - nothing to reset when storage is down
            pass


throttle = AttemptThrottle(store=live_database)


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

    def change_password(self, user_id: int, current: str, new: str,
                        confirm: str | None = None) -> list[str]:
        """Replace a password after verifying the existing one.

        Returns the list of problems, empty when the change was applied. The
        session token is left alone: the person making the change is the one
        already signed in.
        """
        user = self.db.get_user(int(user_id))
        problems: list[str] = []
        if user is None:
            return ["This account no longer exists."]
        if not verify_password(current or "", user["password_hash"]):
            problems.append("Your current password is incorrect.")
        if len(new or "") < 8:
            problems.append("New password must be at least 8 characters.")
        if confirm is not None and new != confirm:
            problems.append("The two new passwords do not match.")
        if problems:
            return problems
        self.db.update_user(int(user_id), password_hash=hash_password(new))
        return []

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
