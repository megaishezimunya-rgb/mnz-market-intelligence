"""AI Market Analyst page: plain-language, explainable multi-market analysis."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import state
import ui
from analysis import market_analyst
from engines import all_engines, get_engine
from pages.engine_common import instrument_selector, load_data, timeframe_selector


def _weights_table() -> pd.DataFrame:
    components = ["trend", "momentum", "rsi", "volatility", "volume", "session"]
    rows = []
    for engine_key, weights in config.ANALYST_WEIGHTS.items():
        row = {"Engine": config.ENGINE_LABELS[engine_key]}
        for component in components:
            value = weights.get(component, 0.0)
            row[component.replace("rsi", "RSI").capitalize()] = f"{value * 100:.0f}%"
        rows.append(row)
    return pd.DataFrame(rows)


def _cross_market(timeframe: str) -> tuple[pd.DataFrame, list]:
    rows, reports = [], []
    for engine in all_engines():
        settings = state.get_settings(engine.key)
        instrument = engine.instruments()[0]
        data = load_data(engine.key, instrument.symbol, timeframe)
        context = engine.context(data, settings)
        report = market_analyst.analyze(engine.key, data, settings, context=context,
                                        engine_title=f"{engine.title} engine")
        reports.append(report)
        rows.append({
            "Market": engine.title,
            "Primary instrument": instrument.label,
            "Symbol": instrument.symbol,
            "Price": report.price,
            "Label": report.label,
            "Conviction %": report.confidence,
            "Trend": report.trend,
            "Data": "Sample" if report.is_sample else report.data_quality,
            "Last bar (UTC)": data.last_bar_time.strftime("%Y-%m-%d %H:%M") if data.last_bar_time else "—",
        })
    return pd.DataFrame(rows), reports


def render() -> None:
    ui.page_header(
        "AI Market Analyst",
        "Rule-based analysis in plain language: what the indicators show, which trend is in place, "
        "why a label was produced and how reliable the underlying data is.",
        tag="EDUCATIONAL",
    )
    ui.demo_bar()

    col1, col2, col3 = st.columns([1.1, 1.9, 1.2], gap="large")
    with col1:
        engine_key = st.selectbox(
            "Market engine", list(config.ENGINE_LABELS),
            format_func=lambda key: config.ENGINE_LABELS[key],
            key="analyst_engine",
        )
    with col2:
        symbol, label = instrument_selector(engine_key, search_enabled=False)
    with col3:
        timeframe = timeframe_selector("analyst")

    engine = get_engine(engine_key)
    settings = state.get_settings(engine_key)
    data = load_data(engine_key, symbol, timeframe)
    context = engine.context(data, settings)
    report = market_analyst.analyze(engine_key, data, settings, context=context,
                                    engine_title=f"{engine.title} engine")

    ui.section(f"{label} analysis", f"{engine.title} engine · {timeframe}")
    ui.render_report(report)
    ui.source_line(data)

    # -- cross-market view -------------------------------------------------- #
    ui.section("Cross-market view", "primary instrument of every engine")
    table, reports = _cross_market(timeframe)
    if table.empty:
        ui.empty_state("No market data is available for a cross-market view.")
    else:
        view = market_analyst.overall_market_view(reports)
        ui.notice(f"<strong>{view['headline']}.</strong> {view['detail']}")
        display = table.copy()
        display["Price"] = display["Price"].map(lambda value: ui.price_fmt(value) if pd.notna(value) else "—")
        ui.show_table(display)

        score_rows = pd.DataFrame([
            {"Market": row["Market"], "Score": rep.score} for row, rep in zip(table.to_dict("records"), reports)
        ])
        if not score_rows.empty:
            ui.show_chart(ui.bar_chart(score_rows, "Market", "Score", horizontal=True, height=250,
                                       title="Weighted score by market"))

        missing = [rep for rep in reports if rep.label == "NO DATA"]
        if missing:
            ui.notice(
                f"<strong>Missing data.</strong> {len(missing)} market(s) could not be analysed: "
                + ", ".join(rep.symbol for rep in missing),
                "warn",
            )

    # -- methodology -------------------------------------------------------- #
    ui.section("How to read the labels", "educational, not advice")
    ui.show_table(pd.DataFrame([
        ("BUY BIAS", "Weighted evidence leans constructive.", "Not an instruction to buy; risk is not assessed."),
        ("SELL BIAS", "Weighted evidence leans defensive.", "Not a short recommendation; risk is not assessed."),
        ("WAIT", "No clear edge, or signals conflict.", "Absence of edge, not a prediction of reversal."),
        ("NO DATA", "Not enough history or no provider data.", "MNZ never fills the gap with invented numbers."),
        ("Conviction %", "Strength and agreement of the evidence, adjusted for data quality.",
         "Capped at 95%; sample data caps it at about 40%."),
    ], columns=["Label", "Meaning", "Important limitation"]))

    ui.section("Engine weights", "each market is weighted differently")
    ui.show_table(_weights_table())
    st.caption(
        "Trend, momentum, RSI and volume drive direction. Volatility and session liquidity adjust "
        "conviction and risk commentary rather than direction."
    )

    ui.section("Data sources and timestamps", "what this page actually used")
    source_rows = pd.DataFrame([
        {
            "Market": rep.engine.title(),
            "Symbol": rep.symbol,
            "Bars": rep.bars,
            "Quality": "Sample" if rep.is_sample else rep.data_quality,
            "Source": rep.source,
            "Generated": rep.timestamp,
        }
        for rep in reports
    ])
    ui.show_table(source_rows)
    ui.notice(
        "Free market data can be delayed, revised or missing. Sample rows are synthetic and exist only "
        "so the interface remains explorable when the provider is unreachable.",
    )
    ui.notice(config.DISCLAIMER, "warn")
    ui.footer()
