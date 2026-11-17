"""Application state for MNZ BOT.

Owns the database handle, the authenticated user, their demo account and their
persisted settings. Pages never touch ``st.session_state`` keys directly for
account data — they call these helpers, so one user can never read another's
records.
"""

from __future__ import annotations

import streamlit as st

import config
from auth import AuthService
from database.database import Database
from simulator.demo_account import DemoAccount

DEFAULT_NOTIFICATIONS = {
    "enabled": True,
    "min_strength": "Moderate",
    "min_quality": config.ALERT_MIN_QUALITY,
    "in_app": True,
}

DEFAULT_DISPLAY = {
    "timeframe": config.DEFAULT_TIMEFRAME,
    "categories": ["forex", "indices", "stocks"],
    "compact": False,
    "allow_sample": False,
}

DEFAULT_SAFETY = {
    "max_slots": config.DEMO_DEFAULT_SLOTS,
    "risk_pct": config.DEMO_RISK_PCT,
}

DEFAULT_PROFILE = {"name": "", "email": "", "experience": "Beginner"}


# --------------------------------------------------------------------------- #
# Database and session
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def get_database() -> Database:
    """One database facade per server process (SQLite or PostgreSQL)."""
    return Database()


def auth() -> AuthService:
    return AuthService(get_database())


def bootstrap() -> None:
    """Restore a session from the URL token, if one is present and valid."""
    if st.session_state.get("_mnz_bootstrapped"):
        return
    st.session_state["_mnz_bootstrapped"] = True
    token = None
    try:
        token = st.query_params.get("session")
    except Exception:  # pragma: no cover - very old Streamlit query API
        token = None
    if token:
        user = auth().user_for_token(token)
        if user:
            _remember(user, token)


def _remember(user: dict, token: str | None) -> None:
    st.session_state["mnz_user"] = user
    st.session_state["mnz_token"] = token
    st.session_state.pop("mnz_account", None)


def current_user() -> dict | None:
    user = st.session_state.get("mnz_user")
    return user if isinstance(user, dict) else None


def sign_in(user: dict, token: str) -> None:
    _remember(user, token)
    try:
        st.query_params["session"] = token
    except Exception:  # pragma: no cover - query params unavailable
        pass


def logout() -> None:
    token = st.session_state.get("mnz_token")
    auth().end_session(token)
    for key in ("mnz_user", "mnz_token", "mnz_account", "mnz_page"):
        st.session_state.pop(key, None)
    try:
        st.query_params.clear()
    except Exception:  # pragma: no cover
        pass


def require_user() -> dict:
    user = current_user()
    if not user:
        raise PermissionError("Authentication required.")
    return user


def refresh_user() -> dict | None:
    user = current_user()
    if not user:
        return None
    fresh = get_database().get_user(int(user["id"]))
    if fresh:
        st.session_state["mnz_user"] = fresh
    return fresh


# --------------------------------------------------------------------------- #
# Demo account
# --------------------------------------------------------------------------- #
def get_account() -> DemoAccount:
    user = require_user()
    cached = st.session_state.get("mnz_account")
    if isinstance(cached, DemoAccount) and cached.id == int(user["account_id"]):
        cached.refresh()
        return cached
    row = get_database().get_account(int(user["account_id"]))
    if row is None:
        raise RuntimeError("The demo account for this user is missing.")
    account = DemoAccount(get_database(), row)
    st.session_state["mnz_account"] = account
    return account


def reload_account() -> DemoAccount:
    st.session_state.pop("mnz_account", None)
    return get_account()


# --------------------------------------------------------------------------- #
# Per-user settings
# --------------------------------------------------------------------------- #
def get_setting(key: str, default=None):
    user = current_user()
    if not user:
        return default
    return get_database().get_user_setting(int(user["id"]), key, default)


def save_setting(key: str, value) -> None:
    user = require_user()
    get_database().set_user_setting(int(user["id"]), key, value)


def profile() -> dict:
    return {**DEFAULT_PROFILE, **(get_setting("profile", {}) or {})}


def notifications() -> dict:
    return {**DEFAULT_NOTIFICATIONS, **(get_setting("notifications", {}) or {})}


def display() -> dict:
    return {**DEFAULT_DISPLAY, **(get_setting("display", {}) or {})}


def safety() -> dict:
    return {**DEFAULT_SAFETY, **(get_setting("safety", {}) or {})}


def save_notifications(updates: dict) -> None:
    save_setting("notifications", {**notifications(), **updates})


def save_display(updates: dict) -> None:
    save_setting("display", {**display(), **updates})


def save_safety(updates: dict) -> None:
    save_setting("safety", {**safety(), **updates})


def save_profile(updates: dict) -> None:
    save_setting("profile", {**profile(), **updates})


def current_timeframe() -> str:
    frame = display().get("timeframe", config.DEFAULT_TIMEFRAME)
    return frame if frame in config.TIMEFRAMES else config.DEFAULT_TIMEFRAME


def allow_sample_data() -> bool:
    return bool(display().get("allow_sample", False))


def max_demo_slots() -> int:
    slots = int(safety().get("max_slots", config.DEMO_DEFAULT_SLOTS))
    return slots if slots in config.DEMO_SLOT_CHOICES else config.DEMO_DEFAULT_SLOTS


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
def current_page() -> str:
    page = st.session_state.get("mnz_page", config.NAV_ITEMS[0])
    return page if page in config.NAV_ITEMS else config.NAV_ITEMS[0]


def goto(page: str) -> None:
    """Queue a navigation change and rerun safely from inside a render."""
    if page in config.NAV_ITEMS:
        st.session_state["mnz_pending_page"] = page
        st.rerun()


def apply_pending_navigation() -> None:
    pending = st.session_state.pop("mnz_pending_page", None)
    if pending in config.NAV_ITEMS:
        st.session_state["mnz_page"] = pending
