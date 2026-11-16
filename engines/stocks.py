"""Stocks engine.

Equity analysis with ticker search, moving averages, RSI/MACD, volume, company
fundamentals where the provider supplies them, and earnings-event awareness.

Equity defaults assume medium-term trend following on daily bars, a 5 bps
simulated cost, and a 50/200 moving-average structure.
"""

from __future__ import annotations

import threading
import time as _time

import config
from analysis import indicators
from engines import base
from engines.base import EngineContext, MarketEngine
from engines.base import _fmt_num, _fmt_pct

try:  # pragma: no cover - environment dependent
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

KEY = "stocks"

UNIVERSE = config.INSTRUMENTS["stocks"]

REGULAR_HOURS = "14:30–21:00 UTC (09:30–16:00 New York, daylight-saving dependent)"
PRE_POST = "Pre-market from ~09:00 UTC and after-hours to ~01:00 UTC; quotes may be thin."

_FUNDAMENTALS_TTL = 900.0
_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()


def clear_company_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _normalised_dividend_yield(info: dict) -> float | None:
    """Return dividend yield as a fraction (0.003 = 0.3%).

    yfinance has changed units across releases: older versions returned a
    fraction in ``dividendYield``, newer ones return a percentage. Deriving the
    fraction from the annual rate and price is unambiguous, with guarded
    fallbacks for any release in between.
    """
    rate = info.get("dividendRate")
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    if isinstance(rate, (int, float)) and isinstance(price, (int, float)) and price:
        return float(rate) / float(price)
    trailing = info.get("trailingAnnualDividendYield")
    if isinstance(trailing, (int, float)):
        return float(trailing)
    legacy = info.get("dividendYield")
    if isinstance(legacy, (int, float)):
        # Current yfinance releases report this field in percent (0.3 = 0.3%).
        return float(legacy) / 100.0
    return None


def _cached(key: str, factory, ttl: float = _FUNDAMENTALS_TTL) -> dict:
    with _LOCK:
        hit = _CACHE.get(key)
    if hit and (_time.time() - hit[0]) < ttl:
        return hit[1]
    value = factory()
    with _LOCK:
        _CACHE[key] = (_time.time(), value)
    return value


def fundamentals(symbol: str) -> dict:
    """Company fundamentals, or a documented reason why they are unavailable."""
    def load() -> dict:
        if yf is None:
            return {"available": False, "error": "yfinance is not installed."}
        try:
            info = yf.Ticker(symbol).get_info()
        except Exception as exc:
            return {"available": False, "error": f"Company profile unavailable: {exc}"}
        if not info:
            return {"available": False, "error": "The provider returned no company profile for this ticker."}
        return {
            "available": True,
            "name": info.get("longName") or info.get("shortName") or symbol,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "profit_margin": info.get("profitMargins"),
            "dividend_yield": _normalised_dividend_yield(info),
            "beta": info.get("beta"),
            "week52_high": info.get("fiftyTwoWeekHigh"),
            "week52_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "source": "Yahoo Finance company profile",
        }

    return _cached(f"fund:{symbol}", load)


def earnings_info(symbol: str) -> dict:
    """Next scheduled earnings date plus recent reported surprises if present."""
    def load() -> dict:
        if yf is None:
            return {"available": False, "error": "yfinance is not installed."}
        ticker = yf.Ticker(symbol)
        next_date = None
        eps_estimate = None
        error = None
        try:
            calendar = ticker.calendar
            if isinstance(calendar, dict):
                dates = calendar.get("Earnings Date") or []
                if dates:
                    next_date = str(dates[0])
                eps_estimate = calendar.get("Earnings Average")
            elif hasattr(calendar, "empty") and not calendar.empty:
                next_date = str(calendar.iloc[0, 0])
        except Exception as exc:
            error = f"Earnings calendar unavailable: {exc}"

        history: list[dict] = []
        try:
            frame = ticker.earnings_dates
            if frame is not None and not frame.empty:
                # Newest first; future estimates without a reported figure are excluded
                # from the "recent reports" table.
                recent = frame.sort_index(ascending=False)
                if "Reported EPS" in recent.columns:
                    reported = recent[recent["Reported EPS"].notna()]
                    if not reported.empty:
                        recent = reported
                recent = recent.head(6)
                for stamp, row in recent.iterrows():
                    history.append({
                        "date": str(stamp)[:10],
                        "eps_estimate": row.get("EPS Estimate"),
                        "reported": row.get("Reported EPS"),
                        "surprise_pct": row.get("Surprise(%)"),
                    })
        except Exception:
            pass

        if next_date is None and not history:
            return {"available": False, "error": error or "No earnings data returned by the provider."}
        return {
            "available": True,
            "next_date": next_date,
            "eps_estimate": eps_estimate,
            "history": history,
            "partial_error": error,
            "source": "Yahoo Finance earnings calendar",
        }

    return _cached(f"earn:{symbol}", load)


class StocksEngine(MarketEngine):
    key = KEY
    title = "Stocks"
    description = (
        "Equity analysis: ticker search, price structure, moving averages, "
        "RSI/MACD, volume, company fundamentals and earnings awareness."
    )
    universe = UNIVERSE

    def strategy_notes(self) -> list[str]:
        return [
            "Daily-bar trend following with a 50/200 moving-average structure and an RSI entry filter.",
            "Simulated cost defaults to 5 bps, a compromise between commission and spread costs.",
            "Earnings gaps can jump over stop levels; position sizing is the only protection the model has.",
            "Fundamentals and earnings dates come from the provider and may lag company filings.",
        ]

    def search(self, query: str, limit: int = 8) -> list[config.Instrument]:
        """Search the built-in universe, then optionally the provider's symbol index."""
        query = (query or "").strip().lower()
        if not query:
            return []
        matches = [
            item for item in UNIVERSE
            if query in item.symbol.lower() or query in item.label.lower()
        ][:limit]
        if matches or yf is None or len(query) < 2:
            return matches
        try:
            results = yf.Search(query, max_results=limit).quotes
        except Exception:
            return []
        for quote in results or []:
            symbol = quote.get("symbol")
            if not symbol or quote.get("quoteType") not in {None, "EQUITY", "ETF"}:
                continue
            matches.append(config.Instrument(
                symbol, quote.get("shortname") or quote.get("longname") or symbol, KEY,
                quote.get("exchange") or "",
            ))
        return matches[:limit]

    def context(self, data, settings) -> EngineContext:
        ctx = super().context(data, settings)
        name = self.label_for(data.symbol)
        ctx.headline = f"{name} — equity context"
        ctx.add_fact("Regular session (UTC)", REGULAR_HOURS)
        ctx.add_fact("Extended hours", PRE_POST)

        profile = fundamentals(data.symbol)
        if profile.get("available"):
            ctx.extras["fundamentals"] = profile
            if profile.get("sector"):
                ctx.add_fact("Sector", str(profile["sector"]))
            if profile.get("industry"):
                ctx.add_fact("Industry", str(profile["industry"]))
            if profile.get("market_cap"):
                cap = profile["market_cap"]
                ctx.add_fact("Market capitalisation", f"${cap / 1e9:,.1f}B" if isinstance(cap, (int, float)) else str(cap))
            if profile.get("trailing_pe"):
                ctx.add_fact("Trailing P/E", _fmt_num(profile["trailing_pe"]))
            if profile.get("beta"):
                ctx.add_fact("Beta (5y)", _fmt_num(profile["beta"]))
        else:
            ctx.warnings.append(profile.get("error", "Fundamentals unavailable."))

        earnings = earnings_info(data.symbol)
        if earnings.get("available"):
            ctx.extras["earnings"] = earnings
            if earnings.get("next_date"):
                ctx.add_fact("Next earnings (provider)", earnings["next_date"])
                ctx.warnings.append(
                    "Earnings events can produce large overnight gaps. The indicator model "
                    "does not price event risk."
                )
        else:
            ctx.notes.append(earnings.get("error", "Earnings calendar unavailable."))

        if data.ok:
            snap = indicators.snapshot(
                data.frame, fast=settings.fast_ma, slow=settings.slow_ma, rsi_period=settings.rsi_period
            )
            ctx.extras["snapshot"] = snap
            ctx.add_fact("Volume vs 50-bar average",
                         f"{snap.volume_ratio:.2f}x" if snap.volume_ratio == snap.volume_ratio else "n/a")
            ctx.add_fact("Annualised volatility", _fmt_pct(snap.annual_vol))
        return ctx


ENGINE = StocksEngine()
