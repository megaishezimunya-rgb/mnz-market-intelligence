"""Shared renderer for the five market-engine pages.

Each engine page supplies its own market-context block; the analysis flow,
charts, strategy settings and data-provenance handling are identical so users
learn the interface once.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd
import streamlit as st

import config
import state
import ui
from analysis import backtesting, indicators, market_analyst
from data import market_data
from engines import get_engine
from engines.base import EngineContext
from data.market_data import PriceData

ExtraRenderer = Callable[[PriceData, config.StrategySettings, EngineContext], None]


# --------------------------------------------------------------------------- #
# Controls
# --------------------------------------------------------------------------- #
def timeframe_selector(key_prefix: str = "global") -> str:
    """Global timeframe selector, persisted in settings."""
    options = list(config.TIMEFRAMES)
    widget_key = f"{key_prefix}_timeframe"
    current = state.current_timeframe()
    if st.session_state.get(widget_key) not in options:
        st.session_state[widget_key] = current
    label = st.selectbox(
        "Timeframe", options, key=widget_key,
        help="Longer histories are better for moving averages; intraday intervals are provider-limited.",
    )
    if label != state.get_data_settings().get("timeframe"):
        state.save_data_settings({"timeframe": label})
    return label


def load_data(engine_key: str, symbol: str, timeframe: str | None = None) -> PriceData:
    """Fetch history for one instrument using the global settings."""
    label = timeframe or state.current_timeframe()
    period, interval = config.TIMEFRAMES.get(label, config.TIMEFRAMES[config.DEFAULT_TIMEFRAME])
    return market_data.get_price_history(
        symbol, period, interval, allow_sample=state.allow_sample_data()
    )


def instrument_selector(engine_key: str, *, search_enabled: bool | None = None) -> tuple[str, str]:
    """Instrument picker with optional provider ticker search. Returns (symbol, label)."""
    engine = get_engine(engine_key)
    instruments = engine.instruments()
    search_enabled = hasattr(engine, "search") if search_enabled is None else search_enabled

    if search_enabled and hasattr(engine, "search"):
        query = st.text_input(
            "Ticker search", key=f"{engine_key}_search",
            placeholder="Search a symbol or company name…",
            help="Searches the configured universe first, then the provider's symbol index.",
        )
        if query.strip():
            matches = engine.search(query)
            if matches:
                instruments = matches
            else:
                st.caption(f"No provider match for “{query}”. Showing the configured {engine.title} universe.")

    symbols = [item.symbol for item in instruments]
    labels = {item.symbol: item.label for item in instruments}
    widget_key = f"{engine_key}_symbol"
    if st.session_state.get(widget_key) not in symbols:
        st.session_state[widget_key] = symbols[0]
    symbol = st.selectbox(
        "Instrument", symbols, key=widget_key,
        format_func=lambda value: f"{value} — {labels.get(value, value)}",
    )
    return symbol, labels.get(symbol, symbol)


# --------------------------------------------------------------------------- #
# Strategy settings form
# --------------------------------------------------------------------------- #
def strategy_form(engine_key: str, *, prefix: str = "") -> None:
    """Editable per-engine strategy configuration, persisted to SQLite."""
    engine = get_engine(engine_key)
    current = state.get_settings(engine_key)
    key = f"{prefix}{engine_key}"

    with st.form(f"strategy_form_{key}"):
        st.caption(f"{engine.title} strategy configuration — saved for this engine only.")
        col1, col2, col3 = st.columns(3)
        fast_ma = col1.number_input("Fast MA (bars)", min_value=2, max_value=400,
                                    value=int(current.fast_ma), step=1, key=f"{key}_fast")
        slow_ma = col2.number_input("Slow MA (bars)", min_value=3, max_value=500,
                                    value=int(current.slow_ma), step=1, key=f"{key}_slow")
        rsi_period = col3.number_input("RSI period", min_value=2, max_value=100,
                                       value=int(current.rsi_period), step=1, key=f"{key}_rsi_p")

        col1, col2, col3 = st.columns(3)
        rsi_buy_max = col1.number_input("RSI entry ceiling", min_value=0.0, max_value=100.0,
                                        value=float(current.rsi_buy_max), step=1.0, key=f"{key}_rsi_buy",
                                        help=("The long-entry RSI state arms below this level and stays armed "
                                              "until RSI reaches the exit level, so entries do not require "
                                              "RSI to be below the ceiling on the exact signal bar."))
        rsi_sell_min = col2.number_input("RSI exit level", min_value=0.0, max_value=100.0,
                                         value=float(current.rsi_sell_min), step=1.0, key=f"{key}_rsi_sell")
        position_size = col3.number_input("Position size (% of equity)", min_value=1.0, max_value=100.0,
                                          value=float(current.position_size_pct), step=5.0, key=f"{key}_size")

        col1, col2, col3 = st.columns(3)
        cost_bps = col1.number_input("Transaction cost (bps, per side)", min_value=0.0, max_value=500.0,
                                     value=float(current.cost_bps), step=0.5, key=f"{key}_cost")
        max_hold = col2.number_input("Time stop (bars, 0 = off)", min_value=0, max_value=2000,
                                     value=int(current.max_hold_bars), step=1, key=f"{key}_hold")
        col3.write("")
        use_rsi = col3.checkbox("Use RSI entry filter", value=bool(current.use_rsi_filter), key=f"{key}_use_rsi")
        allow_short = st.checkbox(
            "Allow simulated short positions", value=bool(current.allow_short), key=f"{key}_short",
            help="Short trades are simulated only. This does not enable live execution.",
        )

        save_col, reset_col, _ = st.columns([1, 1, 2])
        save = save_col.form_submit_button("Save strategy")
        reset = reset_col.form_submit_button("Reset to engine defaults")

    if reset:
        state.reset_settings(engine_key)
        ui.flash(f"{engine.title} strategy reset to its engine defaults.")
        st.rerun()
    if save:
        updated = config.StrategySettings(
            fast_ma=int(fast_ma), slow_ma=int(slow_ma), rsi_period=int(rsi_period),
            rsi_buy_max=float(rsi_buy_max), rsi_sell_min=float(rsi_sell_min),
            use_rsi_filter=bool(use_rsi), allow_short=bool(allow_short),
            cost_bps=float(cost_bps), position_size_pct=float(position_size),
            max_hold_bars=int(max_hold),
        )
        problems = state.save_settings(engine_key, updated)
        if problems:
            for problem in problems:
                st.error(problem)
        else:
            ui.flash(f"{engine.title} strategy saved.")
            st.rerun()


def settings_table(settings: config.StrategySettings) -> pd.DataFrame:
    return pd.DataFrame([
        ("Fast moving average", f"{settings.fast_ma} bars"),
        ("Slow moving average", f"{settings.slow_ma} bars"),
        ("RSI period", f"{settings.rsi_period} bars"),
        ("RSI entry ceiling", f"{settings.rsi_buy_max:.0f}"),
        ("RSI exit level", f"{settings.rsi_sell_min:.0f}"),
        ("RSI entry filter", "On" if settings.use_rsi_filter else "Off"),
        ("Short selling", "Enabled" if settings.allow_short else "Disabled"),
        ("Simulated cost", f"{settings.cost_bps:.1f} bps per side"),
        ("Position size", f"{settings.position_size_pct:.0f}% of virtual equity"),
        ("Time stop", f"{settings.max_hold_bars} bars" if settings.max_hold_bars else "Off"),
    ], columns=["Setting", "Value"])


def events_table(events: list[dict]) -> None:
    if not events:
        ui.notice("No event information is available for this engine.")
        return
    ui.html_table(pd.DataFrame(events).rename(columns={
        "name": "Event", "schedule": "Typical schedule (UTC)", "note": "Why it matters",
    }), min_width=560)


# --------------------------------------------------------------------------- #
# Main page renderer
# --------------------------------------------------------------------------- #
def render_engine_page(engine_key: str, *, extra_context: ExtraRenderer | None = None,
                       search_enabled: bool | None = None) -> None:
    engine = get_engine(engine_key)
    account = state.get_account()
    marks: dict[str, float] = {}

    ui.page_header(
        f"{engine.title} Engine",
        engine.description + " Engine-specific settings, costs and event context are applied.",
        tag="DEMO MODE",
    )
    ui.demo_bar(right=f"Virtual equity {ui.money(account.equity(marks))} · virtual only")

    controls, side = st.columns([2.6, 1.3], gap="large")
    with controls:
        symbol, label = instrument_selector(engine_key, search_enabled=search_enabled)
    with side:
        timeframe = timeframe_selector(engine_key)
        if st.button("Refresh data", key=f"{engine_key}_refresh", type="secondary"):
            market_data.clear_cache()
            st.rerun()

    settings = state.get_settings(engine_key)
    data = load_data(engine_key, symbol, timeframe)

    if data.ok and data.last_price:
        marks[symbol] = data.last_price

    # -- headline numbers --------------------------------------------------- #
    if not data.ok:
        ui.empty_state(
            f"{label} could not be loaded: {data.error}",
            "Try another instrument or timeframe, refresh, or enable offline sample data in Settings.",
        )
    else:
        snap = indicators.snapshot(data.frame, fast=settings.fast_ma, slow=settings.slow_ma,
                                   rsi_period=settings.rsi_period)
        change = None
        if data.bars >= 2:
            prev = float(data.frame["Close"].iloc[-2])
            change = (float(data.frame["Close"].iloc[-1]) / prev - 1) * 100 if prev else None
        ui.kpi_row([
            {"label": "Last price", "value": ui.price_fmt(data.last_price),
             "note": f"{label} · {data.interval} bars"},
            {"label": "Latest bar change", "value": ui.pct(change, signed=True), "trend": (change or 0)},
            {"label": "Trend structure", "value": snap.trend_label,
             "note": f"MA {settings.fast_ma}/{settings.slow_ma}"},
            {"label": "RSI", "value": ui.number(snap.rsi, 1),
             "note": f"ATR {ui.pct(snap.atr_pct)} of price"},
        ])

        ui.section("Price structure", data.describe())
        overlays = {
            f"MA {settings.fast_ma}": indicators.sma(data.frame["Close"], settings.fast_ma),
            f"MA {settings.slow_ma}": indicators.sma(data.frame["Close"], settings.slow_ma),
        }
        ui.show_chart(ui.price_chart(data.frame, overlays=overlays, is_sample=data.is_sample))
        ui.source_line(data)
        if data.is_sample:
            ui.notice(
                "<strong>SAMPLE DATA.</strong> The live provider was unavailable, so this screen is "
                "showing a synthetic offline series. No price, indicator or label here reflects the real market.",
                "warn",
            )

    # -- analysis and detail ------------------------------------------------ #
    context = engine.context(data, settings)
    report = market_analyst.analyze(engine_key, data, settings, context=context,
                                    engine_title=f"{engine.title} engine")

    tab_analyst, tab_momentum, tab_context, tab_strategy = st.tabs(
        ["AI Analyst", "Momentum & volatility", "Market context", "Strategy"]
    )

    with tab_analyst:
        ui.render_report(report)

    with tab_momentum:
        if data.ok:
            close = data.frame["Close"]
            ui.show_chart(ui.momentum_chart(
                data.frame,
                indicators.rsi(close, settings.rsi_period),
                indicators.macd(close),
            ))
            snap = indicators.snapshot(data.frame, fast=settings.fast_ma, slow=settings.slow_ma,
                                       rsi_period=settings.rsi_period)
            fact_rows = pd.DataFrame([
                ("MACD histogram", ui.number(snap.macd_hist, 4)),
                ("MACD state", snap.macd_state),
                ("20-bar rate of change", ui.pct(snap.roc_20, signed=True)),
                ("Annualised volatility", ui.pct(snap.annual_vol)),
                ("Bollinger width", ui.pct(snap.bb_width)),
                ("Volume vs 50-bar average",
                 f"{snap.volume_ratio:.2f}x" if snap.volume_ratio == snap.volume_ratio else "n/a"),
                ("Volatility regime", snap.volatility_label),
            ], columns=["Measure", "Reading"])
            ui.show_table(fact_rows)
            if snap.volatility_label in {"High", "Elevated"}:
                ui.notice("Volatility is elevated. Simulated position sizes should be smaller to reflect wider ranges.", "warn")
        else:
            ui.empty_state("Indicators cannot be computed without price history.")

    with tab_context:
        ui.section("Market context", engine.title)
        ui.render_context_table(context.facts)
        if context.events:
            ui.section("Event awareness", "recurring windows — not a live calendar")
            events_table(context.events)
        if extra_context is not None:
            extra_context(data, settings, context)
        if context.notes:
            ui.section("Notes")
            for note in context.notes:
                st.markdown(f"- {note}")
        if context.warnings:
            for warning in context.warnings:
                ui.notice(ui_html_escape(warning), "warn")
        ui.notice(
            "Event schedules are recurring heuristics, not a live economic calendar. "
            "Always confirm release times with an official source.",
        )

    with tab_strategy:
        ui.section("Current strategy", f"{engine.title} defaults and overrides")
        ui.show_table(settings_table(settings))
        signal = backtesting.latest_signal(data.frame, settings) if data.ok else {
            "state": "No data", "detail": "Price history unavailable.", "reason": "n/a"
        }
        ui.notice(
            f"<strong>Mechanical strategy state: {ui_html_escape(signal['state'])}.</strong> "
            f"{ui_html_escape(signal['detail'])}<br>{ui_html_escape(signal['reason'])}"
        )
        st.caption("This is a mechanical rule output, not a recommendation or an order.")
        if engine.strategy_notes():
            with st.expander("Why this engine uses these defaults", expanded=False):
                for note in engine.strategy_notes():
                    st.markdown(f"- {note}")
        ui.section("Edit strategy settings", "saved per engine")
        strategy_form(engine_key, prefix="page_")
        if st.button("Open Strategy Testing", key=f"{engine_key}_to_backtest", type="secondary"):
            state.goto("Strategy Testing")

    ui.footer()


def ui_html_escape(text: str) -> str:
    from html import escape

    return escape(str(text))
