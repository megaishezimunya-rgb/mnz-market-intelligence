"""Overview dashboard: market selection, data availability, trends and demo performance."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import state
import ui
from analysis import market_analyst
from data import market_data
from engines import get_engine
from pages.engine_common import load_data, timeframe_selector
from simulator import portfolio


def render() -> None:
    account = state.get_account()
    ui.page_header(
        "Overview",
        "A single view of every configured market: what data is available, which instruments are "
        "selected, the current analysis summary and your virtual account.",
        tag="DEMO MODE",
    )
    ui.demo_bar(right=f"Virtual equity {ui.money(account.equity())} · virtual only")

    # -- market selection --------------------------------------------------- #
    ui.section("Market selection", "choose the markets to monitor")
    col1, col2 = st.columns([3, 1], gap="large")
    with col1:
        markets = st.multiselect(
            "Markets",
            options=list(config.ENGINE_LABELS),
            default=[key for key in state.get_data_settings().get("overview_markets", []) if key in config.ENGINE_LABELS]
            or list(config.ENGINE_LABELS),
            format_func=lambda key: config.ENGINE_LABELS[key],
            key="overview_markets",
        )
    with col2:
        per_market = st.number_input("Instruments per market", min_value=1, max_value=3, value=1, step=1,
                                     key="overview_per_market",
                                     help="More instruments means more provider requests.")
    if markets != state.get_data_settings().get("overview_markets"):
        state.save_data_settings({"overview_markets": markets})

    timeframe = timeframe_selector("overview")

    if not markets:
        ui.empty_state("No markets selected.", "Choose at least one market above to build the overview.")
        ui.footer()
        return

    # -- data collection ---------------------------------------------------- #
    rows: list[dict] = []
    reports = []
    marks: dict[str, float] = {}
    availability: list[dict] = []

    for market_key in markets:
        engine = get_engine(market_key)
        settings = state.get_settings(market_key)
        for instrument in engine.instruments()[: int(per_market)]:
            data = load_data(market_key, instrument.symbol, timeframe)
            context = engine.context(data, settings)
            report = market_analyst.analyze(market_key, data, settings, context=context,
                                            engine_title=f"{engine.title} engine")
            reports.append(report)
            if data.ok and data.last_price:
                marks[instrument.symbol] = data.last_price
            availability.append({
                "Market": engine.title,
                "Instrument": instrument.label,
                "Symbol": instrument.symbol,
                "Interval": data.interval,
                "Bars": data.bars,
                "Last bar (UTC)": data.last_bar_time.strftime("%Y-%m-%d %H:%M") if data.last_bar_time else "—",
                "Source": "Sample data (offline)" if data.is_sample else ("Yahoo Finance" if data.ok else "Unavailable"),
                "Status": data.status_note(),
            })
            rows.append({
                "Market": engine.title,
                "Instrument": instrument.label,
                "Symbol": instrument.symbol,
                "Price": data.last_price,
                "Change %": report.change_pct,
                "Trend": report.trend,
                "Analyst label": report.label,
                "Conviction %": report.confidence,
                "Data": "Sample" if report.is_sample else report.data_quality,
            })

    # -- virtual account ---------------------------------------------------- #
    portfolio.record_snapshot(state.get_database(), account, marks, note="overview")
    summary = portfolio.portfolio_summary(account, marks)
    ui.kpi_row([
        {"label": "Virtual balance", "value": ui.money(summary["equity"]),
         "note": f"cash {ui.money(summary['cash'])}"},
        {"label": "Total simulated P&L", "value": ui.money(summary["total_pnl"]),
         "note": ui.pct(summary["total_return_pct"], signed=True), "trend": summary["total_return_pct"]},
        {"label": "Open / closed positions", "value": f"{summary['open_positions']} / {summary['closed_positions']}",
         "note": f"exposure {ui.pct(summary['exposure_pct'])} of equity"},
        {"label": "Max drawdown", "value": ui.pct(summary["max_drawdown_pct"]),
         "note": f"{summary['drawdown_points']} equity snapshots"},
    ])

    # -- market data availability ------------------------------------------- #
    ui.section("Available market data", "provenance, freshness and coverage")
    availability_frame = pd.DataFrame(availability)
    ui.show_table(availability_frame)

    failures = [row for row in availability if row["Source"] == "Unavailable"]
    sample_rows = [row for row in availability if row["Source"] == "Sample data (offline)"]
    if sample_rows:
        ui.notice(
            f"<strong>SAMPLE DATA.</strong> {len(sample_rows)} instrument(s) are showing synthetic offline "
            "data because the live provider was unavailable. Nothing on this page is real market data for "
            "those rows.",
            "warn",
        )
    if failures:
        ui.notice(
            f"<strong>Missing data.</strong> {len(failures)} instrument(s) could not be loaded. "
            "They are excluded from analysis rather than estimated.",
            "warn",
        )
    stale = [row for row in availability if "Delayed" in str(row["Status"])]
    if stale:
        st.caption(f"{len(stale)} instrument(s) report a delayed or stale latest bar.")

    if not reports:
        ui.footer()
        return

    view = market_analyst.overall_market_view(reports)
    ui.section("Analysis summaries", view["headline"])
    ui.notice(f"<strong>{view['headline']}.</strong> {view['detail']}")

    analysis_frame = pd.DataFrame(rows)
    display = analysis_frame.copy()
    display["Price"] = display["Price"].map(lambda value: ui.price_fmt(value) if pd.notna(value) else "—")
    display["Change %"] = display["Change %"].map(lambda value: ui.pct(value, signed=True) if pd.notna(value) else "—")
    ui.show_table(display)

    score_rows = pd.DataFrame([
        {"Market": report_row["Market"], "Score": report.score}
        for report, report_row in zip(reports, rows)
    ])
    if not score_rows.empty:
        grouped = score_rows.groupby("Market", as_index=False)["Score"].mean()
        ui.show_chart(ui.bar_chart(grouped, "Market", "Score", horizontal=True, height=240,
                                   title="Weighted market score (−1 defensive · +1 constructive)"))

    col_a, col_b, col_c = st.columns(3)
    if col_a.button("Open AI Market Analyst", type="secondary"):
        state.goto("AI Market Analyst")
    if col_b.button("Open Demo Trading", type="secondary"):
        state.goto("Demo Trading")
    if col_c.button("Open Performance Reports", type="secondary"):
        state.goto("Performance Reports")

    # -- demo performance --------------------------------------------------- #
    ui.section("Demo performance", "recorded virtual equity")
    curve = portfolio.equity_curve(account)
    ui.show_chart(ui.equity_chart(curve, account.starting_balance, height=280))
    stats = portfolio.performance_stats(account)
    if stats.get("available"):
        st.caption(
            f"{stats['snapshots']} snapshots · first {stats['first']:%Y-%m-%d %H:%M} · "
            f"last {stats['last']:%Y-%m-%d %H:%M} · {stats['note']}"
        )
    else:
        st.caption(stats["note"] + " Visit Demo Trading to record more.")

    ui.footer()
