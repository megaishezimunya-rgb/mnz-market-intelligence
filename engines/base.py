"""Shared building blocks for the five market engines.

Each engine exposes:

* ``key`` / ``title`` / ``description``
* ``UNIVERSE`` — the instruments it supports
* ``default_settings()`` — its own strategy configuration
* ``context()`` — market-specific facts (sessions, fundamentals, breadth,
  supply/demand, event windows) used by the pages and the analyst

Engines deliberately do **not** share a single strategy preset: FX, crypto,
equities, commodities and indices have different volatility, cost and session
profiles, and each default is documented in ``config.ENGINE_STRATEGY_DEFAULTS``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

import config
from analysis import indicators
from data.market_data import PriceData


@dataclass
class EngineContext:
    """Market-specific information attached to an analysis."""

    headline: str = ""
    facts: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    def add_fact(self, label: str, value: str) -> None:
        self.facts.append((label, value))

    def add_event(self, name: str, schedule: str, note: str = "") -> None:
        self.events.append({"name": name, "schedule": schedule, "note": note})


class MarketEngine:
    """Base class documenting the engine interface."""

    key: str = ""
    title: str = ""
    description: str = ""
    universe: list[config.Instrument] = []

    # -- universe ----------------------------------------------------------- #
    def instruments(self) -> list[config.Instrument]:
        return list(self.universe)

    def instrument(self, symbol: str) -> config.Instrument | None:
        for item in self.universe:
            if item.symbol == symbol:
                return item
        return None

    def label_for(self, symbol: str) -> str:
        item = self.instrument(symbol)
        return item.label if item else symbol

    # -- settings ----------------------------------------------------------- #
    def default_settings(self) -> config.StrategySettings:
        return copy.deepcopy(config.ENGINE_STRATEGY_DEFAULTS[self.key])

    def weights(self) -> dict[str, float]:
        return dict(config.ANALYST_WEIGHTS[self.key])

    def strategy_notes(self) -> list[str]:
        """Why this engine's defaults differ from the others."""
        return []

    # -- context ------------------------------------------------------------ #
    def context(self, data: PriceData, settings: config.StrategySettings) -> EngineContext:
        ctx = EngineContext(headline=f"{self.title} market structure")
        if not data.ok:
            ctx.warnings.append(f"No price history available: {data.error}")
            return ctx
        snap = indicators.snapshot(
            data.frame, fast=settings.fast_ma, slow=settings.slow_ma,
            rsi_period=settings.rsi_period,
        )
        ctx.add_fact("Trend structure", snap.trend_label)
        ctx.add_fact("Volatility (annualised)", _fmt_pct(snap.annual_vol))
        ctx.add_fact("Average true range", f"{_fmt_num(snap.atr)} ({_fmt_pct(snap.atr_pct)})")
        return ctx


# --------------------------------------------------------------------------- #
# Formatting helpers shared by engines and pages
# --------------------------------------------------------------------------- #
def _fmt_pct(value: float, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:.{digits}f}%"


def _fmt_num(value: float, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    if abs(value) >= 10_000:
        return f"{value:,.0f}"
    return f"{value:,.{digits}f}"


def _fmt_money(value: float) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"${value:,.2f}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def minutes_of_day(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def in_utc_window(minutes: int, start: int, end: int) -> bool:
    """True when ``minutes`` falls inside [start, end) handling midnight wrap."""
    if start == end:
        return False
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end


def window_label(start: int, end: int) -> str:
    return f"{start // 60:02d}:{start % 60:02d}–{end // 60:02d}:{end % 60:02d} UTC"


def session_rows(now: datetime | None = None) -> list[dict]:
    """Trading-session snapshot for FX-style 24/5 markets (approximate UTC)."""
    now = now or utc_now()
    minutes = minutes_of_day(now)
    weekday = now.weekday()
    sessions = [
        ("Sydney", 21 * 60, 6 * 60),
        ("Tokyo", 0, 9 * 60),
        ("London", 7 * 60, 16 * 60),
        ("New York", 12 * 60, 21 * 60),
    ]
    rows = []
    for name, start, end in sessions:
        open_now = in_utc_window(minutes, start, end) and weekday < 5
        rows.append({
            "Session": name,
            "Window (UTC)": window_label(start, end),
            "Status": "Open" if open_now else "Closed",
            "start": start,
            "end": end,
        })
    return rows


def active_sessions(now: datetime | None = None) -> list[str]:
    return [row["Session"] for row in session_rows(now) if row["Status"] == "Open"]


def liquidity_note(now: datetime | None = None) -> str:
    """Describe current FX/CFD liquidity conditions."""
    now = now or utc_now()
    if now.weekday() == 5 or (now.weekday() == 6 and now.hour < 21) or (
        now.weekday() == 4 and now.hour >= 21
    ):
        return "The FX market is closed for the weekend (closed from ~21:00 UTC Friday to ~21:00 UTC Sunday)."
    active = active_sessions(now)
    if not active:
        return "Between sessions — liquidity is typically thinnest around the daily rollover."
    if "London" in active and "New York" in active:
        return "London / New York overlap — historically the deepest liquidity of the day."
    return f"Active session(s): {', '.join(active)}. Liquidity is usually better during the London and New York sessions."
