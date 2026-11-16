"""Demo Trading: virtual positions, simulated costs and performance — demo only."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import state
import ui
from engines import all_engines
from pages.engine_common import instrument_selector, load_data
from simulator import portfolio
from simulator.virtual_trades import trades_frame


def _engine_for_symbol(symbol: str) -> str | None:
    for engine in all_engines():
        if engine.instrument(symbol):
            return engine.key
    return None


def _marks_for(account, limit: int = 12) -> tuple[dict[str, float], dict[str, str]]:
    marks: dict[str, float] = {}
    failed: dict[str, str] = {}
    symbols = sorted({trade.symbol for trade in account.open_positions()})[:limit]
    for symbol in symbols:
        engine_key = _engine_for_symbol(symbol)
        if not engine_key:
            failed[symbol] = "No engine is configured for this symbol."
            continue
        data = load_data(engine_key, symbol)
        if data.ok and data.last_price:
            marks[symbol] = data.last_price
        else:
            failed[symbol] = data.error or "No price available."
    return marks, failed


def render() -> None:
    account = state.get_account()
    db = state.get_database()
    marks, failed = _marks_for(account)
    portfolio.record_snapshot(db, account, marks, note="demo trading")
    summary = portfolio.portfolio_summary(account, marks)

    ui.page_header(
        "Demo Trading",
        "Simulated entries and exits with virtual money, simulated transaction costs and full trade "
        "history. No broker connection exists and no order can be placed.",
        tag="DEMO ONLY",
    )
    ui.demo_bar(right=f"Virtual equity {ui.money(summary['equity'])} · starting {ui.money(summary['starting_balance'])}")

    if failed:
        ui.notice(
            "<strong>Some open positions cannot be marked.</strong> No price was available for: "
            + ", ".join(f"{symbol} ({reason})" for symbol, reason in failed.items())
            + ". Their unrealised P&L is excluded rather than estimated.",
            "warn",
        )

    ui.kpi_row([
        {"label": "Virtual equity", "value": ui.money(summary["equity"]), "note": f"cash {ui.money(summary['cash'])}"},
        {"label": "Unrealised P&L", "value": ui.money(summary["unrealized_pnl"]),
         "trend": summary["unrealized_pnl"], "note": f"exposure {ui.pct(summary['exposure_pct'])}"},
        {"label": "Realised P&L", "value": ui.money(summary["realized_pnl"]), "trend": summary["realized_pnl"]},
        {"label": "Total simulated return", "value": ui.pct(summary["total_return_pct"], signed=True),
         "trend": summary["total_return_pct"]},
    ])
    ui.kpi_row([
        {"label": "Open positions", "value": str(summary["open_positions"])},
        {"label": "Closed positions", "value": str(summary["closed_positions"])},
        {"label": "Max drawdown", "value": ui.pct(summary["max_drawdown_pct"]),
         "note": f"{summary['drawdown_points']} equity snapshots"},
        {"label": "Total simulated costs", "value": ui.money(summary["total_costs"]),
         "note": "charged on entry and exit"},
    ])

    # -- open a position ---------------------------------------------------- #
    ui.section("Open a simulated position", "virtual money only — no broker is contacted")
    col1, col2 = st.columns([1, 2], gap="large")
    with col1:
        demo_engine = st.selectbox(
            "Market", list(config.ENGINE_LABELS),
            format_func=lambda key: config.ENGINE_LABELS[key], key="demo_engine",
        )
    with col2:
        demo_symbol, demo_label = instrument_selector(demo_engine, search_enabled=False)

    price_data = load_data(demo_engine, demo_symbol)
    engine_settings = state.get_settings(demo_engine)
    default_cost = float(state.get_data_settings().get("default_cost_bps", config.DEFAULT_SIM_COST_BPS))
    last_price = price_data.last_price or 0.0
    suggested_qty = round(max(summary["equity"], 0.0) * 0.1 / last_price, 4) if last_price > 0 else 1.0

    if not price_data.ok:
        ui.notice(
            f"<strong>No current price for {demo_symbol}.</strong> "
            f"{price_data.error} You can still simulate a trade by entering a price manually.",
            "warn",
        )

    with st.form("demo_open_form"):
        c1, c2, c3 = st.columns(3)
        side = c1.selectbox("Side", ["Long", "Short"], key="demo_side")
        quantity = c2.number_input(
            "Quantity", min_value=0.0001, value=float(max(suggested_qty, 0.0001)),
            step=0.1, format="%.4f", key=f"demo_qty_{demo_symbol}",
            help="Fractional quantities are allowed so small virtual accounts can trade expensive instruments.",
        )
        entry_price = c3.number_input(
            "Entry price", min_value=0.0, value=float(last_price), format="%.5f",
            key=f"demo_price_{demo_symbol}",
            help="Defaults to the latest close. Edit it to simulate a specific fill.",
        )
        c4, c5 = st.columns(2)
        cost_bps = c4.number_input(
            "Transaction cost (bps per side)", min_value=0.0, max_value=500.0,
            value=default_cost, step=0.5, key="demo_cost_open",
        )
        notes = c5.text_input("Note (optional)", key="demo_note", placeholder="Why this simulated trade?")
        st.caption(
            f"Suggested quantity is 10% of virtual equity at the latest price. The engine's own default "
            f"size is {engine_settings.position_size_pct:.0f}% and its cost assumption is "
            f"{engine_settings.cost_bps:.1f} bps — the trade below uses the values you enter."
        )
        open_submit = st.form_submit_button("Open simulated position")

    if open_submit:
        trade, problems = account.open_position(
            symbol=demo_symbol, market=demo_engine, side=side, quantity=float(quantity),
            price=float(entry_price), cost_bps=float(cost_bps), notes=notes, strategy="manual",
        )
        if problems:
            for problem in problems:
                st.error(problem)
        else:
            ui.flash(
                f"Opened simulated {side.lower()} {quantity:,.6f} {demo_symbol} at {ui.price_fmt(entry_price)}."
            )
            st.rerun()

    # -- open positions ----------------------------------------------------- #
    open_trades = account.open_positions()
    ui.section("Open simulated positions", f"{len(open_trades)} position(s)")
    if open_trades:
        ui.show_table(trades_frame(open_trades, marks))

        options = [trade.id for trade in open_trades if trade.id is not None]
        selected_id = st.selectbox(
            "Position to close", options,
            format_func=lambda value: _position_label(open_trades, value), key="demo_close_trade",
        )
        selected = next((trade for trade in open_trades if trade.id == selected_id), None)
        if selected is not None:
            default_exit = marks.get(selected.symbol, selected.entry_price)
            with st.form("demo_close_form"):
                c1, c2, c3 = st.columns(3)
                exit_price = c1.number_input(
                    "Exit price", min_value=0.0, value=float(default_exit), format="%.5f",
                    key=f"demo_exit_{selected.id}",
                )
                exit_cost = c2.number_input(
                    "Exit cost (bps)", min_value=0.0, max_value=500.0, value=default_cost,
                    step=0.5, key=f"demo_cost_close_{selected.id}",
                )
                reason = c3.text_input("Exit reason (optional)", key=f"demo_reason_{selected.id}")
                st.caption(
                    f"Unrealised P&L at the latest mark: {ui.money(selected.unrealized_pnl(marks.get(selected.symbol)))} "
                    f"({ui.pct(selected.unrealized_pct(marks.get(selected.symbol)), signed=True)})."
                )
                close_submit = st.form_submit_button("Close simulated position")
            if close_submit:
                closed, problems = account.close_position(
                    selected.id, float(exit_price), cost_bps=float(exit_cost), reason=reason
                )
                if problems:
                    for problem in problems:
                        st.error(problem)
                else:
                    ui.flash(
                        f"Closed {selected.symbol}: realised P&L {ui.money(closed.net_pnl())} "
                        "after simulated costs."
                    )
                    st.rerun()
    else:
        ui.notice("No open simulated positions. Use the form above to place a virtual trade.")

    # -- closed positions --------------------------------------------------- #
    ui.section("Recently closed simulated positions", "most recent first")
    closed_trades = account.closed_positions(limit=25)
    if closed_trades:
        ui.show_table(trades_frame(closed_trades), height=300)
        if len(closed_trades) == 25:
            st.caption("Showing the 25 most recent closed positions. The full list is on Trade History.")
    else:
        ui.notice("No closed simulated positions yet.")

    # -- equity and allocation ---------------------------------------------- #
    ui.section("Virtual equity", "recorded during this session")
    ui.show_chart(ui.equity_chart(portfolio.equity_curve(account), account.starting_balance, height=280))

    allocation = portfolio.market_allocation(account, marks)
    if not allocation.empty:
        ui.section("Open exposure by market")
        ui.show_table(allocation)
        ui.show_chart(ui.bar_chart(allocation, "Market", "Notional", horizontal=True, height=220,
                                   color_by_sign=False, title="Open notional by market"))

    with st.expander("Reset the demo account", expanded=False):
        ui.notice(
            "Resetting deletes every simulated trade and equity snapshot for this demo account and restores "
            "the starting virtual balance. This cannot be undone.",
            "warn",
        )
        confirmed = st.checkbox("I understand this deletes all simulated trades", key="demo_reset_confirm")
        if st.button("Reset demo account", key="demo_reset_btn", disabled=not confirmed):
            account.reset()
            ui.flash("Demo account reset. All simulated trades were deleted.")
            st.rerun()
        st.caption("The starting virtual balance is configured in Settings → Demo account.")

    if state.get_account().closed_positions():
        st.caption(
            "All figures come from local simulated records. Transaction costs are assumptions, not "
            "observed fills. Nothing here represents a real account."
        )
    ui.footer()


def _position_label(trades, trade_id: int) -> str:
    for trade in trades:
        if trade.id == trade_id:
            return (
                f"#{trade.id} · {trade.side} {trade.quantity:,.6f} {trade.symbol} "
                f"@ {ui.price_fmt(trade.entry_price)}"
            )
    return str(trade_id)
