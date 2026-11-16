"""Indices page: global benchmarks, momentum, volatility and breadth."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from engines import indices
from pages import engine_common


def _extra_context(data, settings, context) -> None:
    ui.section("Market breadth", "approximate, from representative constituents")
    breadth = indices.compute_breadth(data.symbol, period="1y", interval="1d")
    if not breadth.get("available"):
        ui.notice(f"<strong>Breadth unavailable.</strong> {ui_html(breadth.get('reason', ''))}")
        return

    pct50 = breadth["pct_above_50dma"]
    pct200 = breadth["pct_above_200dma"]
    ui.kpi_row([
        {"label": "Above 50-day MA", "value": ui.pct(pct50, 0),
         "note": f"{breadth['used']} of {breadth['constituents']} constituents"},
        {"label": "Above 200-day MA", "value": ui.pct(pct200, 0),
         "note": "requires 200 bars per constituent"},
        {"label": "Average RSI", "value": ui.number(breadth["avg_rsi"], 1),
         "note": "mean RSI of the basket"},
        {"label": "Advancers / decliners", "value": f"{breadth['advancers']} / {breadth['decliners']}",
         "note": "latest bar direction"},
    ])
    ui.show_chart(ui.bar_chart(
        pd.DataFrame({"Measure": ["Above 50DMA", "Above 200DMA"], "Percent": [pct50, pct200]}),
        "Measure", "Percent", height=230, color_by_sign=False, title="Breadth (%)",
    ))
    ui.notice(f"<strong>Proxy measure.</strong> {ui_html(breadth['proxy_note'])}")
    if breadth.get("missing"):
        st.caption("Constituents without usable data: " + ", ".join(breadth["missing"]))
    ui.show_table(pd.DataFrame({"Basket constituent": breadth["sample"]}))
    st.caption(
        "Breadth is computed from live provider data for the basket above. If the provider is "
        "unavailable and sample data is enabled, these breadth figures are synthetic too."
    )


def ui_html(text: str) -> str:
    from html import escape

    return escape(str(text))


def render() -> None:
    engine_common.render_engine_page("indices", extra_context=_extra_context)
