"""Stocks page: equity analysis, company fundamentals and earnings awareness."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from pages import engine_common


def _format_market_cap(value) -> str:
    if not isinstance(value, (int, float)) or value != value:
        return "n/a"
    if value >= 1e12:
        return f"${value / 1e12:,.2f}T"
    if value >= 1e9:
        return f"${value / 1e9:,.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:,.1f}M"
    return f"${value:,.0f}"


def _format_ratio(value, digits: int = 2) -> str:
    if not isinstance(value, (int, float)) or value != value:
        return "n/a"
    return f"{value:,.{digits}f}"


def _extra_context(data, settings, context) -> None:
    profile = context.extras.get("fundamentals") or {}
    ui.section("Company fundamentals", "provider data, when available")
    if profile.get("available"):
        rows = [
            ("Company", profile.get("name") or "—"),
            ("Sector", profile.get("sector") or "n/a"),
            ("Industry", profile.get("industry") or "n/a"),
            ("Exchange", profile.get("exchange") or "n/a"),
            ("Currency", profile.get("currency") or "n/a"),
            ("Market capitalisation", _format_market_cap(profile.get("market_cap"))),
            ("Trailing P/E", _format_ratio(profile.get("trailing_pe"))),
            ("Forward P/E", _format_ratio(profile.get("forward_pe"))),
            ("Profit margin", ui.pct((profile.get("profit_margin") or 0) * 100)
             if isinstance(profile.get("profit_margin"), (int, float)) else "n/a"),
            ("Dividend yield", ui.pct((profile.get("dividend_yield") or 0) * 100)
             if isinstance(profile.get("dividend_yield"), (int, float)) else "n/a"),
            ("Beta (5y)", _format_ratio(profile.get("beta"))),
            ("52-week high", _format_ratio(profile.get("week52_high"))),
            ("52-week low", _format_ratio(profile.get("week52_low"))),
            ("Average volume", _format_ratio(profile.get("avg_volume"), 0)),
            ("Source", profile.get("source", "Yahoo Finance")),
        ]
        ui.html_table(pd.DataFrame(rows, columns=["Field", "Value"]), min_width=480)
        st.caption("Fundamentals are reported by the provider and can lag company filings.")
    else:
        ui.notice(
            f"<strong>Fundamentals unavailable.</strong> {ui_html(profile.get('error', 'No company profile returned.'))}"
            "<br>MNZ does not fabricate financial data; the price-based analysis above is unaffected."
        )

    earnings = context.extras.get("earnings") or {}
    ui.section("Earnings awareness", "event risk for equities")
    if earnings.get("available"):
        facts = [("Next earnings date (provider)", earnings.get("next_date") or "not published")]
        if earnings.get("eps_estimate") is not None:
            facts.append(("Consensus EPS estimate", str(earnings.get("eps_estimate"))))
        ui.show_table(pd.DataFrame(facts, columns=["Field", "Value"]))
        history = earnings.get("history") or []
        if history:
            ui.show_table(pd.DataFrame(history).rename(columns={
                "date": "Date", "eps_estimate": "EPS estimate",
                "reported": "Reported EPS", "surprise_pct": "Surprise %",
            }).head(6))
        st.caption("Earnings dates come from the provider and can change. Treat them as indicative.")
        if earnings.get("partial_error"):
            st.caption(earnings["partial_error"])
    else:
        ui.notice(
            f"<strong>Earnings data unavailable.</strong> {ui_html(earnings.get('error', 'Not published by the provider.'))}"
        )


def ui_html(text: str) -> str:
    from html import escape

    return escape(str(text))


def render() -> None:
    engine_common.render_engine_page("stocks", extra_context=_extra_context, search_enabled=True)
