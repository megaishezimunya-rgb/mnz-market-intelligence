"""Central configuration for MNZ BOT.

Brand, palette, navigation, market universes, timeframe mapping, scanner
thresholds and demo-trading defaults live here so every module reads one source
of truth.

MNZ BOT is DEMO-ONLY. There is no broker connectivity, no order routing and no
live execution. Market data comes from Yahoo Finance (delayed) and is always
labelled with its source and timestamp.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Brand
# --------------------------------------------------------------------------- #
APP_NAME = "MNZ BOT"
BRAND = "MNZ BOT"
TAGLINE = "Market Intelligence"
VERSION = "2.0.0"

PALETTE = {
    "bg": "#090B0F",
    "card": "#151922",
    "card_alt": "#1B202B",
    "border": "#232A38",
    "muted": "#8C93A3",
    "text": "#FFFFFF",
    "green": "#20D68A",
    "red": "#F04452",
}

# Backwards-compatible colour map used by the charts.
COLORS: dict[str, str] = {
    "black": PALETTE["bg"],
    "panel": PALETTE["card"],
    "panel_alt": PALETTE["card_alt"],
    "charcoal": "#2A3140",
    "charcoal_light": "#3B4456",
    "muted": PALETTE["muted"],
    "text": PALETTE["text"],
    "white": "#FFFFFF",
    "up": PALETTE["green"],
    "down": PALETTE["red"],
    "grid": "#1D2432",
    "line_primary": PALETTE["green"],
    "line_secondary": "#7C8AA5",
    "line_tertiary": "#4B5568",
}

CHART_COLORWAY = ["#20D68A", "#FFFFFF", "#7C8AA5", "#F04452", "#4B5568"]

DISCLAIMER = (
    "MNZ BOT is an educational market-analysis and simulation platform. "
    "Nothing here is financial advice, an investment recommendation or a "
    "solicitation to trade. Signals are rule-based readings of delayed data, "
    "not predictions. Trading carries a risk of loss; simulated results never "
    "guarantee future performance."
)

DEMO_BANNER = (
    "DEMO MODE — every balance, position and result in the Demo section is "
    "simulated with virtual money. No broker is connected."
)

# --------------------------------------------------------------------------- #
# Safety switches (never enabled)
# --------------------------------------------------------------------------- #
DEMO_ONLY: bool = True
LIVE_EXECUTION_ENABLED: bool = False
BROKER_INTEGRATION_ENABLED: bool = False
ALLOW_CREDENTIAL_STORAGE: bool = False


def utcnow() -> datetime:
    """Naive UTC 'now' — the project stores naive UTC timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# Main navigation — exactly six sections
# --------------------------------------------------------------------------- #
NAV_ITEMS = ["Home", "Markets", "Signals", "Demo", "MNZ AI", "Settings"]

PUBLIC_PAGES = [
    "Home",
    "Features",
    "Platform Compatibility",
    "How It Works",
    "Pricing",
    "Academy",
    "Support",
    "Login",
    "Register",
]

# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "mnz_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("MNZ_DB_PATH", DATA_DIR / "mnz.db"))
# Optional durable storage. Root-level Streamlit secrets are exported to the
# environment, so adding DATABASE_URL under Settings -> Secrets is enough.
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
EXPORT_DIR = DATA_DIR / "exports"

# --------------------------------------------------------------------------- #
# Data provider
# --------------------------------------------------------------------------- #
DATA_SOURCE_NAME = "Yahoo Finance via yfinance"
DATA_CACHE_TTL_SECONDS = int(os.environ.get("MNZ_CACHE_TTL", "300"))
MAX_BARS_FOR_ANALYSIS = 2000
ALLOW_SAMPLE_DATA_FALLBACK = True

TIME_SOURCE_NOTE = (
    "Timestamps are the bar timestamps returned by the provider (UTC). "
    "Yahoo Finance data is delayed, and intraday intervals have limited "
    "history. This feed is not suitable for execution decisions."
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
    """Per-market strategy configuration (backtests and simulated entries)."""

    fast_ma: int = 50
    slow_ma: int = 200
    rsi_period: int = 14
    rsi_buy_max: float = 65.0
    rsi_sell_min: float = 75.0
    use_rsi_filter: bool = True
    allow_short: bool = False
    cost_bps: float = 8.0
    position_size_pct: float = 100.0
    max_hold_bars: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "StrategySettings":
        payload = payload or {}
        known = {f: payload[f] for f in cls.__dataclass_fields__ if f in payload}
        return cls(**known)

    def validate(self) -> list[str]:
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
@dataclass(frozen=True)
class MarketCategory:
    """A scanner category and whether the connected feed can serve it."""

    key: str
    name: str
    source: str
    available: bool
    instruments: tuple[Instrument, ...]
    note: str = ""


FOREX = [
    Instrument("EURUSD=X", "EUR / USD", "forex", "Majors — most liquid pair"),
    Instrument("GBPUSD=X", "GBP / USD", "forex", "Majors — London session"),
    Instrument("USDJPY=X", "USD / JPY", "forex", "Majors — carry sensitive"),
    Instrument("AUDUSD=X", "AUD / USD", "forex", "Majors — commodity currency"),
    Instrument("USDCAD=X", "USD / CAD", "forex", "Majors — oil sensitive"),
    Instrument("USDCHF=X", "USD / CHF", "forex", "Majors — defensive flows"),
    Instrument("NZDUSD=X", "NZD / USD", "forex", "Majors — risk sensitive"),
    Instrument("EURGBP=X", "EUR / GBP", "forex", "Cross — European focus"),
    Instrument("EURJPY=X", "EUR / JPY", "forex", "Cross — higher volatility"),
    Instrument("GBPJPY=X", "GBP / JPY", "forex", "Cross — wide ranges"),
]

INDICES = [
    Instrument("^DJI", "US30 — Dow Jones 30", "indices", "United States — 30 large caps"),
    Instrument("^GSPC", "S&P 500", "indices", "United States — large cap"),
    Instrument("^NDX", "Nasdaq 100", "indices", "United States — growth / tech"),
    Instrument("^FTSE", "FTSE 100", "indices", "United Kingdom"),
    Instrument("^GDAXI", "DAX 40", "indices", "Germany"),
    Instrument("^STOXX50E", "Euro Stoxx 50", "indices", "Euro area"),
    Instrument("^N225", "Nikkei 225", "indices", "Japan"),
    Instrument("^HSI", "Hang Seng", "indices", "Hong Kong"),
    Instrument("^AXJO", "ASX 200", "indices", "Australia"),
    Instrument("^BSESN", "BSE Sensex", "indices", "India"),
]

STOCKS = [
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
]

COMMODITIES = [
    Instrument("GC=F", "Gold futures", "commodities", "Precious metal"),
    Instrument("SI=F", "Silver futures", "commodities", "Precious metal"),
    Instrument("CL=F", "Crude oil — WTI", "commodities", "Energy benchmark"),
    Instrument("BZ=F", "Crude oil — Brent", "commodities", "Energy benchmark"),
    Instrument("HG=F", "Copper futures", "commodities", "Industrial proxy"),
    Instrument("NG=F", "Natural gas", "commodities", "Weather driven"),
    Instrument("ZC=F", "Corn futures", "commodities", "Agricultural"),
    Instrument("ZW=F", "Wheat futures", "commodities", "Agricultural"),
]

CRYPTO = [
    Instrument("BTC-USD", "Bitcoin", "crypto", "24/7 market"),
    Instrument("ETH-USD", "Ethereum", "crypto", "24/7 market"),
    Instrument("SOL-USD", "Solana", "crypto", "24/7 market, higher beta"),
    Instrument("XRP-USD", "XRP", "crypto", "24/7 market"),
    Instrument("ADA-USD", "Cardano", "crypto", "24/7 market"),
    Instrument("AVAX-USD", "Avalanche", "crypto", "24/7 market"),
    Instrument("LINK-USD", "Chainlink", "crypto", "24/7 market"),
    Instrument("DOGE-USD", "Dogecoin", "crypto", "24/7 market"),
]

# Synthetic indices are a Deriv product. The connected Yahoo Finance feed does
# not serve them, so they are listed as awaiting a data connection rather than
# filled with invented prices.
SYNTHETICS = [
    Instrument("V10", "Volatility 10 Index", "synthetics", "Deriv synthetic"),
    Instrument("V25", "Volatility 25 Index", "synthetics", "Deriv synthetic"),
    Instrument("V75", "Volatility 75 Index", "synthetics", "Deriv synthetic"),
    Instrument("V100", "Volatility 100 Index", "synthetics", "Deriv synthetic"),
    Instrument("BOOM500", "Boom 500 Index", "synthetics", "Deriv synthetic"),
    Instrument("CRASH500", "Crash 500 Index", "synthetics", "Deriv synthetic"),
    Instrument("STEP", "Step Index", "synthetics", "Deriv synthetic"),
    Instrument("R_100", "Range Break 100", "synthetics", "Deriv synthetic"),
]

MARKETS: dict[str, MarketCategory] = {
    "forex": MarketCategory(
        "forex", "Forex", "Yahoo Finance", True, tuple(FOREX),
        "Ten major and cross pairs. FX is closed at weekends.",
    ),
    "indices": MarketCategory(
        "indices", "Global Indices", "Yahoo Finance", True, tuple(INDICES),
        "Cash index quotes, including US30. Index CFDs may differ from cash.",
    ),
    "stocks": MarketCategory(
        "stocks", "Stocks", "Yahoo Finance", True, tuple(STOCKS),
        "Large-cap US equities with delayed quotes.",
    ),
    "commodities": MarketCategory(
        "commodities", "Commodities", "Yahoo Finance", True, tuple(COMMODITIES),
        "Futures front-month continuous contracts.",
    ),
    "crypto": MarketCategory(
        "crypto", "Crypto", "Yahoo Finance", True, tuple(CRYPTO),
        "24/7 spot pairs quoted in USD.",
    ),
    "synthetics": MarketCategory(
        "synthetics", "Synthetic Indices", "Deriv", False, tuple(SYNTHETICS),
        "Synthetic indices require an authorised Deriv data connection. "
        "No prices are shown until that connection is configured and verified.",
    ),
}

# Engine-compatible views (kept for the existing analysis modules).
INSTRUMENTS: dict[str, list[Instrument]] = {
    "forex": FOREX,
    "crypto": CRYPTO,
    "stocks": STOCKS,
    "commodities": COMMODITIES,
    "indices": INDICES,
}

ENGINE_LABELS = {
    "forex": "Forex",
    "crypto": "Crypto",
    "stocks": "Stocks",
    "commodities": "Commodities",
    "indices": "Indices",
}

BREADTH_BASKETS: dict[str, list[str]] = {
    "^GSPC": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "JNJ", "V"],
    "^NDX": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "PEP", "COST"],
    "^DJI": ["AAPL", "MSFT", "JPM", "V", "UNH", "HD", "MCD", "CAT", "IBM", "GS"],
    "^FTSE": ["SHEL.L", "AZN.L", "HSBA.L", "ULVR.L", "BP.L", "GSK.L", "RIO.L", "BATS.L"],
}


def instrument_index() -> dict[str, Instrument]:
    """Symbol -> Instrument lookup across every market category."""
    out: dict[str, Instrument] = {}
    for category in MARKETS.values():
        for instrument in category.instruments:
            out[instrument.symbol] = instrument
    return out


# --------------------------------------------------------------------------- #
# Timeframes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Timeframe:
    """Scanner timeframe mapped to a provider period/interval."""

    label: str
    period: str
    interval: str
    minutes: int
    resample: str | None = None
    note: str = ""


TIMEFRAMES: dict[str, Timeframe] = {
    "M1": Timeframe("M1", "5d", "1m", 1, note="Provider limit: 1-minute bars, last few days."),
    "M5": Timeframe("M5", "1mo", "5m", 5),
    "M15": Timeframe("M15", "1mo", "15m", 15),
    "M30": Timeframe("M30", "1mo", "30m", 30),
    "H1": Timeframe("H1", "3mo", "1h", 60),
    "H4": Timeframe("H4", "6mo", "1h", 240, resample="4h",
                    note="Provider serves hourly bars; MNZ aggregates every four."),
    "D1": Timeframe("D1", "1y", "1d", 1440),
}

TIMEFRAME_ORDER = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
DEFAULT_TIMEFRAME = "H1"

STALE_BAR_MINUTES = {
    "1m": 10, "5m": 40, "15m": 90, "30m": 150,
    "1h": 240, "4h": 600, "1d": 4320, "1wk": 20160,
}


def timeframe(label: str | None) -> Timeframe:
    return TIMEFRAMES.get(label or DEFAULT_TIMEFRAME, TIMEFRAMES[DEFAULT_TIMEFRAME])


# --------------------------------------------------------------------------- #
# Scanner and signals
# --------------------------------------------------------------------------- #
SIGNAL_BUY_THRESHOLD = 0.28
SIGNAL_SELL_THRESHOLD = -0.28
SIGNAL_MIN_BARS = 60
# A directional label needs more than one indicator to agree. This is the
# number of components that must point the same way, and the smallest component
# reading counted as agreement.
SIGNAL_MIN_CONFIRMATIONS = 2
SIGNAL_CONFIRMATION_FLOOR = 0.15
# In a trendless market the same weighted score is weaker evidence, so the bar
# for a directional reading is raised instead of lowered.
SIGNAL_RANGE_ADX = 18.0
SIGNAL_RANGE_THRESHOLD = 0.45
BUY_THRESHOLD = SIGNAL_BUY_THRESHOLD
SELL_THRESHOLD = SIGNAL_SELL_THRESHOLD
MIN_BARS_FOR_ANALYSIS = 210

# ATR multiples used for simulated targets.
SIGNAL_SL_ATR = 1.5
SIGNAL_TP_ATR = 2.6
# A directional reading is a plan for the next few bars of its own timeframe.
# After that many bars it is stale and must be re-scanned instead of followed.
SIGNAL_VALID_BARS = 6

# Per-market signal weights (must sum to 1 for the direction components).
SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "forex": {"trend": 0.40, "momentum": 0.25, "rsi": 0.20, "structure": 0.15},
    "indices": {"trend": 0.40, "momentum": 0.25, "rsi": 0.15, "structure": 0.20},
    "stocks": {"trend": 0.38, "momentum": 0.27, "rsi": 0.15, "structure": 0.20},
    "commodities": {"trend": 0.38, "momentum": 0.24, "rsi": 0.18, "structure": 0.20},
    "crypto": {"trend": 0.35, "momentum": 0.30, "rsi": 0.15, "structure": 0.20},
    "default": {"trend": 0.38, "momentum": 0.27, "rsi": 0.15, "structure": 0.20},
}

ANALYST_WEIGHTS: dict[str, dict[str, float]] = {
    "forex": {"trend": 0.38, "momentum": 0.22, "rsi": 0.15, "volatility": 0.10, "volume": 0.05, "session": 0.10},
    "crypto": {"trend": 0.30, "momentum": 0.25, "rsi": 0.10, "volatility": 0.15, "volume": 0.20},
    "stocks": {"trend": 0.35, "momentum": 0.25, "rsi": 0.15, "volatility": 0.10, "volume": 0.15},
    "commodities": {"trend": 0.35, "momentum": 0.20, "rsi": 0.15, "volatility": 0.15, "volume": 0.10, "session": 0.05},
    "indices": {"trend": 0.40, "momentum": 0.25, "rsi": 0.10, "volatility": 0.15, "volume": 0.10},
}

ENGINE_STRATEGY_DEFAULTS: dict[str, StrategySettings] = {
    "forex": StrategySettings(fast_ma=50, slow_ma=200, rsi_period=14, rsi_buy_max=62.0,
                              rsi_sell_min=72.0, use_rsi_filter=True, allow_short=False,
                              cost_bps=2.0, position_size_pct=50.0),
    "crypto": StrategySettings(fast_ma=21, slow_ma=100, rsi_period=14, rsi_buy_max=70.0,
                               rsi_sell_min=80.0, use_rsi_filter=False, allow_short=False,
                               cost_bps=15.0, position_size_pct=50.0),
    "stocks": StrategySettings(fast_ma=50, slow_ma=200, rsi_period=14, rsi_buy_max=70.0,
                               rsi_sell_min=78.0, use_rsi_filter=True, allow_short=False,
                               cost_bps=5.0, position_size_pct=100.0),
    "commodities": StrategySettings(fast_ma=40, slow_ma=150, rsi_period=14, rsi_buy_max=68.0,
                                    rsi_sell_min=76.0, use_rsi_filter=True, allow_short=True,
                                    cost_bps=6.0, position_size_pct=60.0),
    "indices": StrategySettings(fast_ma=50, slow_ma=200, rsi_period=14, rsi_buy_max=72.0,
                                rsi_sell_min=80.0, use_rsi_filter=True, allow_short=False,
                                cost_bps=3.0, position_size_pct=100.0),
}

# Representative instruments scanned by "Scan All".
SCAN_SHORTLIST: dict[str, list[str]] = {
    "forex": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"],
    "indices": ["^DJI", "^GSPC", "^NDX", "^FTSE"],
    "stocks": ["AAPL", "MSFT", "NVDA", "TSLA"],
    "commodities": ["GC=F", "CL=F", "SI=F", "NG=F"],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"],
}

# --------------------------------------------------------------------------- #
# Demo trading
# --------------------------------------------------------------------------- #
DEMO_STARTING_BALANCE = 100.00
DEMO_ACCOUNT_NAME = "MNZ Demo Account"
DEMO_SLOT_CHOICES = [1, 3, 5]
DEMO_DEFAULT_SLOTS = 3
DEMO_RISK_PCT = 1.5
DEMO_MAX_OPEN_DAYS = 7   # stale simulated positions are closed on the next visit
DEFAULT_SIM_COST_BPS = 4.0
MAX_SIM_QUANTITY = 1_000_000.0
EQUITY_HISTORY_LIMIT = 5000

# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
ALERT_MIN_QUALITY = 65
ALERT_STRENGTHS = ["Strong", "Moderate"]
ALERT_MAX_PER_DAY = 12

# Resolved signals needed before a calibration group is treated as meaningful.
CALIBRATION_MIN_SAMPLE = 10

# --------------------------------------------------------------------------- #
# Planned compatibility targets — never shown as connected unless verified.
# --------------------------------------------------------------------------- #
PLANNED_PLATFORMS = [
    {
        "name": "MetaTrader 5",
        "status": "Planned",
        "detail": (
            "MT5 compatibility is a planned integration. MNZ has no MT5 bridge, "
            "account credentials or order routing, and cannot place trades."
        ),
    },
    {
        "name": "Razor Markets",
        "status": "Planned",
        "detail": (
            "Razor Markets is a planned data/execution target. No connection "
            "exists in this build; no Razor balance or account status is shown. "
            "Its licence claim could not be verified — planned is not an "
            "endorsement of the operator."
        ),
    },
    {
        "name": "Deriv",
        "status": "Planned",
        "detail": (
            "Synthetic indices on MNZ require a Deriv market-data connection. "
            "It is not configured, so synthetic prices are not displayed."
        ),
    },
    {
        "name": "Yahoo Finance",
        "status": "Active",
        "detail": (
            "Delayed public market data used for analysis and scanning. "
            "Read-only: no account, no balance, no execution."
        ),
    },
]

FUTURE_COMMERCIAL: dict[str, str] = {
    "Customer accounts": "Per-user records isolated by user id and account id.",
    "Subscription plans": "Plan catalogue is intentionally absent until billing exists.",
    "Secure authentication": "Local email/password accounts with PBKDF2 hashing.",
    "Automated execution": "DISABLED — LIVE_EXECUTION_ENABLED is hard-coded False.",
}

# --------------------------------------------------------------------------- #
# Broker due diligence.
#
# A licence check is not a recommendation, and a name only appears on the Broker
# page once these checks have been attempted. Each result records what could be
# confirmed and what could not, with the date it was checked — never an opinion
# about whether the firm is "good". No entry here may carry a referral link.
# --------------------------------------------------------------------------- #
BROKER_VERIFICATION_DATE = "19 November 2026"

BROKER_METHOD = (
    "Checked against the FSCA's published provider lists, the operator's own legal "
    "pages, and third-party regulatory reviews dated October–November 2025. The "
    "FSCA register itself is a form-based search, so it was not queried "
    "programmatically — confirm any result yourself before acting on it."
)

BROKER_STANDARD = [
    ("01", "Registered entity",
     "The company name and registration number on the site must belong to a company "
     "that exists on the CIPC register."),
    ("02", "FSP number on the register",
     "The FSP number is looked up on the FSCA register and the exact legal name must "
     "match — not a similar name, and not a badge on the firm's own site."),
    ("03", "Licence category",
     "Category I advice and intermediary services is a different licence to an OTC "
     "derivative provider. The category decides what the firm may actually do."),
    ("04", "Representative status",
     "A firm claiming to act under someone else's licence must appear as an appointed "
     "juristic representative on that licence."),
    ("05", "Domain listed",
     "The FSCA record should name the domain the firm trades on. An unlisted domain "
     "cannot be tied back to the licence."),
    ("06", "Counterparty and withdrawals",
     "Who holds client money, who is the counterparty to your contract, and where a "
     "complaint goes if a withdrawal stalls."),
]

# tone: "bad" = could not verify, "warn" = partially verified, "ok" = verified,
# "info" = not applicable or nothing to verify.
BROKER_REVIEW = [
    {
        "name": "Razor Markets (Pty) Ltd",
        "claim": (
            "Reg 2024/605719/07 · claims to be a juristic representative of Sithundhi "
            "Group (Pty) Ltd under FSP 52030"
        ),
        "found": (
            "Not found on the FSCA register in its own right, and the representative "
            "appointment plus the razormarkets.co.za domain are not shown against FSP "
            "52030. An earlier published version of the site's own disclaimer named a "
            "different licence (FSP 52677) before the live pages switched to 52030."
        ),
        "status": "Not verified — we would not fund an account",
        "tone": "bad",
    },
    {
        "name": "Sithundhi Group (Pty) Ltd",
        "claim": "FSP 52030 — named by Razor Markets as its principal",
        "found": (
            "The number is cited consistently across Razor Markets' current legal pages. "
            "We could not confirm that Razor Markets is its appointed representative, or "
            "that the trading domain is listed against the licence."
        ),
        "status": "Licence referenced — the link is unconfirmed",
        "tone": "warn",
    },
    {
        "name": "Elite Financial Services (Pty) Ltd",
        "claim": "FSP 52677 — named in an earlier version of the Razor Markets disclaimer",
        "found": (
            "Listed in the FSCA's own licensed-provider publications as a Category I "
            "advice and intermediary services provider. Nothing was found connecting it "
            "to the Razor Markets platform."
        ),
        "status": "Licensed entity — no link to the platform",
        "tone": "info",
    },
    {
        "name": "RocketX (Pty) Ltd",
        "claim": (
            "FSP 52142 · ODP 74 · reg 2020/824856/07 — named as counterparty and "
            "principal for Razor Markets CFD contracts"
        ),
        "found": (
            "RocketX's own disclosure matches: authorised FSP 52142 and OTC derivative "
            "provider 74. Razor Markets states every CFD contract is with RocketX, so the "
            "counterparty risk sits there. A licensed counterparty does not make the "
            "platform itself a licensed broker."
        ),
        "status": "Licensed — counterparty risk sits here",
        "tone": "ok",
    },
    {
        "name": "MetaTrader 5",
        "claim": "Software terminal — not a broker",
        "found": (
            "MetaQuotes licenses the terminal. Your account, your money and the licence "
            "behind it belong to the broker you connect the terminal to, never to MT5."
        ),
        "status": "Not a licence holder",
        "tone": "info",
    },
    {
        "name": "Deriv",
        "claim": "No South African licence claim is made by MNZ for Deriv",
        "found": (
            "Not assessed. MNZ has no Deriv data connection, so synthetic indices stay "
            "unavailable regardless of the operator's licensing."
        ),
        "status": "Not assessed",
        "tone": "info",
    },
]

LIVE_EXECUTION_NOTICE = (
    "Automated execution is disabled. MNZ never asks for brokerage passwords or "
    "account credentials and contains no order-routing code."
)

__all__ = [
    "APP_NAME", "BRAND", "TAGLINE", "VERSION", "PALETTE", "COLORS", "CHART_COLORWAY",
    "Instrument", "MarketCategory", "StrategySettings", "Timeframe",
    "INSTRUMENTS", "MARKETS", "ENGINE_LABELS", "BREADTH_BASKETS", "instrument_index",
    "TIMEFRAMES", "TIMEFRAME_ORDER", "DEFAULT_TIMEFRAME", "timeframe",
    "ENGINE_STRATEGY_DEFAULTS", "ANALYST_WEIGHTS", "SIGNAL_WEIGHTS",
    "BUY_THRESHOLD", "SELL_THRESHOLD", "MIN_BARS_FOR_ANALYSIS",
    "SIGNAL_BUY_THRESHOLD", "SIGNAL_SELL_THRESHOLD", "SIGNAL_MIN_BARS",
    "SIGNAL_SL_ATR", "SIGNAL_TP_ATR", "SIGNAL_VALID_BARS", "SCAN_SHORTLIST",
    "DEMO_STARTING_BALANCE", "DEMO_SLOT_CHOICES", "DEMO_DEFAULT_SLOTS", "DEMO_RISK_PCT",
    "DEMO_MAX_OPEN_DAYS",
    "DEFAULT_SIM_COST_BPS", "EQUITY_HISTORY_LIMIT",
    "ALERT_MIN_QUALITY", "ALERT_STRENGTHS", "ALERT_MAX_PER_DAY",
    "DISCLAIMER", "DEMO_BANNER", "FUTURE_COMMERCIAL", "PLANNED_PLATFORMS",
    "DB_PATH", "DATABASE_URL", "DATA_DIR", "EXPORT_DIR", "ALLOW_SAMPLE_DATA_FALLBACK",
    "DATA_CACHE_TTL_SECONDS", "STALE_BAR_MINUTES", "TIME_SOURCE_NOTE",
    "LIVE_EXECUTION_ENABLED", "LIVE_EXECUTION_NOTICE", "NAV_ITEMS", "PUBLIC_PAGES",
    "BROKER_STANDARD", "BROKER_REVIEW", "BROKER_METHOD", "BROKER_VERIFICATION_DATE",
]
