"""Commodities page: trend, volatility, supply/demand context and events."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from pages import engine_common


def _extra_context(data, settings, context) -> None:
    info = context.extras.get("supply_demand")
    ui.section("Supply and demand context", "structural background, not live data")
    if info:
        ui.html_table(pd.DataFrame([
            ("Price drivers", info["drivers"]),
            ("Structural balance", info["structure"]),
            ("Seasonality", info["seasonality"]),
        ], columns=["Factor", "Description"]), min_width=520)
    else:
        ui.notice("No supply/demand notes are available for this instrument.")
    ui.notice(
        "These notes describe structural drivers written for education. No live inventory, "
        "positioning, shipping or warehouse data is connected to this application."
    )
    st.caption(
        "Futures data is a continuous front-month series. Roll gaps between contracts are not adjusted, "
        "so long-horizon charts and backtests include roll effects."
    )


def render() -> None:
    engine_common.render_engine_page("commodities", extra_context=_extra_context)
