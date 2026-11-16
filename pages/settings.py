"""Settings: demo account, per-engine strategies, data provider and safety notices."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import state
import ui
from data import market_data
from engines import all_engines, stocks
from pages.engine_common import strategy_form


def render() -> None:
    account = state.get_account()
    db = state.get_database()
    ui.page_header(
        "Settings",
        "Demo account configuration, per-engine strategy settings, data-provider preferences and the "
        "safety posture of this build.",
        tag="DEMO ONLY",
    )
    ui.demo_bar(right=f"Settings stored locally in SQLite · account #{account.id}")

    tab_account, tab_engines, tab_data, tab_safety = st.tabs(
        ["Demo account", "Engine strategies", "Data & provider", "Safety & roadmap"]
    )

    # -- demo account ------------------------------------------------------- #
    with tab_account:
        ui.section("Virtual account", "nothing here touches a real account")
        ui.show_table(pd.DataFrame([
            ("Account ID", str(account.id)),
            ("Account name", account.name),
            ("Created", account.created_at.replace("T", " ")),
            ("Starting virtual balance", ui.money(account.starting_balance)),
            ("Current cash", ui.money(account.cash)),
            ("Current equity", ui.money(account.equity())),
            ("Mode", "DEMO — virtual money only"),
        ], columns=["Field", "Value"]))

        ui.section("Starting balance", "resetting the account deletes simulated trades")
        new_balance = st.number_input(
            "Starting virtual balance (USD)", min_value=100.0, max_value=10_000_000.0,
            value=float(account.starting_balance), step=500.0, key="settings_start_balance",
        )
        confirm_reset = st.checkbox(
            "I understand this resets the demo account and deletes all simulated trades and snapshots",
            key="settings_confirm_reset",
        )
        if st.button("Apply starting balance", key="settings_apply_balance", disabled=not confirm_reset):
            problems = account.set_starting_balance(float(new_balance))
            if problems:
                for problem in problems:
                    st.error(problem)
            else:
                ui.flash(f"Demo account reset with a starting virtual balance of {ui.money(new_balance)}.")
                st.rerun()

        ui.section("Simulator defaults", "used for new manual simulated trades")
        with st.form("sim_defaults_form"):
            default_cost = st.number_input(
                "Default transaction cost (bps per side)", min_value=0.0, max_value=500.0,
                value=float(state.get_data_settings().get("default_cost_bps", config.DEFAULT_SIM_COST_BPS)),
                step=0.5, key="settings_default_cost",
            )
            submit_defaults = st.form_submit_button("Save simulator default")
        if submit_defaults:
            state.save_data_settings({"default_cost_bps": float(default_cost)})
            ui.flash(f"Default simulated cost set to {default_cost:.1f} bps per side.")
            st.rerun()

        st.caption(
            "The simulator never deducts notional from cash; it is a notional demo, not a margin model. "
            "Costs are charged on entry and exit, and realised P&L is net of both."
        )

    # -- engine strategies -------------------------------------------------- #
    with tab_engines:
        ui.section("Strategy configuration", "each engine keeps its own settings")
        st.caption(
            "These settings drive the analysis, the latest strategy state and every backtest for that "
            "engine. Defaults differ by market because volatility, cost and session structure differ."
        )
        engine_tabs = st.tabs([engine.title for engine in all_engines()])
        for tab, engine in zip(engine_tabs, all_engines()):
            with tab:
                st.markdown(f"**{engine.title}** — {engine.description}")
                strategy_form(engine.key, prefix="settings_")
                if engine.strategy_notes():
                    with st.expander("Why these defaults", expanded=False):
                        for note in engine.strategy_notes():
                            st.markdown(f"- {note}")

    # -- data & provider ---------------------------------------------------- #
    with tab_data:
        ui.section("Data provider", "free market data, with its limitations")
        status = market_data.provider_status()
        ui.show_table(pd.DataFrame([
            ("Provider", status["provider"]),
            ("Client installed", "Yes" if status["installed"] else "No"),
            ("Detail", status["detail"]),
            ("Offline sample fallback", "Enabled" if status["sample_fallback"] else "Disabled"),
            ("Cache TTL", f"{status['cache_ttl']} seconds"),
            ("Delay", "Free feeds may be delayed 15–20 minutes and can revise history"),
        ], columns=["Field", "Value"]))

        col1, col2 = st.columns(2)
        if col1.button("Test provider connection", key="settings_test_provider"):
            probe = market_data.get_price_history(
                "EURUSD=X", "5d", "1d", allow_sample=False, force_refresh=True
            )
            if probe.ok:
                st.success(
                    f"Provider reachable: {probe.bars} bars for EURUSD=X, last bar "
                    f"{probe.last_bar_time:%Y-%m-%d %H:%M} UTC (delayed feed)."
                )
            else:
                st.error(f"Provider unavailable: {probe.error}")
        if col2.button("Clear cached market data", key="settings_clear_cache", type="secondary"):
            market_data.clear_cache()
            stocks.clear_company_cache()
            ui.flash("Cached market data and company profiles cleared.")
            st.rerun()

        ui.section("Preferences")
        current = state.get_data_settings()
        with st.form("data_prefs_form"):
            allow_sample = st.checkbox(
                "Allow clearly-labelled offline sample data when the provider is unavailable",
                value=bool(current.get("allow_sample_data", True)),
                help="Sample data is synthetic and marked as such on every chart, table and analysis.",
                key="settings_allow_sample",
            )
            ttl = st.number_input(
                "Provider cache lifetime (seconds)", min_value=30, max_value=3600,
                value=int(current.get("cache_ttl", config.DATA_CACHE_TTL_SECONDS)), step=30,
                key="settings_ttl",
            )
            timeframes = list(config.TIMEFRAMES)
            timeframe = st.selectbox(
                "Default timeframe", timeframes,
                index=timeframes.index(current.get("timeframe", config.DEFAULT_TIMEFRAME))
                if current.get("timeframe") in timeframes else 0,
                key="settings_timeframe",
            )
            submit_prefs = st.form_submit_button("Save data preferences")
        if submit_prefs:
            state.save_data_settings({
                "allow_sample_data": bool(allow_sample),
                "cache_ttl": int(ttl),
                "timeframe": timeframe,
            })
            market_data.clear_cache()
            ui.flash("Data preferences saved.")
            st.rerun()

        ui.notice(
            "<strong>Data honesty.</strong> MNZ never invents live prices. When the provider fails and "
            "sample data is enabled, synthetic rows are labelled SAMPLE DATA everywhere they appear. "
            "When it fails and sample data is disabled, the app shows an explicit error instead.",
        )

    # -- safety & roadmap --------------------------------------------------- #
    with tab_safety:
        ui.section("This build is demo-only", "hard-coded, not a toggle")
        ui.show_table(pd.DataFrame([
            ("Live broker connection", "None — no broker API is used"),
            ("Order execution", "Disabled and unimplemented"),
            ("Brokerage credentials", "Never requested, never stored"),
            ("Payments or subscriptions", "Not implemented"),
            ("Real money", "Never involved"),
            ("Virtual starting balance", ui.money(config.DEMO_STARTING_BALANCE)),
            ("Automated execution flag", f"LIVE_EXECUTION_ENABLED = {config.LIVE_EXECUTION_ENABLED}"),
            ("Demo-only flag", f"DEMO_ONLY = {config.DEMO_ONLY}"),
        ], columns=["Control", "Status"]))
        ui.notice(config.LIVE_EXECUTION_NOTICE, "warn")

        ui.section("Planned commercial architecture", "designed for, deliberately not built")
        ui.show_table(pd.DataFrame(
            [(key, value) for key, value in config.FUTURE_COMMERCIAL.items()],
            columns=["Capability", "Status and design intent"],
        ))
        st.caption(
            "The database is account-scoped and settings are namespaced, so customer accounts, per-user "
            "settings, subscription entitlements and licensing could be added without redesigning storage. "
            "Authentication, billing and licensing are not implemented."
        )

        ui.section("Disclaimer")
        ui.notice(config.DISCLAIMER, "warn")
        st.caption(
            f"{config.BRAND} · {config.APP_NAME} v{config.VERSION} · "
            "Python, Streamlit, Pandas, Plotly, SQLite, yfinance."
        )

    ui.footer()
