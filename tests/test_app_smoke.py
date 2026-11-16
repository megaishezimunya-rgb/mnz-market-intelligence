"""Offline AppTest smoke tests: every navigation page must render without exceptions.

No network access is allowed here. All provider entry points are replaced with
deterministic fixtures, and the database lives in a per-test temporary file.
"""

from __future__ import annotations

import zlib

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
import state
from data import market_data
from engines import indices as indices_engine
from engines import stocks as stocks_engine

APP_PATH = config.BASE_DIR / "app.py"

PAGES = [
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

PAGE_HEADINGS = {
    "Overview": "Overview",
    "Forex": "Forex Engine",
    "Crypto": "Crypto Engine",
    "Stocks": "Stocks Engine",
    "Commodities": "Commodities Engine",
    "Indices": "Indices Engine",
    "AI Market Analyst": "AI Market Analyst",
    "Strategy Testing": "Strategy Testing",
    "Demo Trading": "Demo Trading",
    "Trade History": "Trade History",
    "Performance Reports": "Performance Reports",
    "Settings": "Settings",
}


def _fixture_frame(symbol: str, bars: int = 420) -> pd.DataFrame:
    seed = zlib.crc32(symbol.encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    base = 50 + seed % 100
    drift = np.linspace(0.0, base * 0.15, bars)
    wave = np.sin(np.linspace(0, 14, bars)) * base * 0.03
    close = base + drift + wave + rng.normal(0, base * 0.002, bars)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    index = pd.date_range(end=pd.Timestamp.utcnow().normalize(), periods=bars, freq="D")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": 1_000_000.0},
        index=index,
    )


def _fixture_price_data(symbol: str, period: str, interval: str) -> market_data.PriceData:
    return market_data.PriceData(
        symbol=symbol,
        period=period,
        interval=interval,
        frame=_fixture_frame(symbol),
        source="Offline fixture",
        fetched_at=config.utcnow(),
        is_sample=False,
        delayed=True,
    )


def _fixture_fundamentals(symbol: str) -> dict:
    return {
        "available": True,
        "name": f"{symbol} Fixture Corp",
        "sector": "Technology",
        "industry": "Software",
        "exchange": "TEST",
        "currency": "USD",
        "market_cap": 1.2e12,
        "trailing_pe": 24.5,
        "forward_pe": 22.1,
        "profit_margin": 0.24,
        "dividend_yield": 0.006,
        "beta": 1.1,
        "week52_high": 210.0,
        "week52_low": 150.0,
        "avg_volume": 4_000_000,
        "source": "Offline fixture",
    }


def _fixture_earnings(symbol: str) -> dict:
    return {
        "available": True,
        "next_date": "2026-12-01",
        "eps_estimate": 1.5,
        "history": [
            {"date": "2026-09-01", "eps_estimate": 1.4, "reported": 1.52, "surprise_pct": 8.6},
            {"date": "2026-06-01", "eps_estimate": 1.3, "reported": 1.31, "surprise_pct": 0.8},
        ],
    }


@pytest.fixture()
def offline_app(tmp_path, monkeypatch):
    """Isolate storage and replace every provider call with fixtures."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "smoke.db")
    monkeypatch.setattr(market_data, "_fetch_live", _fixture_price_data)
    monkeypatch.setattr(stocks_engine, "fundamentals", _fixture_fundamentals)
    monkeypatch.setattr(stocks_engine, "earnings_info", _fixture_earnings)
    monkeypatch.setattr(
        indices_engine, "compute_breadth",
        lambda symbol, period="1y", interval="1d": {
            "available": False,
            "reason": "Breadth is disabled for the offline test suite.",
        },
    )
    market_data.clear_cache()
    state.get_database.clear()
    yield
    state.get_database.clear()
    market_data.clear_cache()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_offline(offline_app, page):
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception, f"Initial render raised: {at.exception}"
    assert len(at.radio) == 1, "The sidebar navigation radio should be the only radio group."

    at.radio[0].set_value(page).run()
    assert at.session_state["nav"] == page
    assert not at.exception, f"{page} raised: {at.exception}"
    assert at.markdown, f"{page} rendered no content"
    rendered = "\n".join(str(element.value) for element in at.markdown)
    heading = PAGE_HEADINGS[page]
    assert f"<h1>{heading}</h1>" in rendered, f"{page} did not render its heading {heading!r}"


def test_navigation_contains_every_page(offline_app):
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert list(at.radio[0].options) == PAGES
