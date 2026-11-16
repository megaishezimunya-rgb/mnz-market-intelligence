"""Crypto page: trend, momentum, volatility and 24/7 market context."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import ui
from engines import crypto
from pages import engine_common


def _extra_context(data, settings, context) -> None:
    ui.section("24/7 market information", "continuous trading")
    for note in crypto.MARKET_NOTES:
        st.markdown(f"- {note}")
    snap = context.extras.get("snapshot")
    if snap is not None:
        ui.section("Volatility and volume", "crypto-specific monitoring")
        ui.show_table(pd.DataFrame([
            ("Annualised volatility", ui.pct(snap.annual_vol)),
            ("Volatility regime", snap.volatility_label),
            ("ATR as % of price", ui.pct(snap.atr_pct)),
            ("10-bar vs 50-bar volume",
             f"{snap.volume_ratio:.2f}x" if snap.volume_ratio == snap.volume_ratio else "n/a"),
            ("RSI", ui.number(snap.rsi, 1)),
        ], columns=["Measure", "Reading"]))
        if snap.volatility_label in {"High", "Elevated"}:
            ui.notice(
                "Volatility is high relative to its recent range. The demo does not model margin calls, "
                "so treat simulated position sizes as optimistic.",
                "warn",
            )
    ui.section("Cost assumption", "crypto markets are not free to trade")
    st.caption(
        f"Crypto defaults to {config.ENGINE_STRATEGY_DEFAULTS['crypto'].cost_bps:.0f} bps per side to reflect "
        "wider spreads and slippage than major FX pairs. Change it under Strategy if you want a different assumption."
    )


def render() -> None:
    engine_common.render_engine_page("crypto", extra_context=_extra_context)
