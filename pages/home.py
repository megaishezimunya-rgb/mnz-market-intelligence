"""Home dashboard for MNZ BOT."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import config
import state
import ui
from data import market_data
from pages import common


def _scanner_status() -> tuple[str, str]:
    meta = st.session_state.get("scan_meta")
    if not meta:
        return "Not started", "No scan has run in this session."
    stamp = (meta.get("at") or "").replace("T", " ")[:16]
    status = "Active" if st.session_state.get("scanner", {}).get("status") == "Running" else "Idle"
    return status, f"Last scan {stamp} UTC · {meta.get('count', 0)} instruments"


def render() -> None:
    user = state.require_user()
    db = state.get_database()
    account = state.get_account()
    display = state.display()

    ui.page_header(
        "Home",
        f"Welcome back, {state.profile().get('name') or 'trader'}. Scanner status, signals, "
        "demo balance and data health in one place.",
        tag="DEMO ACCOUNT",
    )

    open_trades = account.open_positions()
    marks = common.position_marks(open_trades)
    equity = account.equity(marks)
    unrealized = account.unrealized_pnl(marks)
    alerts = db.list_alerts(int(user["id"]), unread_only=True, limit=3)
    counts = db.signal_counts(int(user["id"]))
    scan_status, scan_detail = _scanner_status()

    ui.kpi_row([
        {"label": "Demo equity", "value": ui.money(equity),
         "note": f"Starting {ui.money(account.starting_balance)} · virtual only",
         "trend": 1 if equity >= account.starting_balance else -1},
        {"label": "Open simulated P&L", "value": ui.money(unrealized),
         "note": f"{len(open_trades)} of {len(open_trades) + (state.max_demo_slots() - len(open_trades))} slots used",
         "trend": 1 if unrealized > 0 else -1 if unrealized < 0 else 0},
        {"label": "Scanner", "value": scan_status, "note": scan_detail},
        {"label": "Stored signals", "value": str(sum(counts.values())),
         "note": f"{counts.get('BUY', 0)} BUY · {counts.get('SELL', 0)} SELL · {counts.get('WAIT', 0)} WAIT"},
        {"label": "Alerts", "value": str(len(alerts)),
         "note": "Unread Smart Alerts" if alerts else "No unread alerts"},
    ])

    ui.demo_bar(f"Virtual equity {ui.money(equity)} · all positions simulated")

    left, right = st.columns([1.75, 1], gap="large")

    with left:
        ui.section("Latest signals", "newest stored readings")
        rows = db.list_signals(int(user["id"]), limit=4)
        if not rows:
            ui.empty_state(
                "No signals stored yet.",
                "Open Markets, choose a timeframe and press Scan All to generate the first readings.",
            )
            if st.button("Open Markets", key="home_open_markets"):
                state.goto("Markets")
        else:
            for row in rows:
                name = config.instrument_index().get(row["symbol"])
                ui.signal_card(row, name=name.label if name else "")
            if st.button("View signal centre", key="home_to_signals", type="secondary"):
                state.goto("Signals")

        ui.section("Monitored market categories", "from your display settings")
        chosen = display.get("categories", ["forex", "indices", "stocks"])
        cards = []
        for key in chosen:
            category = config.MARKETS.get(key)
            if not category:
                continue
            state_text = (
                f"{len(category.instruments)} instruments · live feed"
                if category.available
                else "Awaiting a data connection"
            )
            cards.append({
                "label": category.name,
                "value": "Active" if category.available else "Not connected",
                "note": state_text,
                "trend": 1 if category.available else 0,
            })
        ui.kpi_row(cards)
        if st.button("Change monitored markets", key="home_to_settings", type="secondary"):
            state.goto("Settings")

    with right:
        ui.section("Market data connection", "verified, not assumed")
        health = common.connection_health()
        provider = market_data.provider_status()
        if health["ok"]:
            ui.notice(
                f"<strong>Connected</strong> · {config.DATA_SOURCE_NAME}<br>"
                f"Probe latency {health['latency_ms']} ms · last success "
                f"{(provider.get('last_success_at') or '').replace('T', ' ')[:16]} UTC. "
                "Delayed public data — not an execution feed.",
                "ok",
            )
        else:
            ui.notice(
                "<strong>No verified connection.</strong> "
                f"{health.get('error') or provider.get('detail') or 'The provider could not be reached.'}<br>"
                "Markets will show an explicit error instead of prices.",
                "warn",
            )
        if st.button("Re-check connection", key="home_ping", type="secondary"):
            common.connection_health(force=True)
            st.rerun()

        ui.section("Important alerts", "unread only")
        if not alerts:
            ui.notice("No unread alerts. Smart Alerts are created only from current, directional signals.")
        else:
            for alert in alerts:
                severity = "ok" if alert.get("severity") == "buy" else "warn"
                ui.notice(
                    f"<strong>{alert['title']}</strong><br>{alert['message']}",
                    severity,
                )
            if st.button("Open alerts", key="home_to_alerts", type="secondary"):
                state.goto("Signals")

        ui.section("Next event windows", "recurring, not a live calendar")
        events = common.upcoming_events(days=7)[:3]
        for event in events:
            when = event.get("when_text", "Varies")
            ui.notice(
                f"<strong>{event['name']}</strong><br>{when} · {event['certainty']}",
            )

    ui.section("Demo activity", "simulated only")
    if open_trades:
        rows = []
        for trade in open_trades:
            mark = marks.get(trade.symbol)
            rows.append({
                "Symbol": trade.symbol,
                "Side": trade.side,
                "Quantity": trade.quantity,
                "Entry": trade.entry_price,
                "Mark": mark,
                "P&L": round(trade.unrealized_pnl(mark), 2),
                "TP": trade.tp,
                "SL": trade.sl,
                "Slot": trade.slot,
            })
        ui.html_table(pd.DataFrame(rows), numeric=["Quantity", "Entry", "Mark", "P&L", "TP", "SL"])
        st.caption("Marks are the latest delayed prices. No real position exists.")
        if st.button("Open Demo centre", key="home_to_demo", type="secondary"):
            state.goto("Demo")
    else:
        ui.notice(
            "No open simulated positions. Open a signal in <strong>Demo</strong> to create one — "
            "a slot is only used after the position is successfully created."
        )

    ui.footer()
