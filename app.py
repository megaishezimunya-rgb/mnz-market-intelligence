"""MNZ MARKET INTELLIGENCE — application entry point.

Run with:
    streamlit run app.py

VERSION ONE IS DEMO-ONLY: virtual money, simulated trades, no broker, no live
orders and no credentials of any kind.
"""

from __future__ import annotations

import streamlit as st

import config
import state
import ui
from data import market_data
from pages import (
    analyst_page,
    commodities_page,
    crypto_page,
    demo_trading,
    forex_page,
    indices_page,
    overview,
    reports,
    settings,
    stocks_page,
    strategy_testing,
    trade_history,
)

st.set_page_config(
    page_title=config.APP_NAME,
    page_icon="◼",
    layout="wide",
    initial_sidebar_state="expanded",
)

ui.inject_theme()
state.init_state()

PAGE_RENDERERS = {
    "Overview": overview.render,
    "Forex": forex_page.render,
    "Crypto": crypto_page.render,
    "Stocks": stocks_page.render,
    "Commodities": commodities_page.render,
    "Indices": indices_page.render,
    "AI Market Analyst": analyst_page.render,
    "Strategy Testing": strategy_testing.render,
    "Demo Trading": demo_trading.render,
    "Trade History": trade_history.render,
    "Performance Reports": reports.render,
    "Settings": settings.render,
}


def _sidebar() -> str:
    with st.sidebar:
        ui.brand_logo()
        st.markdown('<div class="mnz-nav-caption">Navigation</div>', unsafe_allow_html=True)
        selection = st.radio(
            "Navigation", state.NAV_ITEMS, key="nav", label_visibility="collapsed",
        )
        provider = market_data.provider_status()
        feed = "Yahoo Finance · delayed" if provider["installed"] else "yfinance not installed"
        st.markdown(
            f'<div class="mnz-sidebar-foot">'
            f"<strong>DEMO MODE</strong><br>Virtual money only. No broker connection, no live orders.<br><br>"
            f"<strong>DATA FEED</strong><br>{feed}<br><br>"
            f"<strong>{config.BRAND}</strong> · v{config.VERSION}<br>"
            f"Educational analysis, not financial advice."
            f"</div>",
            unsafe_allow_html=True,
        )
    return selection


selection = _sidebar()
ui.pop_flash()
PAGE_RENDERERS[selection]()
