"""Forex page: pairs, session information and scheduled event awareness."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import ui
from engines import base
from pages import engine_common


def _extra_context(data, settings, context) -> None:
    sessions = context.extras.get("sessions") or []
    if sessions:
        ui.section("Trading sessions", "approximate UTC windows")
        ui.show_table(pd.DataFrame(sessions)[["Session", "Window (UTC)", "Status"]])
        st.caption(base.liquidity_note())
    focus = [note for note in context.notes if note.startswith("Session focus")]
    if focus:
        ui.notice("<strong>Session focus.</strong> " + ui_html(focus[0].split(":", 1)[-1].strip()))
    ui.section("Simulated cost assumption", "this engine's configuration")
    st.caption(
        f"Forex defaults to {config.ENGINE_STRATEGY_DEFAULTS['forex'].cost_bps:.1f} bps per side and "
        f"{config.ENGINE_STRATEGY_DEFAULTS['forex'].position_size_pct:.0f}% of virtual equity per position. "
        "Edit them under Strategy or in Settings."
    )


def ui_html(text: str) -> str:
    from html import escape

    return escape(text)


def render() -> None:
    engine_common.render_engine_page("forex", extra_context=_extra_context)
