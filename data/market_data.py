"""Market data access for MNZ MARKET INTELLIGENCE.

The only live data provider is Yahoo Finance through ``yfinance``.  Every
request is normalised into a :class:`PriceData` object that always carries its
provenance (source, timestamp, delay status) so the interface can be honest
about what the user is looking at.

If the provider cannot be reached the module either returns an error (shown to
the user) or, when offline sample data is enabled, deterministic *sample* bars
that are flagged ``is_sample=True`` everywhere they are displayed.  Sample data
is never presented as real market data.
"""

from __future__ import annotations

import threading
import time as _time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import pandas as pd

import config

try:  # pragma: no cover - import guard is environment dependent
    import yfinance as yf

    YFINANCE_AVAILABLE = True
    YFINANCE_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    yf = None  # type: ignore[assignment]
    YFINANCE_AVAILABLE = False
    YFINANCE_IMPORT_ERROR = str(exc)


OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

_PERIOD_DAYS = {
    "1d": 1, "5d": 5, "1mo": 30, "3mo": 92, "6mo": 183,
    "1y": 366, "2y": 731, "5y": 1827, "10y": 3653, "max": 3653, "ytd": 240,
}
_INTERVAL_MINUTES = {
    "1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30,
    "60m": 60, "1h": 60, "90m": 90, "1d": 1440, "5d": 7200, "1wk": 10080, "1mo": 43200,
}
_SAMPLE_FREQ = {"1m": "min", "2m": "2min", "5m": "5min", "15m": "15min", "30m": "30min",
                "60m": "h", "1h": "h", "90m": "90min", "1d": "D", "5d": "5D",
                "1wk": "W", "1mo": "MS"}


# --------------------------------------------------------------------------- #
# Container
# --------------------------------------------------------------------------- #
@dataclass
class PriceData:
    """Normalised price history plus provenance metadata."""

    symbol: str
    period: str
    interval: str
    frame: pd.DataFrame
    source: str
    fetched_at: datetime
    is_sample: bool = False
    delayed: bool = True
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    # -- basic state -------------------------------------------------------- #
    @property
    def ok(self) -> bool:
        return self.error is None and not self.frame.empty

    @property
    def bars(self) -> int:
        return 0 if self.frame.empty else len(self.frame)

    @property
    def last_price(self) -> float | None:
        if self.frame.empty:
            return None
        value = float(self.frame["Close"].iloc[-1])
        return value if np.isfinite(value) else None

    @property
    def last_bar_time(self) -> datetime | None:
        if self.frame.empty:
            return None
        stamp = self.frame.index[-1]
        if isinstance(stamp, pd.Timestamp):
            return stamp.to_pydatetime().replace(tzinfo=None)
        return None

    @property
    def age_minutes(self) -> float | None:
        last = self.last_bar_time
        if last is None:
            return None
        now_utc = config.utcnow()
        return max(0.0, (now_utc - last).total_seconds() / 60.0)

    @property
    def stale(self) -> bool:
        age = self.age_minutes
        if age is None:
            return True
        limit = config.STALE_BAR_MINUTES.get(self.interval, 4320)
        return age > limit

    @property
    def source_label(self) -> str:
        if self.is_sample:
            return "Sample data — offline generator (NOT real market data)"
        return f"{self.source} — delayed feed"

    @property
    def quality(self) -> str:
        """Coarse data-quality bucket used by the analyst."""
        if not self.ok:
            return "unavailable"
        if self.is_sample:
            return "sample"
        if self.stale:
            return "delayed"
        return "current"

    def status_note(self) -> str:
        if not self.ok:
            return f"Unavailable — {self.error or 'no data returned'}"
        if self.is_sample:
            return "Sample data (offline) — not real market data"
        if self.stale:
            age = self.age_minutes or 0
            return f"Delayed — last bar {_human_age(age)} old"
        return "Data loaded"

    def describe(self) -> str:
        stamp = self.last_bar_time.strftime("%Y-%m-%d %H:%M") if self.last_bar_time else "unknown"
        return (
            f"{self.bars} bars · interval {self.interval} · last bar {stamp} · "
            f"source: {self.source_label}"
        )

    def closes(self) -> pd.Series:
        return self.frame["Close"].dropna() if not self.frame.empty else pd.Series(dtype=float)


def _human_age(minutes: float) -> str:
    if minutes < 90:
        return f"{minutes:.0f} min"
    if minutes < 60 * 36:
        return f"{minutes / 60:.1f} h"
    return f"{minutes / 1440:.1f} d"


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
_CACHE: dict[tuple, tuple[float, PriceData]] = {}
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    """Drop all cached provider responses (used by Settings)."""
    with _CACHE_LOCK:
        _CACHE.clear()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def get_price_history(
    symbol: str,
    period: str,
    interval: str,
    *,
    allow_sample: bool | None = None,
    force_refresh: bool = False,
    ttl: int | None = None,
) -> PriceData:
    """Fetch (or cache) history for ``symbol``.

    Returns a :class:`PriceData` in every case — failures carry ``error`` rather
    than raising, so pages can render an explicit message.
    """
    symbol = (symbol or "").strip()
    allow_sample = config.ALLOW_SAMPLE_DATA_FALLBACK if allow_sample is None else allow_sample
    ttl = config.DATA_CACHE_TTL_SECONDS if ttl is None else ttl
    key = (symbol, period, interval, bool(allow_sample))

    if not symbol:
        return PriceData(symbol="", period=period, interval=interval,
                         frame=_empty_frame(), source="none",
                         fetched_at=config.utcnow(), error="No symbol supplied.")

    if not force_refresh:
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit and (_time.time() - hit[0]) < ttl:
            return hit[1]

    data = _fetch_live(symbol, period, interval)
    if not data.ok and allow_sample:
        primary_error = data.error or "provider returned no rows"
        data = _sample_data(symbol, period, interval)
        data.notes.append(f"Live provider unavailable ({primary_error}). Showing offline sample data.")

    with _CACHE_LOCK:
        _CACHE[key] = (_time.time(), data)
    return data


def get_multiple(
    symbols: Iterable[str],
    period: str,
    interval: str,
    *,
    allow_sample: bool | None = None,
    limit: int | None = None,
) -> dict[str, PriceData]:
    """Fetch several symbols sequentially, tolerating individual failures."""
    out: dict[str, PriceData] = {}
    for index, symbol in enumerate(symbols):
        if limit is not None and index >= limit:
            break
        out[symbol] = get_price_history(symbol, period, interval, allow_sample=allow_sample)
    return out


def provider_status() -> dict:
    """Report provider availability for the Settings / Overview screens."""
    return {
        "provider": config.DATA_SOURCE_NAME,
        "installed": YFINANCE_AVAILABLE,
        "detail": "yfinance import failed: " + YFINANCE_IMPORT_ERROR if not YFINANCE_AVAILABLE else "Ready",
        "sample_fallback": config.ALLOW_SAMPLE_DATA_FALLBACK,
        "cache_ttl": config.DATA_CACHE_TTL_SECONDS,
    }


# --------------------------------------------------------------------------- #
# Live provider
# --------------------------------------------------------------------------- #
def _fetch_live(symbol: str, period: str, interval: str) -> PriceData:
    now = config.utcnow()
    if not YFINANCE_AVAILABLE:
        return PriceData(
            symbol=symbol, period=period, interval=interval, frame=_empty_frame(),
            source=config.DATA_SOURCE_NAME, fetched_at=now,
            error="yfinance is not installed. Run: pip install -r requirements.txt",
        )

    try:
        ticker = yf.Ticker(symbol)
        raw = ticker.history(period=period, interval=interval, auto_adjust=False, actions=False)
    except Exception as exc:  # network, rate-limit, delisted symbol, provider change
        return PriceData(
            symbol=symbol, period=period, interval=interval, frame=_empty_frame(),
            source=config.DATA_SOURCE_NAME, fetched_at=now,
            error=_friendly_error(exc),
        )

    frame = _normalise(raw)
    if frame.empty:
        return PriceData(
            symbol=symbol, period=period, interval=interval, frame=_empty_frame(),
            source=config.DATA_SOURCE_NAME, fetched_at=now,
            error="The provider returned no rows for this symbol, period or interval.",
        )
    return PriceData(
        symbol=symbol, period=period, interval=interval, frame=frame,
        source=config.DATA_SOURCE_NAME, fetched_at=now, is_sample=False, delayed=True,
    )


def _friendly_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    lowered = text.lower()
    if "429" in lowered or "too many requests" in lowered or "rate limit" in lowered:
        return "Provider rate limit reached (HTTP 429). Wait a few minutes or refresh later."
    if "connection" in lowered or "timed out" in lowered or "timeout" in lowered or "resolve" in lowered:
        return f"Could not reach the data provider: {text}"
    if "delisted" in lowered or "no price data" in lowered or "not found" in lowered:
        return f"Symbol unavailable at the provider: {text}"
    return text


# --------------------------------------------------------------------------- #
# Normalisation helpers
# --------------------------------------------------------------------------- #
def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=OHLCV_COLUMNS, dtype=float)


def _normalise(raw: pd.DataFrame | None) -> pd.DataFrame:
    """Return a clean, tz-naive OHLCV frame sorted by time."""
    if raw is None or len(raw) == 0:
        return _empty_frame()
    frame = raw.copy()

    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [str(col[0]) for col in frame.columns]

    renames = {str(c).lower(): c for c in frame.columns}
    mapping = {}
    for want in OHLCV_COLUMNS:
        if want.lower() in renames:
            mapping[renames[want.lower()]] = want
    frame = frame.rename(columns=mapping)

    for column in OHLCV_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan
    frame = frame[OHLCV_COLUMNS]

    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, errors="coerce", utc=True)
        frame = frame[frame.index.notna()]
    if getattr(frame.index, "tz", None) is not None:
        frame.index = frame.index.tz_convert("UTC").tz_localize(None)
    frame.index.name = "Date"

    frame["Volume"] = pd.to_numeric(frame["Volume"], errors="coerce").fillna(0.0)
    for column in ["Open", "High", "Low", "Close"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["Close"])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame


# --------------------------------------------------------------------------- #
# Offline sample generator (clearly labelled, deterministic)
# --------------------------------------------------------------------------- #
def _sample_bar_count(period: str, interval: str) -> int:
    days = _PERIOD_DAYS.get(period, 366)
    minutes = _INTERVAL_MINUTES.get(interval, 1440)
    raw = days * 1440 / max(minutes, 1)
    if interval in {"1d", "5d", "1wk", "1mo"} and period != "max":
        raw *= 5 / 7  # trading days only
    return int(np.clip(raw, 220, config.MAX_BARS_FOR_ANALYSIS))


def _sample_data(symbol: str, period: str, interval: str) -> PriceData:
    """Deterministic synthetic series, used only when the live feed fails."""
    seed = zlib.crc32(f"{symbol}|{period}|{interval}".encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    bars = _sample_bar_count(period, interval)

    start_price = float(np.exp(rng.uniform(np.log(4), np.log(1800))))
    is_crypto = symbol.endswith("-USD")
    is_rate = symbol.endswith("=X")
    per_bar_scale = (_INTERVAL_MINUTES.get(interval, 1440) / 1440) ** 0.5
    sigma = (0.006 if is_rate else 0.012) * (per_bar_scale if interval != "1wk" else 2.2)
    mu = rng.normal(0.0002, 0.0004) * per_bar_scale

    returns = rng.normal(mu, sigma, bars)
    # add gentle regime waves so trends and ranges both appear
    wave = np.sin(np.linspace(0, rng.uniform(3, 9), bars)) * sigma * 0.55
    closes = start_price * np.exp(np.cumsum(returns + wave))
    opens = np.empty(bars)
    opens[0] = closes[0] * (1 + rng.normal(0, sigma * 0.3))
    opens[1:] = closes[:-1] * (1 + rng.normal(0, sigma * 0.15, bars - 1))
    wick = np.abs(rng.normal(0, sigma * 0.7, bars))
    highs = np.maximum(opens, closes) * (1 + wick)
    lows = np.minimum(opens, closes) * (1 - wick)
    base_volume = 5e6 if not is_rate else 1.2e5
    volumes = base_volume * (0.5 + rng.lognormal(0, 0.5, bars)) * (1 + np.abs(returns) * 25)

    freq = _SAMPLE_FREQ.get(interval, "D")
    index = pd.date_range(end=pd.Timestamp.now(tz="UTC").tz_localize(None).floor("min"),
                          periods=bars, freq=freq)
    frame = pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=index,
    )
    frame.index.name = "Date"
    return PriceData(
        symbol=symbol, period=period, interval=interval, frame=frame,
        source="MNZ offline sample generator", fetched_at=config.utcnow(),
        is_sample=True, delayed=False,
        notes=[
            "Synthetic demonstration series. Prices, volumes and timestamps are "
            "generated locally and are NOT real market data.",
            "Never use sample data to evaluate the market or a strategy for real money.",
        ],
    )
