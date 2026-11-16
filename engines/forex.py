"""Forex engine.

Currency-pair analysis with moving averages, RSI, MACD, trend structure,
trading-session information and economic-event awareness.

Defaults are tuned for 24/5 FX: slower moving averages, low simulated cost,
moderate position sizing, and no short-selling unless the user enables it.
"""

from __future__ import annotations

import config
from engines import base
from engines.base import EngineContext, MarketEngine, liquidity_note, session_rows

KEY = "forex"

UNIVERSE = config.INSTRUMENTS["forex"]

# Which sessions historically matter most for each pair (educational context).
SESSION_FOCUS = {
    "EURUSD=X": "London and New York overlap; European data and US releases dominate.",
    "GBPUSD=X": "London session; UK data and BoE communication are the main drivers.",
    "USDJPY=X": "Tokyo and New York; US yields and BoJ policy are the main drivers.",
    "AUDUSD=X": "Sydney and Tokyo; China data and risk sentiment matter.",
    "USDCAD=X": "New York; crude oil and BoC policy matter.",
    "USDCHF=X": "London; defensive flows and SNB policy matter.",
    "NZDUSD=X": "Sydney; risk appetite and RBNZ policy matter.",
    "EURGBP=X": "London; relative euro-area vs UK data.",
    "EURJPY=X": "London and Tokyo; a higher-volatility cross.",
    "GBPJPY=X": "London and Tokyo; historically one of the widest-ranging crosses.",
}

# Recurring, widely scheduled release windows.  These are heuristics, NOT a live
# economic calendar — the app says so wherever they are shown.
RECURRING_EVENTS = [
    ("US Non-farm payrolls", "First Friday of the month, ~13:30 UTC", "High impact on USD pairs"),
    ("US CPI inflation", "Monthly, ~13:30 UTC (release day varies)", "High impact on USD pairs"),
    ("FOMC rate decision", "Eight meetings per year, ~19:00 UTC", "High impact across all USD pairs"),
    ("ECB rate decision", "Roughly every six weeks, ~13:15 UTC", "High impact on EUR crosses"),
    ("BoE rate decision", "Roughly every six weeks, ~12:00 UTC", "High impact on GBP crosses"),
    ("BoJ rate decision", "Roughly monthly, timing varies", "High impact on JPY crosses"),
]


class ForexEngine(MarketEngine):
    key = KEY
    title = "Forex"
    description = (
        "Currency-pair analysis: moving averages, RSI, MACD, trend structure, "
        "session timing and scheduled event risk."
    )
    universe = UNIVERSE

    def strategy_notes(self) -> list[str]:
        return [
            "FX trends are slower and ranges are tighter than equities, so this engine defaults to a 50/200 moving-average structure.",
            "Simulated cost defaults to 2 bps because major-pair spreads are typically tight; raise it for crosses.",
            "Long-only by default — enable short-selling in Settings only if you understand both legs of the simulation.",
            "Positions default to 50% of virtual equity because FX is usually traded with leverage, which this demo does not model.",
        ]

    def context(self, data, settings) -> EngineContext:
        ctx = super().context(data, settings)
        now = base.utc_now()
        ctx.headline = f"{self.label_for(data.symbol)} — session and event context"
        ctx.add_fact("Pairs tracked", str(len(UNIVERSE)))
        ctx.add_fact("Market hours", "24 hours, Sunday ~21:00 UTC to Friday ~21:00 UTC")
        ctx.add_fact("Sessions open now (UTC)", ", ".join(base.active_sessions(now)) or "None")
        ctx.add_fact("Liquidity", liquidity_note(now))
        ctx.extras["sessions"] = session_rows(now)
        focus = SESSION_FOCUS.get(data.symbol)
        if focus:
            ctx.notes.append(f"Session focus: {focus}")
        ctx.notes.append(
            "Session windows are approximations in UTC and shift with daylight saving. "
            "They describe typical activity, not guaranteed liquidity."
        )
        ctx.events = [
            {"name": name, "schedule": schedule, "note": note}
            for name, schedule, note in RECURRING_EVENTS
        ]
        ctx.warnings.append(
            "No live economic calendar is connected. Release windows above are recurring "
            "heuristics — check an official calendar before trading around events."
        )
        if now.weekday() >= 5:
            ctx.warnings.append("Weekend: FX spot markets are closed, so the latest bar is the Friday close.")
        return ctx


ENGINE = ForexEngine()
