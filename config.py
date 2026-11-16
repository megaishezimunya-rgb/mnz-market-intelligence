"""Central configuration for MNZ MARKET INTELLIGENCE.

Everything brand-, market- and strategy-related is declared here so that the
engines, the analyst, the simulator and the interface all read from one source
of truth.

This build is deliberately DEMO-ONLY.  There is no broker connectivity, no
order routing and no live execution of any kind.  See ``FUTURE_COMMERCIAL`` at
the bottom of this file for the planned (and intentionally unimplemented)
commercial architecture.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Brand
# --------------------------------------------------------------------------- #
APP_NAME = "MNZ MARKET INTELLIGENCE"
BRAND = "MNZ"
TAGLINE = "MARKET INTELLIGENCE"
VERSION = "1.0.0"

def utcnow() -> datetime:
    """Naive UTC 'now' — the project stores naive UTC timestamps throughout."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


DISCLAIMER = (
    "MNZ MARKET INTELLIGENCE is an educational, analytical research tool. "
    "Nothing in this application is financial advice, an investment "
    "recommendation, or a solicitation to trade. Market analysis is generated "
    "from indicators and rules, not from a human adviser. Trading carries risk "
    "of loss. Historical and simulated results never guarantee future "
    "performance."
)

DEMO_BANNER = (
    "DEMO MODE — virtual money only. No broker connection, no live orders, "
    "no real-money execution."
)

# --------------------------------------------------------------------------- #
# Hard safety switches (never enabled in version 1)
# --------------------------------------------------------------------------- #
DEMO_ONLY: bool = True
LIVE_EXECUTION_ENABLED: bool = False  # automated / broker execution is unimplemented
BROKER_INTEGRATION_ENABLED: bool = False
ALLOW_CREDENTIAL_STORAGE: bool = False  # we never ask for brokerage credentials

# --------------------------------------------------------------------------- #
# Palette — black, white and charcoal only
# --------------------------------------------------------------------------- #
COLORS: dict[str, str] = {
    "black": "#0A0A0B",
    "panel": "#121214",
    "panel_alt": "#17171A",
    "charcoal": "#2A2A2E",
    "charcoal_light": "#3A3A40",
    "muted": "#8C8C93",
    "text": "#F4F4F5",
    "white": "#FFFFFF",
    "up": "#FFFFFF",
    "down": "#75757E",
    "grid": "#222226",
    "line_primary": "#FFFFFF",
    "line_secondary": "#A8A8B0",
    "line_tertiary": "#5C5C64",
}

CHART_COLORWAY = [
    COLORS["line_primary"],
    COLORS["line_secondary"],
    COLORS["line_tertiary"],
    COLORS["muted"],
    COLORS["charcoal_light"],
]

# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "mnz_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("MNZ_DB_PATH", DATA_DIR / "mnz.db"))
EXPORT_DIR = DATA_DIR / "exports"

# --------------------------------------------------------------------------- #
# Data provider settings
# --------------------------------------------------------------------------- #
DATA_SOURCE_NAME = "Yahoo Finance via yfinance"
DATA_CACHE_TTL_SECONDS = int(os.environ.get("MNZ_CACHE_TTL", "300"))
MAX_BARS_FOR_ANALYSIS = 1500

# When a provider is unreachable the app can show clearly-labelled offline
# sample data so every screen remains explorable.  It is never presented as
# real market data: a watermark appears on charts, tables and the analyst.
ALLOW_SAMPLE_DATA_FALLBACK = True

TIME_SOURCE_NOTE = (
    "Timestamps shown are the bar timestamps returned by the provider. "
    "Yahoo Finance data may be delayed by 15–20 minutes for some venues and "
    "is not suitable for execution decisions."
)

# --------------------------------------------------------------------------- #
# Domain models
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Instrument:
    """A tradable or analysable instrument."""

    symbol: str
    label: str
    market: str
    notes: str = ""


@dataclass
class StrategySettings:
    """Per-engine strategy configuration (backtests and simulator entries)."""

    fast_ma: int = 50
    slow_ma: int = 200
    rsi_period: int = 14
    rsi_buy_max: float = 65.0
    rsi_sell_min: float = 75.0
    use_rsi_filter: bool = True
    allow_short: bool = False
    cost_bps: float = 8.0
    position_size_pct: float = 100.0
    max_hold_bars: int = 0  # 0 = no time stop

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "StrategySettings":
        payload = payload or {}
        known = {f: payload[f] for f in cls.__dataclass_fields__ if f in payload}
        return cls(**known)

    def validate(self) -> list[str]:
        """Return a list of human-readable problems (empty when valid)."""
        problems: list[str] = []
        if self.fast_ma < 2:
            problems.append("Fast moving average must be at least 2 bars.")
        if self.slow_ma <= self.fast_ma:
            problems.append("Slow moving average must be longer than the fast one.")
        if not 2 <= self.rsi_period <= 100:
            problems.append("RSI period must be between 2 and 100.")
        if not 0 <= self.cost_bps <= 500:
            problems.append("Transaction cost must be between 0 and 500 basis points.")
        if not 1 <= self.position_size_pct <= 100:
            problems.append("Position size must be between 1% and 100% of equity.")
        if self.max_hold_bars < 0:
            problems.append("Time stop cannot be negative.")
        return problems


# --------------------------------------------------------------------------- #
# Market universes
# --------------------------------------------------------------------------- #
INSTRUMENTS: dict[str, list[Instrument]] = {
    "forex": [
        Instrument("EURUSD=X", "EUR / USD", "forex", "Majors — most liquid pair"),
        Instrument("GBPUSD=X", "GBP / USD", "forex", "Majors — London session driver"),
        Instrument("USDJPY=X", "USD / JPY", "forex", "Majors — carry-sensitive"),
        Instrument("AUDUSD=X", "AUD / USD", "forex", "Majors — commodity currency"),
        Instrument("USDCAD=X", "USD / CAD", "forex", "Majors — oil sensitive"),
        Instrument("USDCHF=X", "USD / CHF", "forex", "Majors — defensive flows"),
        Instrument("NZDUSD=X", "NZD / USD", "forex", "Majors — risk-sensitive"),
        Instrument("EURGBP=X", "EUR / GBP", "forex", "Cross — European focus"),
        Instrument("EURJPY=X", "EUR / JPY", "forex", "Cross — higher volatility"),
        Instrument("GBPJPY=X", "GBP / JPY", "forex", "Cross — wide ranges"),
    ],
    "crypto": [
        Instrument("BTC-USD", "Bitcoin", "crypto", "24/7 market, deep liquidity"),
        Instrument("ETH-USD", "Ethereum", "crypto", "24/7 market, smart-contract leader"),
        Instrument("SOL-USD", "Solana", "crypto", "24/7 market, higher beta"),
        Instrument("XRP-USD", "XRP", "crypto", "24/7 market, headline sensitive"),
        Instrument("ADA-USD", "Cardano", "crypto", "24/7 market"),
        Instrument("AVAX-USD", "Avalanche", "crypto", "24/7 market"),
        Instrument("LINK-USD", "Chainlink", "crypto", "24/7 market"),
        Instrument("DOGE-USD", "Dogecoin", "crypto", "24/7 market, sentiment driven"),
    ],
    "stocks": [
        Instrument("AAPL", "Apple Inc.", "stocks", "Technology"),
        Instrument("MSFT", "Microsoft Corp.", "stocks", "Technology"),
        Instrument("NVDA", "NVIDIA Corp.", "stocks", "Semiconductors"),
        Instrument("AMZN", "Amazon.com Inc.", "stocks", "Consumer discretionary"),
        Instrument("GOOGL", "Alphabet Inc.", "stocks", "Communication services"),
        Instrument("META", "Meta Platforms Inc.", "stocks", "Communication services"),
        Instrument("TSLA", "Tesla Inc.", "stocks", "Automotive / energy"),
        Instrument("JPM", "JPMorgan Chase & Co.", "stocks", "Financials"),
        Instrument("XOM", "Exxon Mobil Corp.", "stocks", "Energy"),
        Instrument("JNJ", "Johnson & Johnson", "stocks", "Healthcare"),
        Instrument("V", "Visa Inc.", "stocks", "Financials"),
        Instrument("UNH", "UnitedHealth Group", "stocks", "Healthcare"),
    ],
    "commodities": [
        Instrument("GC=F", "Gold futures", "commodities", "Precious metal, USD sensitive"),
        Instrument("SI=F", "Silver futures", "commodities", "Precious metal, industrial demand"),
        Instrument("CL=F", "Crude oil — WTI", "commodities", "Energy benchmark"),
        Instrument("BZ=F", "Crude oil — Brent", "commodities", "Energy benchmark"),
        Instrument("HG=F", "Copper futures", "commodities", "Industrial / growth proxy"),
        Instrument("NG=F", "Natural gas", "commodities", "Weather and storage driven"),
        Instrument("ZC=F", "Corn futures", "commodities", "Agricultural, seasonal"),
        Instrument("ZW=F", "Wheat futures", "commodities", "Agricultural, weather driven"),
    ],
    "indices": [
        Instrument("^GSPC", "S&P 500", "indices", "United States — large cap"),
        Instrument("^NDX", "Nasdaq 100", "indices", "United States — growth / tech"),
        Instrument("^DJI", "Dow Jones Industrial Average", "indices", "United States — industrials"),
        Instrument("^FTSE", "FTSE 100", "indices", "United Kingdom"),
        Instrument("^GDAXI", "DAX", "indices", "Germany"),
        Instrument("^STOXX50E", "Euro Stoxx 50", "indices", "Euro area"),
        Instrument("^N225", "Nikkei 225", "indices", "Japan"),
        Instrument("^HSI", "Hang Seng", "indices", "Hong Kong"),
        Instrument("^AXJO", "ASX 200", "indices", "Australia"),
        Instrument("^BSESN", "BSE Sensex", "indices", "India"),
    ],
}

ENGINE_LABELS = {
    "forex": "Forex",
    "crypto": "Crypto",
    "stocks": "Stocks",
    "commodities": "Commodities",
    "indices": "Indices",
}

# Representative baskets used to approximate market breadth where a true
# constituent feed is not available.  Breadth is computed live from these
# instruments and labelled as a proxy in the interface.
BREADTH_BASKETS: dict[str, list[str]] = {
    "^GSPC": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "JNJ", "V"],
    "^NDX": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "PEP", "COST"],
    "^DJI": ["AAPL", "MSFT", "JPM", "V", "UNH", "HD", "MCD", "CAT", "IBM", "GS"],
    "^FTSE": ["SHEL.L", "AZN.L", "HSBA.L", "ULVR.L", "BP.L", "GSK.L", "RIO.L", "BATS.L"],
}

# --------------------------------------------------------------------------- #
# Timeframes — label -> (yfinance period, interval, approx bar minutes)
# --------------------------------------------------------------------------- #
TIMEFRAMES: dict[str, tuple[str, str]] = {
    "1 month · 5 minute": ("1mo", "5m"),
    "3 months · hourly": ("3mo", "1h"),
    "6 months · daily": ("6mo", "1d"),
    "1 year · daily": ("1y", "1d"),
    "2 years · daily": ("2y", "1d"),
    "5 years · daily": ("5y", "1d"),
    "10 years · weekly": ("10y", "1wk"),
    "Maximum · weekly": ("max", "1wk"),
}

DEFAULT_TIMEFRAME = "1 year · daily"

# --------------------------------------------------------------------------- #
# Per-engine strategy configuration
# --------------------------------------------------------------------------- #
ENGINE_STRATEGY_DEFAULTS: dict[str, StrategySettings] = {
    # Forex trends are slower and ranges are tighter: wider stops, longer MAs,
    # lower per-trade costs, and no short-selling by default.
    "forex": StrategySettings(
        fast_ma=50, slow_ma=200, rsi_period=14, rsi_buy_max=62.0, rsi_sell_min=72.0,
        use_rsi_filter=True, allow_short=False, cost_bps=2.0,
        position_size_pct=50.0, max_hold_bars=0,
    ),
    # Crypto trends are fast and volatile: shorter MAs, higher cost allowance.
    "crypto": StrategySettings(
        fast_ma=21, slow_ma=100, rsi_period=14, rsi_buy_max=70.0, rsi_sell_min=80.0,
        use_rsi_filter=False, allow_short=False, cost_bps=15.0,
        position_size_pct=50.0, max_hold_bars=0,
    ),
    # Stocks: medium-term trend following with a momentum filter.
    "stocks": StrategySettings(
        fast_ma=50, slow_ma=200, rsi_period=14, rsi_buy_max=70.0, rsi_sell_min=78.0,
        use_rsi_filter=True, allow_short=False, cost_bps=5.0,
        position_size_pct=100.0, max_hold_bars=0,
    ),
    # Commodities trend for long stretches then mean-revert sharply.
    "commodities": StrategySettings(
        fast_ma=40, slow_ma=150, rsi_period=14, rsi_buy_max=68.0, rsi_sell_min=76.0,
        use_rsi_filter=True, allow_short=True, cost_bps=6.0,
        position_size_pct=60.0, max_hold_bars=0,
    ),
    # Indices: broad, slower trends; index products cost less to simulate.
    "indices": StrategySettings(
        fast_ma=50, slow_ma=200, rsi_period=14, rsi_buy_max=72.0, rsi_sell_min=80.0,
        use_rsi_filter=True, allow_short=False, cost_bps=3.0,
        position_size_pct=100.0, max_hold_bars=0,
    ),
}

# Each engine weights its analytical components differently — one model does
# not fit every market.
ANALYST_WEIGHTS: dict[str, dict[str, float]] = {
    "forex": {"trend": 0.38, "momentum": 0.22, "rsi": 0.15, "volatility": 0.10, "volume": 0.05, "session": 0.10},
    "crypto": {"trend": 0.30, "momentum": 0.25, "rsi": 0.10, "volatility": 0.15, "volume": 0.20},
    "stocks": {"trend": 0.35, "momentum": 0.25, "rsi": 0.15, "volatility": 0.10, "volume": 0.15},
    "commodities": {"trend": 0.35, "momentum": 0.20, "rsi": 0.15, "volatility": 0.15, "volume": 0.10, "session": 0.05},
    "indices": {"trend": 0.40, "momentum": 0.25, "rsi": 0.10, "volatility": 0.15, "volume": 0.10},
}

BUY_THRESHOLD = 0.25
SELL_THRESHOLD = -0.25
MIN_BARS_FOR_ANALYSIS = 210
STALE_BAR_MINUTES = {"5m": 30, "15m": 60, "30m": 90, "1h": 240, "1d": 4320, "1wk": 20160}

# --------------------------------------------------------------------------- #
# Demo trading simulator
# --------------------------------------------------------------------------- #
DEMO_STARTING_BALANCE = 10_000.00
DEMO_ACCOUNT_NAME = "MNZ Demo Account"
DEFAULT_SIM_COST_BPS = 8.0
MAX_SIM_QUANTITY = 1_000_000.0
EQUITY_HISTORY_LIMIT = 5_000

# --------------------------------------------------------------------------- #
# Commercial architecture (planned, not implemented)
# --------------------------------------------------------------------------- #
FUTURE_COMMERCIAL: dict[str, str] = {
    "Customer accounts": "Per-user records isolated by account id; database layer already keys trades by account.",
    "Subscription plans": "Plan catalogue and entitlement flags are intentionally absent until billing exists.",
    "Customer dashboards": "The demo dashboard is already account-scoped and can be reused per customer.",
    "Secure authentication": "Not implemented in version 1. No credentials are collected or stored.",
    "Separate user settings": "Settings are namespaced by key and account, ready for per-user scoping.",
    "Product licensing": "No licence enforcement is implemented in this build.",
    "Automated execution": "DISABLED and unimplemented — LIVE_EXECUTION_ENABLED is hard-coded False.",
}

LIVE_EXECUTION_NOTICE = (
    "Automated execution is disabled in this version. MNZ never asks for "
    "brokerage passwords or account credentials, and contains no order-routing code."
)

__all__ = [
    "APP_NAME", "BRAND", "TAGLINE", "VERSION", "COLORS", "CHART_COLORWAY",
    "Instrument", "StrategySettings", "INSTRUMENTS", "ENGINE_LABELS",
    "BREADTH_BASKETS", "TIMEFRAMES", "DEFAULT_TIMEFRAME",
    "ENGINE_STRATEGY_DEFAULTS", "ANALYST_WEIGHTS", "BUY_THRESHOLD",
    "SELL_THRESHOLD", "MIN_BARS_FOR_ANALYSIS", "DEMO_STARTING_BALANCE",
    "DEFAULT_SIM_COST_BPS", "DISCLAIMER", "DEMO_BANNER", "FUTURE_COMMERCIAL",
    "DB_PATH", "DATA_DIR", "EXPORT_DIR", "ALLOW_SAMPLE_DATA_FALLBACK",
    "DATA_CACHE_TTL_SECONDS", "STALE_BAR_MINUTES", "TIME_SOURCE_NOTE",
    "LIVE_EXECUTION_ENABLED", "LIVE_EXECUTION_NOTICE",
]
