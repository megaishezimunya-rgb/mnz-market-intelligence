"""Trade History: the complete record of simulated trades with filters and export."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import state
import ui
from simulator import portfolio
from simulator.virtual_trades import trades_frame


def render() -> None:
    account = state.get_account()
    ui.page_header(
        "Trade History",
        "Every simulated trade stored in the local database, with costs and realised or unrealised P&L.",
        tag="DEMO ONLY",
    )
    ui.demo_bar(right=f"Account #{account.id} · {account.name}")

    trades = account.all_positions()
    if not trades:
        ui.empty_state(
            "No simulated trades recorded yet.",
            "Open positions from the Demo Trading page to build a history.",
        )
        if st.button("Open Demo Trading", type="secondary"):
            state.goto("Demo Trading")
        ui.footer()
        return

    # -- filters ------------------------------------------------------------ #
    ui.section("Filters")
    col1, col2, col3 = st.columns([1.6, 1, 1.4])
    with col1:
        markets = st.multiselect(
            "Market", sorted({trade.market for trade in trades}),
            default=sorted({trade.market for trade in trades}),
            format_func=lambda key: config.ENGINE_LABELS.get(key, key.title()),
            key="history_markets",
        )
    with col2:
        status = st.selectbox("Status", ["All", "Open", "Closed"], key="history_status")
    with col3:
        symbol_query = st.text_input("Symbol contains", key="history_symbol", placeholder="e.g. BTC")

    filtered = [trade for trade in trades if trade.market in markets]
    if status != "All":
        filtered = [trade for trade in filtered if trade.status.lower() == status.lower()]
    if symbol_query.strip():
        needle = symbol_query.strip().upper()
        filtered = [trade for trade in filtered if needle in trade.symbol.upper()]

    marks: dict[str, float] = {}
    for symbol in sorted({trade.symbol for trade in filtered if trade.is_open})[:12]:
        from engines import all_engines
        from pages.engine_common import load_data

        engine_key = next(
            (engine.key for engine in all_engines() if engine.instrument(symbol)), None
        )
        if not engine_key:
            continue
        data = load_data(engine_key, symbol)
        if data.ok and data.last_price:
            marks[symbol] = data.last_price

    frame = trades_frame(filtered, marks)
    summary = portfolio.portfolio_summary(account, marks)
    ui.kpi_row([
        {"label": "Trades shown", "value": str(len(filtered)),
         "note": f"{len(trades)} recorded in total"},
        {"label": "Open positions", "value": str(sum(trade.is_open for trade in filtered))},
        {"label": "Realised P&L (all)", "value": ui.money(summary["realized_pnl"]),
         "trend": summary["realized_pnl"]},
        {"label": "Total simulated costs", "value": ui.money(summary["total_costs"])},
    ])

    ui.section("Recorded simulated trades", "unrealised values use the latest available mark")
    if frame.empty:
        ui.notice("No trades match these filters.")
    else:
        preferred = [
            "ID", "Symbol", "Market", "Side", "Status", "Quantity", "Entry", "Exit",
            "Entry time", "Exit time", "Costs", "Unrealised P&L", "Realised P&L",
            "Unrealised %", "Return %", "Strategy",
        ]
        columns = [column for column in preferred if column in frame.columns]
        ui.show_table(frame[columns], height=420)
        st.download_button(
            "Download trade history CSV",
            frame.to_csv(index=False).encode("utf-8"),
            file_name="mnz_trade_history.csv",
            mime="text/csv",
        )

    stats = portfolio.trade_statistics(filtered)
    if not stats.empty:
        ui.section("Statistics for the filtered trades")
        ui.show_table(stats)

    ui.notice(
        "These are simulated trades stored locally. MNZ has no connection to a broker, exchange or "
        "custodian, and cannot place, modify or close a real order.",
    )
    ui.footer()
