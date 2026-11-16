"""Commodities engine.

Gold, silver, energy, industrial metals and grains with trend analysis,
volatility monitoring, supply/demand context where it can be described honestly
and scheduled event awareness.

Commodity futures are quoted as continuous front-month series, so long histories
contain roll effects that this model does not remove.
"""

from __future__ import annotations

import config
from analysis import indicators
from engines import base
from engines.base import EngineContext, MarketEngine
from engines.base import _fmt_money, _fmt_pct

KEY = "commodities"

UNIVERSE = config.INSTRUMENTS["commodities"]

# Structural, educational context.  This is deliberately descriptive and is not
# presented as live supply/demand data.
SUPPLY_DEMAND = {
    "GC=F": {
        "drivers": "Real interest rates, the US dollar, central-bank reserve buying and ETF flows.",
        "structure": "Mine supply grows slowly; investment and jewellery demand dominate price swings.",
        "seasonality": "Demand often strengthens ahead of major Asian festival seasons.",
    },
    "SI=F": {
        "drivers": "Industrial demand (solar, electronics), mine supply and gold-linked sentiment.",
        "structure": "Silver is both a monetary and an industrial metal, so it moves with growth data too.",
        "seasonality": "Industrial restocking cycles can matter more than calendar seasonality.",
    },
    "CL=F": {
        "drivers": "OPEC+ policy, US inventories, refinery runs and global growth expectations.",
        "structure": "Short-cycle US shale supply responds quickly to price; OPEC+ spare capacity is the swing factor.",
        "seasonality": "US driving season (northern summer) and heating season (winter) shift demand.",
    },
    "BZ=F": {
        "drivers": "Global waterborne crude balances, OPEC+ policy and geopolitical risk.",
        "structure": "Brent prices international seaborne crude; the WTI–Brent spread reflects logistics.",
        "seasonality": "Similar to WTI but more exposed to international demand.",
    },
    "HG=F": {
        "drivers": "Chinese construction and grid demand, mine disruptions and exchange inventories.",
        "structure": "Copper is often treated as a growth proxy because of its electrical uses.",
        "seasonality": "Chinese construction activity is strongest after the Lunar New Year.",
    },
    "NG=F": {
        "drivers": "Weather, storage levels, LNG export capacity and production discipline.",
        "structure": "Storage and pipeline constraints make regional prices highly volatile.",
        "seasonality": "Winter heating demand and summer cooling demand drive the largest moves.",
    },
    "ZC=F": {
        "drivers": "US planting and harvest conditions, ethanol demand and export competition.",
        "structure": "Weather during pollination and yield reports dominate supply expectations.",
        "seasonality": "Prices are most sensitive around US planting and harvest windows.",
    },
    "ZW=F": {
        "drivers": "Global crop conditions, exporter policy and currency moves.",
        "structure": "Black Sea and other export logistics are a persistent supply risk.",
        "seasonality": "Northern-hemisphere harvest pressure typically peaks mid-year.",
    },
}

# Heuristic recurring releases — not a live calendar.
RECURRING_EVENTS = [
    ("US EIA petroleum status report", "Weekly, Wednesday ~15:30 UTC", "Crude, gasoline and distillate inventories"),
    ("US EIA natural gas storage", "Weekly, Thursday ~15:30 UTC", "Natural gas storage changes"),
    ("USDA WASDE report", "Monthly, ~12:00 UTC", "Grain supply and demand estimates"),
    ("CFTC Commitments of Traders", "Weekly, Friday ~15:30 UTC", "Positioning data for futures markets"),
    ("OPEC+ meetings", "Scheduled irregularly", "Production policy for crude oil"),
]


class CommoditiesEngine(MarketEngine):
    key = KEY
    title = "Commodities"
    description = (
        "Commodity analysis: trend structure, volatility regime, supply and demand "
        "context and scheduled event awareness."
    )
    universe = UNIVERSE

    def strategy_notes(self) -> list[str]:
        return [
            "Commodities trend for long stretches then mean-revert sharply, so this engine uses a 40/150 structure.",
            "Short-selling is enabled by default here because futures markets are two-sided.",
            "Simulated cost defaults to 6 bps and position size to 60% to reflect contract volatility.",
            "Data is a continuous front-month series; roll gaps are not adjusted, so treat long-horizon returns as approximate.",
        ]

    def context(self, data, settings) -> EngineContext:
        ctx = super().context(data, settings)
        ctx.headline = f"{self.label_for(data.symbol)} — commodity context"
        info = SUPPLY_DEMAND.get(data.symbol)
        if info:
            ctx.extras["supply_demand"] = info
            ctx.add_fact("Price drivers", info["drivers"])
            ctx.add_fact("Structural balance", info["structure"])
            ctx.add_fact("Seasonality", info["seasonality"])
        ctx.add_fact("Contract basis", "Continuous front-month futures series (roll effects not removed)")
        if data.ok:
            snap = indicators.snapshot(
                data.frame, fast=settings.fast_ma, slow=settings.slow_ma, rsi_period=settings.rsi_period
            )
            ctx.extras["snapshot"] = snap
            ctx.add_fact("Volatility regime", snap.volatility_label)
            ctx.add_fact("Average true range", f"{_fmt_money(snap.atr)} ({_fmt_pct(snap.atr_pct)})")
        ctx.notes.append(
            "Supply and demand notes are structural background written for education. "
            "No live inventory, positioning or shipping feed is connected."
        )
        ctx.events = [
            {"name": name, "schedule": schedule, "note": note}
            for name, schedule, note in RECURRING_EVENTS
        ]
        ctx.warnings.append(
            "Futures markets roll contracts. Differences between the quoted series and the "
            "front-month contract can be material."
        )
        return ctx


ENGINE = CommoditiesEngine()
