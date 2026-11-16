"""Crypto engine.

Trend, momentum, volatility and volume analysis for Bitcoin, Ethereum and other
supported cryptocurrencies, with explicit 24/7 market information.

Crypto trades continuously, is more volatile than FX, and has higher simulated
transaction costs.  Its defaults therefore use faster moving averages, no RSI
entry filter by default, and a larger cost assumption.
"""

from __future__ import annotations

import config
from analysis import indicators
from engines import base
from engines.base import EngineContext, MarketEngine

KEY = "crypto"

UNIVERSE = config.INSTRUMENTS["crypto"]

MARKET_NOTES = [
    "Crypto markets trade 24/7, including weekends and public holidays.",
    "There is no official closing price; daily bars are cut at 00:00 UTC by most providers.",
    "Weekend liquidity is usually thinner, which can widen spreads and exaggerate moves.",
    "Exchange outages, funding rates and derivatives basis are not modelled here.",
]


class CryptoEngine(MarketEngine):
    key = KEY
    title = "Crypto"
    description = (
        "Digital-asset analysis: trend structure, momentum, volatility regime, "
        "trading volume and 24/7 market context."
    )
    universe = UNIVERSE

    def strategy_notes(self) -> list[str]:
        return [
            "Crypto trends develop faster, so this engine defaults to a 21/100 moving-average structure.",
            "No RSI entry filter by default — crypto can stay overbought for long stretches during trends.",
            "Simulated cost defaults to 15 bps to reflect wider spreads and slippage than major FX.",
            "Volatility is reported as annualised standard deviation and an ATR percentage; size positions accordingly.",
        ]

    def context(self, data, settings) -> EngineContext:
        ctx = super().context(data, settings)
        ctx.headline = f"{self.label_for(data.symbol)} — 24/7 market context"
        ctx.add_fact("Market hours", "24 hours, 7 days a week")
        ctx.add_fact("Daily bar cut-off", "00:00 UTC (provider dependent)")
        snap = indicators.snapshot(
            data.frame, fast=settings.fast_ma, slow=settings.slow_ma, rsi_period=settings.rsi_period
        ) if data.ok else None
        if snap is not None:
            ctx.extras["snapshot"] = snap
            ctx.add_fact("Volatility regime", snap.volatility_label)
            ctx.add_fact("Annualised volatility", base._fmt_pct(snap.annual_vol))
            ctx.add_fact("Volume vs 50-bar average", f"{snap.volume_ratio:.2f}x" if snap.volume_ratio == snap.volume_ratio else "n/a")
        ctx.notes.extend(MARKET_NOTES)
        ctx.warnings.append(
            "Crypto volume and price feeds differ between exchanges. Cross-check any "
            "significant level against a second venue you trust."
        )
        return ctx


ENGINE = CryptoEngine()
