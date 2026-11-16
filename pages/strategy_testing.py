"""Strategy Testing: per-engine backtests with costs, drawdown and period comparison."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import config
import state
import ui
from analysis import backtesting
from analysis.market_analyst import AnalystReport  # noqa: F401  (type context only)
from engines import get_engine
from pages.engine_common import instrument_selector, load_data, strategy_form, timeframe_selector


def render() -> None:
    account = state.get_account()
    ui.page_header(
        "Strategy Testing",
        "Backtest each engine's own strategy on historical bars, with simulated transaction costs and "
        "comparisons across different market periods. Research only — never a forecast.",
        tag="RESEARCH",
    )
    ui.demo_bar()

    col1, col2, col3 = st.columns([1.1, 1.9, 1.2], gap="large")
    with col1:
        engine_key = st.selectbox(
            "Market engine", list(config.ENGINE_LABELS),
            format_func=lambda key: config.ENGINE_LABELS[key],
            key="bt_engine",
        )
    with col2:
        symbol, label = instrument_selector(engine_key, search_enabled=False)
    with col3:
        timeframe = timeframe_selector("bt")

    engine = get_engine(engine_key)
    settings = state.get_settings(engine_key)

    with st.expander("Strategy settings (applies to this engine everywhere)", expanded=False):
        strategy_form(engine_key, prefix="bt_")
        st.caption("Changing settings does not change a result you have already run; run again to compare.")

    problems = settings.validate()
    if problems:
        for problem in problems:
            st.error(problem)
        ui.footer()
        return

    run_col, note_col = st.columns([1, 3])
    run_clicked = run_col.button("Run backtest", key="bt_run")
    note_col.caption(
        f"Engine: {engine.title} · MAs {settings.fast_ma}/{settings.slow_ma} · RSI {settings.rsi_period} · "
        f"cost {settings.cost_bps:.1f} bps per side · size {settings.position_size_pct:.0f}%"
    )

    if run_clicked:
        data = load_data(engine_key, symbol, timeframe)
        if not data.ok:
            st.session_state["bt_payload"] = None
            st.session_state["bt_error"] = data.error
        else:
            result = backtesting.run_backtest(
                data.frame, settings, symbol=symbol, market=engine_key,
                initial_balance=account.starting_balance, source=data.source_label,
                is_sample=data.is_sample,
            )
            comparison = backtesting.compare_periods(
                data.frame, settings, symbol=symbol, market=engine_key,
                initial_balance=account.starting_balance, source=data.source_label,
                is_sample=data.is_sample,
            )
            st.session_state["bt_payload"] = {
                "result": result,
                "comparison": comparison,
                "timeframe": timeframe,
                "ran_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                "engine": engine_key,
                "symbol": symbol,
                "data": data,
            }
            st.session_state["bt_error"] = None

    payload = st.session_state.get("bt_payload")
    if not payload:
        if st.session_state.get("bt_error"):
            ui.empty_state(f"Backtest could not run: {st.session_state['bt_error']}",
                           "Try another instrument or timeframe.")
        else:
            ui.notice("Choose an engine, instrument and timeframe, then run a backtest to see results.")
            ui.notice(
                "Historical results do not guarantee future performance. Simulated backtests ignore "
                "slippage beyond the cost assumption, financing, taxes and liquidity constraints.",
                "warn",
            )
        ui.footer()
        return

    result: backtesting.BacktestResult = payload["result"]
    comparison: pd.DataFrame = payload["comparison"]
    data = payload["data"]
    if not result.ok:
        for warning in result.warnings:
            ui.notice(warning, "warn")
        ui.footer()
        return

    ui.section(
        f"{payload['symbol']} backtest",
        f"{payload['ran_at']} · {payload['timeframe']} · {payload['engine'].title()} engine",
    )
    ui.source_line(data, extra=f"run at {payload['ran_at']}")

    m = result.metrics
    ui.kpi_row([
        {"label": "Total simulated return", "value": ui.pct(m["total_return_pct"], signed=True),
         "trend": m["total_return_pct"]},
        {"label": "Maximum drawdown", "value": ui.pct(m["max_drawdown_pct"])},
        {"label": "Win rate", "value": ui.pct(m["win_rate"], 1),
         "note": f"{m['num_trades']} simulated trades"},
        {"label": "Final equity", "value": ui.money(m["final_equity"]),
         "note": f"from {ui.money(result.initial_balance)}"},
    ])
    ui.kpi_row([
        {"label": "Buy & hold (same bars)", "value": ui.pct(m["buy_hold_return_pct"], signed=True)},
        {"label": "Total simulated costs", "value": ui.money(m["total_costs"]),
         "note": f"{result.settings.cost_bps:.1f} bps per side"},
        {"label": "Time in market", "value": ui.pct(m["exposure_pct"], 1)},
        {"label": "Profit factor",
         "value": "n/a" if not isinstance(m["profit_factor"], (int, float)) or m["profit_factor"] != m["profit_factor"]
         else ("∞" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"),
         "note": f"avg trade {ui.pct(m['avg_trade_pct'], signed=True)}"},
    ])

    if result.is_sample:
        ui.notice(
            "<strong>SAMPLE DATA.</strong> This backtest ran on a synthetic offline series. The numbers "
            "demonstrate the mechanics and say nothing about real markets.",
            "warn",
        )

    chart_col, dd_col = st.columns([1.6, 1], gap="large")
    with chart_col:
        ui.section("Simulated equity", "initial balance to final equity")
        ui.show_chart(ui.equity_chart(
            pd.DataFrame({"ts": result.equity_curve.index, "equity": result.equity_curve.to_numpy()}),
            result.initial_balance, height=300,
        ))
    with dd_col:
        ui.section("Drawdown", "peak to trough")
        dd = result.equity_curve / result.equity_curve.cummax() - 1
        ui.show_chart(ui.drawdown_chart(pd.DataFrame({
            "ts": result.equity_curve.index, "drawdown_pct": dd.to_numpy() * 100,
        }), height=300))

    ui.section("Result summary", "all figures are simulated")
    ui.show_table(result.metrics_frame())

    ui.section("Comparison across market periods", "same strategy, different windows")
    ui.show_table(comparison)
    st.caption(
        "Windows shorter than the strategy's warm-up requirement are reported as insufficient rather "
        "than filled with a guess. Different periods stress-test how regime-dependent the rules are."
    )

    ui.section("Simulated trades", f"{len(result.trades)} closed trades at bar-close fills")
    trades = result.trades_frame()
    if trades.empty:
        ui.notice("No trades were generated with these settings on this history.")
    else:
        ui.show_table(trades, height=320)
        st.download_button(
            "Download trades CSV", trades.to_csv(index=False).encode("utf-8"),
            file_name=f"mnz_backtest_{result.symbol.replace('^', '').replace('=', '-')}.csv",
            mime="text/csv",
        )

    if result.warnings:
        with st.expander("Assumptions and warnings", expanded=True):
            for warning in result.warnings:
                st.markdown(f"- {warning}")

    action1, action2, _ = st.columns([1, 1, 2])
    if action1.button("Save this result", key="bt_save"):
        state.get_database().save_backtest({
            "market": result.market,
            "symbol": result.symbol,
            "period": payload["data"].period,
            "interval": payload["data"].interval,
            "settings": result.settings.to_dict(),
            "metrics": result.metrics,
            "is_sample": result.is_sample,
        })
        ui.flash("Backtest result saved to the local database (see Performance Reports).")
        st.rerun()
    if action2.button("Open Performance Reports", key="bt_to_reports", type="secondary"):
        state.goto("Performance Reports")

    ui.notice(
        "Historical results do not guarantee future performance. Backtests are a diagnostic tool for "
        "strategy behaviour, not evidence of future returns.",
        "warn",
    )
    ui.footer()
