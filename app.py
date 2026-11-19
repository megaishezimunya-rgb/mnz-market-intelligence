"""MNZ BOT — application entry point.

Run with:
    streamlit run app.py

Signed-out visitors see the public website (website.py). Signed-in users get the
six-section application: Home, Markets, Signals, Demo, MNZ AI, Settings.

DEMO-ONLY: virtual money, simulated positions, no broker and no live orders.
"""

from __future__ import annotations

from html import escape

import streamlit as st

import config
import state
import ui
from pages import ai_page, demo_page, home, markets, settings_page, signals_page
from website import render as render_website

st.set_page_config(
    page_title=config.APP_NAME,
    page_icon="◼",
    layout="wide",
    initial_sidebar_state="expanded",
)

ui.inject_theme()
state.bootstrap()

# --------------------------------------------------------------------------- #
# Public website (signed out)
# --------------------------------------------------------------------------- #
if state.current_user() is None:
    render_website()
    st.stop()

state.apply_pending_navigation()

PAGE_RENDERERS = {
    "Home": home.render,
    "Markets": markets.render,
    "Signals": signals_page.render,
    "Demo": demo_page.render,
    "MNZ AI": ai_page.render,
    "Settings": settings_page.render,
}

MOBILE_LABELS = {
    "Home": "Home",
    "Markets": "Markets",
    "Signals": "Signals",
    "Demo": "Demo",
    "MNZ AI": "AI",
    "Settings": "Settings",
}


# --------------------------------------------------------------------------- #
# Desktop sidebar
# --------------------------------------------------------------------------- #
def _select_page() -> None:
    """Copy a sidebar choice into the page state before the rerun renders."""
    choice = st.session_state.get("nav_radio")
    if choice in config.NAV_ITEMS:
        st.session_state["mnz_page"] = choice


def render_sidebar() -> str:
    current = state.current_page()
    # Keep the radio in sync only when a button or shortcut changed the page.
    # The widget's own value is the user's click, so it must never be overwritten
    # with the stale page here.
    if st.session_state.get("nav_radio") != current:
        st.session_state["nav_radio"] = current

    with st.sidebar:
        ui.brand_logo()
        st.markdown('<div class="mnz-nav-caption">Workspace</div>', unsafe_allow_html=True)
        selection = st.radio(
            "Navigation", config.NAV_ITEMS, key="nav_radio",
            label_visibility="collapsed", on_change=_select_page,
        )

        user = state.current_user() or {}
        account = state.get_account()
        unread = state.get_database().unread_alert_count(int(user["id"]))
        st.markdown(
            f'<div class="mnz-sidebar-foot">'
            f"<strong>{escape(str(user.get('name', '')))}</strong><br>"
            f"{escape(str(user.get('email', '')))}<br><br>"
            f"<strong>DEMO</strong><br>Virtual cash {ui.money(account.cash)}<br>"
            f"{unread} unread alert(s)<br><br>"
            f"<strong>DATA</strong><br>{config.DATA_SOURCE_NAME}<br><br>"
            f"{config.BRAND} · v{config.VERSION}<br>"
            "Educational analysis, not financial advice."
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("Sign out", key="sidebar_signout", type="secondary"):
            state.logout()
            st.rerun()
    return selection


# --------------------------------------------------------------------------- #
# Mobile bottom navigation (hidden on desktop by CSS)
# --------------------------------------------------------------------------- #
def render_mobile_nav(current: str) -> None:
    with st.container(key="mobile_nav"):
        row = st.container(horizontal=True, horizontal_alignment="distribute", gap="small")
        for item in config.NAV_ITEMS:
            active = item == current
            if row.button(
                MOBILE_LABELS[item], key=f"mnav_{item}",
                type="primary" if active else "secondary",
                width="stretch",
            ):
                st.session_state["mnz_page"] = item
                st.rerun()


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
page = render_sidebar()
render_mobile_nav(page)
ui.pop_flash()
if state.storage_state() == "sqlite":
    ui.temporary_storage_notice()
PAGE_RENDERERS[page]()
