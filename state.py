"""Application state: database handle, demo account, settings and navigation.

Kept out of the page modules so every screen reads and writes settings through
one code path.  Settings are stored as JSON in SQLite, which is also the shape a
future per-customer account model would use.
"""

from __future__ import annotations

import copy

import streamlit as st

import config
from database.database import Database
from simulator.demo_account import DemoAccount

NAV_ITEMS = [
    "Overview",
    "Forex",
    "Crypto",
    "Stocks",
    "Commodities",
    "Indices",
    "AI Market Analyst",
    "Strategy Testing",
    "Demo Trading",
    "Trade History",
    "Performance Reports",
    "Settings",
]

ENGINE_BY_NAV = {
    "Forex": "forex",
    "Crypto": "crypto",
    "Stocks": "stocks",
    "Commodities": "commodities",
    "Indices": "indices",
}

DEFAULT_DATA_SETTINGS = {
    "allow_sample_data": True,
    "timeframe": config.DEFAULT_TIMEFRAME,
    "cache_ttl": config.DATA_CACHE_TTL_SECONDS,
    "default_cost_bps": config.DEFAULT_SIM_COST_BPS,
    "overview_markets": ["forex", "crypto", "stocks", "commodities", "indices"],
}


@st.cache_resource(show_spinner=False)
def get_database() -> Database:
    """One SQLite handle per server process."""
    return Database()


def init_state() -> None:
    """Prepare session state. Safe to call on every rerun."""
    # Navigation requests are applied before the sidebar widget is created, because
    # Streamlit forbids writing to a widget-backed key after instantiation.
    pending = st.session_state.pop("_mnz_pending_nav", None)
    if pending in NAV_ITEMS:
        st.session_state.nav = pending

    if st.session_state.get("_mnz_initialised"):
        _refresh_account_silently()
        return

    db = get_database()
    account_row = db.get_or_create_account(config.DEMO_ACCOUNT_NAME, config.DEMO_STARTING_BALANCE)
    st.session_state.db = db
    st.session_state.account_id = int(account_row["id"])
    st.session_state.account = DemoAccount(db, account_row)
    st.session_state.engine_settings = load_engine_settings(db)
    st.session_state.data_settings = {**DEFAULT_DATA_SETTINGS, **(db.get_setting("data_settings", {}) or {})}
    st.session_state.nav = NAV_ITEMS[0]
    st.session_state["_mnz_initialised"] = True


def _refresh_account_silently() -> None:
    account = st.session_state.get("account")
    if isinstance(account, DemoAccount):
        account.refresh()


# --------------------------------------------------------------------------- #
# Account
# --------------------------------------------------------------------------- #
def get_account() -> DemoAccount:
    account = st.session_state.get("account")
    if not isinstance(account, DemoAccount):
        db = get_database()
        account = DemoAccount.load(db, st.session_state.get("account_id"))
        st.session_state.account = account
        st.session_state.account_id = account.id
    return account


def reload_account() -> DemoAccount:
    account = DemoAccount.load(get_database(), st.session_state.get("account_id"))
    st.session_state.account = account
    st.session_state.account_id = account.id
    return account


# --------------------------------------------------------------------------- #
# Engine strategy settings
# --------------------------------------------------------------------------- #
def _default_settings_dict() -> dict[str, dict]:
    return {key: value.to_dict() for key, value in config.ENGINE_STRATEGY_DEFAULTS.items()}


def load_engine_settings(db: Database | None = None) -> dict[str, config.StrategySettings]:
    db = db or get_database()
    stored = db.get_setting("engine_settings", {}) or {}
    out: dict[str, config.StrategySettings] = {}
    for key, default in config.ENGINE_STRATEGY_DEFAULTS.items():
        merged = copy.deepcopy(default.to_dict())
        saved = stored.get(key) or {}
        if isinstance(saved, dict):
            merged.update({k: v for k, v in saved.items() if k in merged})
        settings = config.StrategySettings.from_dict(merged)
        if settings.validate():
            settings = copy.deepcopy(default)
        out[key] = settings
    return out


def get_settings(engine_key: str) -> config.StrategySettings:
    settings_map = st.session_state.get("engine_settings")
    if not isinstance(settings_map, dict) or engine_key not in settings_map:
        settings_map = load_engine_settings()
        st.session_state.engine_settings = settings_map
    return settings_map[engine_key]


def save_settings(engine_key: str, settings: config.StrategySettings) -> list[str]:
    problems = settings.validate()
    if problems:
        return problems
    db = get_database()
    stored = db.get_setting("engine_settings", {}) or {}
    stored[engine_key] = settings.to_dict()
    db.set_setting("engine_settings", stored)
    st.session_state.engine_settings = load_engine_settings(db)
    return []


def reset_settings(engine_key: str) -> None:
    db = get_database()
    stored = db.get_setting("engine_settings", {}) or {}
    stored.pop(engine_key, None)
    db.set_setting("engine_settings", stored)
    st.session_state.engine_settings = load_engine_settings(db)


# --------------------------------------------------------------------------- #
# Data preferences
# --------------------------------------------------------------------------- #
def get_data_settings() -> dict:
    settings = st.session_state.get("data_settings")
    if not isinstance(settings, dict):
        settings = {**DEFAULT_DATA_SETTINGS, **(get_database().get_setting("data_settings", {}) or {})}
        st.session_state.data_settings = settings
    return settings


def save_data_settings(updates: dict) -> None:
    settings = {**get_data_settings(), **updates}
    get_database().set_setting("data_settings", settings)
    st.session_state.data_settings = settings


def allow_sample_data() -> bool:
    return bool(get_data_settings().get("allow_sample_data", True))


def current_timeframe() -> str:
    frame = get_data_settings().get("timeframe", config.DEFAULT_TIMEFRAME)
    return frame if frame in config.TIMEFRAMES else config.DEFAULT_TIMEFRAME


def timeframe_period_interval(label: str | None = None) -> tuple[str, str]:
    return config.TIMEFRAMES.get(label or current_timeframe(), config.TIMEFRAMES[config.DEFAULT_TIMEFRAME])


# --------------------------------------------------------------------------- #
# Navigation helpers
# --------------------------------------------------------------------------- #
def goto(page: str) -> None:
    """Queue a navigation change and rerun (safe from inside a page render)."""
    if page in NAV_ITEMS:
        st.session_state["_mnz_pending_nav"] = page
        st.rerun()


def default_symbol(engine_key: str) -> str:
    return config.INSTRUMENTS[engine_key][0].symbol


def instrument_labels(engine_key: str) -> dict[str, str]:
    return {item.symbol: item.label for item in config.INSTRUMENTS[engine_key]}
