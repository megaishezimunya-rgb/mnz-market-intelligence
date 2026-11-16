"""Indices engine.

Major global market indices with trend, momentum, volatility and market breadth
where it can be computed.  Breadth uses a representative basket of index
constituents as a documented proxy, because a full constituent feed is not
available from the free data source.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
from analysis import indicators
from data import market_data
from engines import base
from engines.base import EngineContext, MarketEngine

KEY = "indices"

UNIVERSE = config.INSTRUMENTS["indices"]

INDEX_INFO = {
    "^GSPC": ("United States", "S&P 500 — large-cap US benchmark"),
    "^NDX": ("United States", "Nasdaq 100 — growth and technology heavy"),
    "^DJI": ("United States", "Dow Jones — price-weighted industrials"),
    "^FTSE": ("United Kingdom", "FTSE 100 — large-cap UK, globally exposed"),
    "^GDAXI": ("Germany", "DAX — German large caps"),
    "^STOXX50E": ("Euro area", "Euro Stoxx 50 — euro-area blue chips"),
    "^N225": ("Japan", "Nikkei 225 — export-sensitive Japanese large caps"),
    "^HSI": ("Hong Kong", "Hang Seng — China/Hong Kong exposure"),
    "^AXJO": ("Australia", "ASX 200 — resources and financials heavy"),
    "^BSESN": ("India", "BSE Sensex — Indian large caps"),
}

SESSION_NOTES = "Cash-session hours differ by exchange; index quotes outside those hours may be futures or stale."


def compute_breadth(index_symbol: str, period: str = "1y", interval: str = "1d") -> dict:
    """Approximate market breadth from a representative constituent basket."""
    basket = config.BREADTH_BASKETS.get(index_symbol)
    if not basket:
        return {
            "available": False,
            "reason": "No breadth basket is configured for this index, so breadth is not shown rather than estimated.",
        }
    data = market_data.get_multiple(basket, period, interval, limit=10)
    above_50 = above_200 = 0
    valid_50 = valid_200 = 0
    rsis: list[float] = []
    advancers = decliners = 0
    used: list[str] = []
    missing: list[str] = []

    for symbol, price in data.items():
        if not price.ok or price.bars < 55:
            missing.append(symbol)
            continue
        frame = price.frame
        close = frame["Close"]
        used.append(symbol)
        ma50 = indicators.sma(close, 50)
        if pd.notna(ma50.iloc[-1]):
            valid_50 += 1
            above_50 += int(close.iloc[-1] > ma50.iloc[-1])
        if len(close) >= 210:
            ma200 = indicators.sma(close, 200)
            if pd.notna(ma200.iloc[-1]):
                valid_200 += 1
                above_200 += int(close.iloc[-1] > ma200.iloc[-1])
        last_rsi = indicators.rsi(close, 14).iloc[-1]
        if pd.notna(last_rsi):
            rsis.append(float(last_rsi))
        if len(close) >= 2:
            if close.iloc[-1] > close.iloc[-2]:
                advancers += 1
            elif close.iloc[-1] < close.iloc[-2]:
                decliners += 1

    if not used:
        return {
            "available": False,
            "reason": "Breadth could not be computed because no basket member returned usable data.",
            "missing": missing,
        }
    return {
        "available": True,
        "constituents": len(basket),
        "used": len(used),
        "missing": missing,
        "pct_above_50dma": 100.0 * above_50 / valid_50 if valid_50 else float("nan"),
        "pct_above_200dma": 100.0 * above_200 / valid_200 if valid_200 else float("nan"),
        "avg_rsi": float(np.mean(rsis)) if rsis else float("nan"),
        "advancers": advancers,
        "decliners": decliners,
        "sample": used,
        "proxy_note": (
            "Breadth is approximated from "
            f"{len(used)} representative large-cap constituents, not the full index membership."
        ),
    }


class IndicesEngine(MarketEngine):
    key = KEY
    title = "Indices"
    description = (
        "Global index analysis: trend structure, momentum, volatility and "
        "market breadth approximated from representative constituents."
    )
    universe = UNIVERSE

    def strategy_notes(self) -> list[str]:
        return [
            "Indices trend slowly and broadly, so this engine uses a 50/200 structure and a permissive RSI filter.",
            "Simulated cost defaults to 3 bps; index exposure is often accessed through low-cost instruments.",
            "Index levels are not directly tradable. Simulated trades in this demo use the index level as a proxy price.",
            "Breadth is a proxy from a constituent basket and is labelled as such wherever it appears.",
        ]

    def context(self, data, settings) -> EngineContext:
        ctx = super().context(data, settings)
        region, blurb = INDEX_INFO.get(data.symbol, ("—", "Global index"))
        ctx.headline = f"{self.label_for(data.symbol)} — index context"
        ctx.add_fact("Region", region)
        ctx.add_fact("Benchmark", blurb)
        ctx.add_fact("Trading hours", SESSION_NOTES)
        if data.ok:
            snap = indicators.snapshot(
                data.frame, fast=settings.fast_ma, slow=settings.slow_ma, rsi_period=settings.rsi_period
            )
            ctx.extras["snapshot"] = snap
            ctx.add_fact("Trend structure", snap.trend_label)
        ctx.notes.append(
            "Index quotes can reflect the cash session or a futures overlay depending on the "
            "provider and time of day."
        )
        return ctx


ENGINE = IndicesEngine()
