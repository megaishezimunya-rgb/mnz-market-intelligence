"""Demo: simulated trading centre, journal and performance reports."""

from __future__ import annotations

from datetime import datetime
from html import escape as html_escape

import numpy as np
import pandas as pd
import streamlit as st

import config
import state
import ui
from data import market_data
from pages import common

SLOT_COLUMNS = ["Slot", "Status", "Symbol", "Side", "Quantity", "Entry", "Mark", "P&L", "TP", "SL"]


def _suggest_quantity(equity: float, entry: float, stop: float | None,
                      risk_pct: float) -> float:
    if entry <= 0 or equity <= 0:
        return 0.0
    if stop and abs(entry - stop) > 0:
        quantity = equity * risk_pct / 100.0 / abs(entry - stop)
    else:
        quantity = equity * 0.10 / entry
    cap = equity * 10.0 / entry
    return float(round(max(0.0, min(quantity, cap)), 6))


def _latest_price(symbol: str, timeframe: str) -> float | None:
    data = market_data.get_timeframe_history(
        symbol, timeframe, allow_sample=state.allow_sample_data(),
    )
    return data.last_price if data.ok else None


def _slot_table(account, marks: dict[str, float], max_slots: int) -> pd.DataFrame:
    open_trades = {trade.slot: trade for trade in account.open_positions() if trade.slot}
    rows = []
    for slot in range(1, max_slots + 1):
        trade = open_trades.get(slot)
        if trade is None:
            rows.append({"Slot": slot, "Status": "Available"})
            continue
        mark = marks.get(trade.symbol)
        rows.append({
            "Slot": slot,
            "Status": "Occupied",
            "Symbol": trade.symbol,
            "Side": trade.side,
            "Quantity": round(trade.quantity, 6),
            "Entry": trade.entry_price,
            "Mark": mark,
            "P&L": round(trade.unrealized_pnl(mark), 2),
            "TP": trade.tp,
            "SL": trade.sl,
        })
    return pd.DataFrame(rows)


def _trade_tab(account, marks: dict[str, float], max_slots: int) -> None:
    user_id = state.require_user()["id"]
    db = state.get_database()
    safety = state.safety()
    timeframe = state.current_timeframe()

    ui.section("Demo entry slots", f"{max_slots} slot(s) selected · a slot is used only after a position opens")
    ui.html_table(
        _slot_table(account, marks, max_slots),
        columns=SLOT_COLUMNS, numeric=["Quantity", "Entry", "Mark", "P&L", "TP", "SL"],
    )

    occupied = {trade.slot for trade in account.open_positions() if trade.slot}
    free_slots = [slot for slot in range(1, max_slots + 1) if slot not in occupied]
    if not free_slots:
        ui.notice(
            "All demo slots are occupied. Close a simulated position before opening another — "
            "the limit exists so simulated exposure stays bounded.",
            "warn",
        )
        return

    mode = st.radio("Entry source", ["From a stored signal", "Manual entry"],
                    horizontal=True, key="demo_mode")

    if mode == "From a stored signal":
        rows = [row for row in db.list_signals(user_id, limit=100)
                if row["label"] in {"BUY", "SELL"}]
        latest: list[dict] = []
        seen = set()
        for row in rows:
            key = row["symbol"]
            if key in seen:
                continue
            seen.add(key)
            latest.append(row)
        if not latest:
            ui.empty_state(
                "No directional signals stored yet.",
                "Run a scan in Markets or Signal Centre, then return here. "
                "Signal entries use the stored entry, TP and SL.",
            )
            return
        options = {
            f"{row['symbol']} · {row['label']} · {row['timeframe']} · Q{row['quality']} · {row['created_at'][:16]}": row
            for row in latest
        }
        picked = st.selectbox("Signal", list(options), key="demo_signal_pick")
        row = options[picked]
        ui.signal_card(row, name=config.instrument_index().get(row["symbol"]).label
                       if row["symbol"] in config.instrument_index() else "")
        if row.get("is_sample") or row.get("data_quality") != "current":
            ui.notice(
                "This signal came from sample or stale data. It is shown for reference, but a "
                "demo entry would be based on an unverified reading.",
                "warn",
            )
        entry = float(row.get("entry_ref") or row["price"])
        side = "Long" if row["label"] == "BUY" else "Short"
        tp = row.get("tp")
        sl = row.get("sl")
        quantity = _suggest_quantity(account.equity(marks), entry, sl, float(safety.get("risk_pct", 1.5)))
        symbol = row["symbol"]
        market = row["market"]
        signal_id = row.get("id")
        trade_timeframe = row.get("timeframe", timeframe)

        c1, c2, c3 = st.columns(3)
        c1.metric("Entry reference", ui.price_fmt(entry))
        c2.metric("Simulated TP", ui.price_fmt(tp))
        c3.metric("Simulated SL", ui.price_fmt(sl))

        with st.form("open_from_signal"):
            qty = st.number_input("Quantity (units)", min_value=0.000001, value=max(quantity, 0.000001),
                                  step=max(quantity / 10, 0.000001), format="%.6f")
            slot = st.selectbox("Demo slot", free_slots)
            confirm = st.checkbox("I understand this is a simulated position with virtual money.")
            submitted = st.form_submit_button("Open simulated position")
        if submitted:
            if not confirm:
                st.error("Please confirm the simulated nature of the position.")
            else:
                trade, problems = account.open_position(
                    symbol=symbol, market=market, side=side, quantity=float(qty),
                    price=entry, tp=tp, sl=sl, slot=int(slot), signal_id=signal_id,
                    timeframe=trade_timeframe, strategy="signal",
                    notes=f"From signal #{signal_id} · {row['label']} · demo",
                )
                if problems:
                    for problem in problems:
                        st.error(problem)
                else:
                    account.snapshot(marks, note="position opened")
                    ui.flash(f"Simulated {side.lower()} opened on {symbol} in slot {slot}.")
                    st.rerun()
    else:
        categories = [key for key, cat in config.MARKETS.items() if cat.available]
        c1, c2 = st.columns(2)
        category_key = c1.selectbox(
            "Market", categories,
            format_func=lambda key: config.MARKETS[key].name, key="demo_manual_market",
        )
        instruments = config.MARKETS[category_key].instruments
        symbols = [item.symbol for item in instruments]
        if st.session_state.get("demo_manual_symbol") not in symbols:
            st.session_state["demo_manual_symbol"] = symbols[0]
        symbol = c2.selectbox(
            "Instrument", symbols, key="demo_manual_symbol",
            format_func=lambda value: f"{value} — {dict((i.symbol, i.label) for i in instruments).get(value, value)}",
        )
        price = _latest_price(symbol, timeframe)
        with st.form("open_manual"):
            c1, c2, c3 = st.columns(3)
            side = c1.selectbox("Side", ["Long", "Short"])
            entry = c2.number_input("Entry price", min_value=0.0,
                                    value=float(price or 1.0), format="%.6f")
            quantity = c3.number_input(
                "Quantity (units)", min_value=0.000001,
                value=max(_suggest_quantity(account.equity(marks), float(price or 1.0), None,
                                            float(safety.get("risk_pct", 1.5))), 0.000001),
                format="%.6f",
            )
            c1, c2, c3 = st.columns(3)
            tp = c1.number_input("Take profit (optional)", min_value=0.0, value=0.0, format="%.6f")
            sl = c2.number_input("Stop loss (optional)", min_value=0.0, value=0.0, format="%.6f")
            slot = c3.selectbox("Demo slot", free_slots)
            confirm = st.checkbox("I understand this is a simulated position with virtual money.")
            submitted = st.form_submit_button("Open simulated position")
        if submitted:
            problems = []
            if entry <= 0:
                problems.append("Entry price must be greater than zero.")
            if not confirm:
                problems.append("Please confirm the simulated nature of the position.")
            if problems:
                for problem in problems:
                    st.error(problem)
            else:
                trade, errors = account.open_position(
                    symbol=symbol, market=category_key, side=side, quantity=float(quantity),
                    price=float(entry), tp=float(tp) or None, sl=float(sl) or None,
                    slot=int(slot), timeframe=timeframe, strategy="manual",
                    notes="Manual simulated entry",
                )
                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    account.snapshot(marks, note="manual position opened")
                    ui.flash(f"Simulated {side.lower()} opened on {symbol} in slot {slot}.")
                    st.rerun()



def _positions_tab(account, marks: dict[str, float]) -> None:
    trades = account.open_positions()
    ui.section("Open simulated positions", "marked at the latest delayed price")
    if not trades:
        ui.notice("No open simulated positions.")
        return
    rows = []
    for trade in trades:
        mark = marks.get(trade.symbol)
        rows.append({
            "Slot": trade.slot,
            "Symbol": trade.symbol,
            "Side": trade.side,
            "Timeframe": trade.timeframe,
            "Quantity": round(trade.quantity, 6),
            "Entry": trade.entry_price,
            "Mark": mark,
            "P&L": round(trade.unrealized_pnl(mark), 2),
            "TP": trade.tp,
            "SL": trade.sl,
            "Opened": (trade.entry_time or "").replace("T", " ")[:16],
        })
    ui.html_table(pd.DataFrame(rows), numeric=["Quantity", "Entry", "Mark", "P&L", "TP", "SL"])
    st.caption("Unrealised P&L is gross of exit costs, which are charged when the position closes.")

    options = {
        f"#{trade.id} · {trade.symbol} · {trade.side} · slot {trade.slot or '—'}": trade
        for trade in trades
    }
    picked = st.selectbox("Close a position", list(options), key="demo_close_pick")
    trade = options[picked]
    mark = marks.get(trade.symbol)
    with st.form("close_position"):
        exit_price = st.number_input(
            "Exit price", min_value=0.0,
            value=float(mark or trade.entry_price), format="%.6f",
        )
        reason = st.text_input("Reason (optional)", placeholder="Manual close / thesis changed")
        submitted = st.form_submit_button("Close simulated position")
    if submitted:
        closed, problems = account.close_position(
            int(trade.id), float(exit_price), reason=reason or "manual close",
        )
        if problems:
            for problem in problems:
                st.error(problem)
        else:
            account.snapshot(marks, note="position closed")
            ui.flash(f"Simulated position closed with P&L {ui.money(closed.net_pnl())}.")
            st.rerun()


def _history_tab(account) -> None:
    trades = account.closed_positions()
    ui.section("Closed simulated positions", "complete demo trade history")
    if not trades:
        ui.notice("No closed simulated positions yet.")
        return
    rows = []
    for trade in trades:
        rows.append({
            "ID": trade.id,
            "Symbol": trade.symbol,
            "Market": config.ENGINE_LABELS.get(trade.market, trade.market),
            "Side": trade.side,
            "Quantity": round(trade.quantity, 6),
            "Entry": trade.entry_price,
            "Exit": trade.exit_price,
            "P&L": round(trade.net_pnl(), 2),
            "Return %": round(trade.return_pct(), 2),
            "Costs": round(trade.costs, 2),
            "Opened": (trade.entry_time or "").replace("T", " ")[:16],
            "Closed": (trade.exit_time or "").replace("T", " ")[:16],
            "Notes": trade.notes,
        })
    frame = pd.DataFrame(rows)
    ui.html_table(frame, numeric=["Quantity", "Entry", "Exit", "P&L", "Return %", "Costs"])
    st.download_button(
        "Download demo trade history (CSV)", frame.to_csv(index=False).encode("utf-8"),
        file_name="mnz_demo_trades.csv", mime="text/csv", key="demo_csv",
    )


def _journal_tab(account) -> None:
    user_id = state.require_user()["id"]
    db = state.get_database()
    ui.section("Intelligent trading journal", "your own notes on simulated decisions")
    closed = account.closed_positions(limit=50)
    options = {"No linked trade": None}
    options.update({
        f"#{trade.id} · {trade.symbol} · {trade.side} · P&L {ui.money(trade.net_pnl())}": trade.id
        for trade in closed
    })
    with st.form("journal_form"):
        linked = st.selectbox("Link to a closed simulated trade (optional)", list(options))
        note = st.text_area("What did you learn?",
                            placeholder="What did the setup look like? Did you follow the plan?")
        c1, c2 = st.columns(2)
        tags = c1.text_input("Tags", placeholder="trend, patience, news")
        mood = c2.selectbox("Confidence", ["", "Low", "Neutral", "High"])
        submitted = st.form_submit_button("Save journal entry")
    if submitted:
        if not note.strip():
            st.error("Write something before saving.")
        else:
            db.add_journal({
                "user_id": user_id,
                "trade_id": options[linked],
                "symbol": next((t.symbol for t in closed if t.id == options[linked]), ""),
                "note": note.strip(),
                "tags": tags,
                "mood": mood,
            })
            ui.flash("Journal entry saved.")
            st.rerun()

    entries = db.list_journal(user_id)
    if not entries:
        ui.notice("No journal entries yet.")
        return
    for entry in entries:
        st.markdown(
            f'<div class="mnz-card"><div style="font-size:.68rem;color:#8C93A3;'
            f'letter-spacing:.08em">{entry["created_at"].replace("T", " ")[:16]} UTC · '
            f'{html_escape(entry.get("symbol") or "general")} · '
            f'{html_escape(entry.get("tags") or "no tags")}</div>'
            f'<div style="font-size:.86rem;line-height:1.65;margin-top:.4rem;white-space:pre-wrap">'
            f'{html_escape(entry["note"])}</div></div>',
            unsafe_allow_html=True,
        )
    labels = {
        f"#{entry['id']} · {entry['created_at'][:16]} · {entry.get('symbol') or 'general'}": entry["id"]
        for entry in entries
    }
    picked = st.selectbox("Delete an entry", ["—"] + list(labels), key="journal_delete_pick")
    if picked != "—" and st.button("Delete entry", key="journal_delete", type="secondary"):
        db.delete_journal(user_id, labels[picked])
        st.rerun()


def _performance_tab(account, marks: dict[str, float]) -> None:
    stats = account.stats()
    drawdown = account.maximum_drawdown()
    equity = account.equity(marks)
    ui.kpi_row([
        {"label": "Virtual equity", "value": ui.money(equity),
         "note": f"Start {ui.money(account.starting_balance)}",
         "trend": 1 if equity >= account.starting_balance else -1},
        {"label": "Realised P&L", "value": ui.money(stats["realized_pnl"]),
         "trend": 1 if stats["realized_pnl"] > 0 else -1 if stats["realized_pnl"] < 0 else 0},
        {"label": "Win rate", "value": ui.pct(stats["win_rate"], 1),
         "note": f"{stats['wins']}W / {stats['losses']}L"},
        {"label": "Profit factor", "value": ui.number(stats["profit_factor"], 2)},
        {"label": "Max drawdown", "value": ui.pct(drawdown["pct"]),
         "note": f"{drawdown['points']} equity points"},
    ])

    ui.section("Equity and drawdown", "from recorded demo snapshots")
    history = account.equity_history()
    if history.empty:
        ui.notice("No equity snapshots yet. Open or close a simulated position to start the curve.")
    else:
        ui.show_chart(ui.equity_chart(history, account.starting_balance,
                                      height=common.chart_height(300)))
        series = history.set_index("ts")["equity"]
        peak = series.cummax()
        dd = pd.DataFrame({
            "ts": series.index,
            "drawdown_pct": ((series / peak.replace(0, np.nan) - 1) * 100).to_numpy(),
        })
        ui.show_chart(ui.drawdown_chart(dd, height=200))

    ui.section("Monthly simulated returns", "computed from recorded equity")
    if history.empty or len(history) < 2:
        ui.notice("Not enough equity history for monthly returns.")
    else:
        monthly = history.set_index("ts")["equity"].resample("ME").last().dropna()
        returns = monthly.pct_change().dropna() * 100
        if returns.empty:
            ui.notice("Not enough monthly points yet.")
        else:
            frame = pd.DataFrame({
                "Month": [stamp.strftime("%Y-%m") for stamp in returns.index],
                "Return %": returns.round(2).to_numpy(),
            })
            ui.show_chart(ui.bar_chart(frame, "Month", "Return %",
                                       height=240, title="Monthly return %"))

    ui.section("Breakdown by market", "closed simulated trades")
    closed = account.closed_positions()
    if closed:
        rows = []
        for market in sorted({trade.market for trade in closed}):
            subset = [trade for trade in closed if trade.market == market]
            pnls = np.array([trade.net_pnl() for trade in subset], dtype=float)
            rows.append({
                "Market": config.ENGINE_LABELS.get(market, market),
                "Trades": len(subset),
                "Net P&L": round(float(pnls.sum()), 2),
                "Wins": int((pnls > 0).sum()),
                "Win rate %": round(float((pnls > 0).mean() * 100), 1),
            })
        ui.html_table(pd.DataFrame(rows), numeric=["Trades", "Net P&L", "Wins", "Win rate %"])
    else:
        ui.notice("No closed trades to break down.")

    st.caption(
        "All figures are simulated from stored demo records. Nothing here is a real account "
        "balance or a live broker statement."
    )


def render() -> None:
    state.require_user()
    account = state.get_account()
    open_trades = account.open_positions()
    marks = common.position_marks(open_trades)
    max_slots = state.max_demo_slots()

    ui.page_header(
        "Demo",
        "A fully simulated trading centre with $100 virtual starting balance, TP/SL exits and "
        "1, 3 or 5 demo slots. No broker, no orders, no real money.",
        tag="SIMULATED ONLY",
    )

    # Automatic simulated exits (TP/SL) are evaluated on each visit.
    exits = account.process_protective_exits(marks)
    if exits:
        for exit_event in exits:
            if exit_event.get("result") in {"TP", "SL"}:
                ui.flash(
                    f"Slot {exit_event.get('trade_id')} closed automatically at simulated "
                    f"{exit_event['result']} · P&L {ui.money(exit_event.get('pnl'))}."
                )
        account.refresh()
        open_trades = account.open_positions()
        marks = common.position_marks(open_trades)

    # There is no scheduler on the host, so long-running simulated positions are
    # closed here on the next visit, at a real current price.
    stale = [event for event in account.close_stale(marks) if event.get("result") == "closed"]
    if stale:
        for event in stale:
            ui.flash(
                f"Simulated position {event.get('trade_id')} ({event.get('symbol')}) was "
                f"auto-closed after {config.DEMO_MAX_OPEN_DAYS} days · P&L "
                f"{ui.money(event.get('pnl'))}."
            )
        account.refresh()
        open_trades = account.open_positions()
        marks = common.position_marks(open_trades)

    equity = account.equity(marks)
    stats = account.stats()
    ui.kpi_row([
        {"label": "Demo equity", "value": ui.money(equity),
         "note": f"{ui.money(account.cash)} virtual cash",
         "trend": 1 if equity >= account.starting_balance else -1},
        {"label": "Open simulated P&L", "value": ui.money(account.unrealized_pnl(marks)),
         "trend": 1 if account.unrealized_pnl(marks) > 0 else -1 if account.unrealized_pnl(marks) < 0 else 0},
        {"label": "Open positions", "value": f"{len(open_trades)} / {max_slots}",
         "note": "slots occupied"},
        {"label": "Closed trades", "value": str(stats["trades_closed"]),
         "note": f"Win rate {ui.pct(stats['win_rate'], 1)}"},
        {"label": "Mode", "value": "DEMO", "note": "Virtual money only"},
    ])
    ui.demo_bar(f"Virtual equity {ui.money(equity)} · {len(open_trades)}/{max_slots} slots · all simulated")

    tab_trade, tab_positions, tab_history, tab_journal, tab_perf = st.tabs(
        ["Trade", "Open positions", "History", "Journal", "Performance Centre"]
    )
    with tab_trade:
        _trade_tab(account, marks, max_slots)
    with tab_positions:
        _positions_tab(account, marks)
    with tab_history:
        _history_tab(account)
    with tab_journal:
        _journal_tab(account)
    with tab_perf:
        _performance_tab(account, marks)

    ui.footer()
