"""MNZ AI: grounded explanations of markets, signals and indicators."""

from __future__ import annotations

import streamlit as st

import ai
import config
import state
import ui
from analysis import indicators
from analysis.signals import Signal
from data import market_data
from pages import common


def _load(symbol: str, timeframe: str):
    data = market_data.get_timeframe_history(
        symbol, timeframe, allow_sample=state.allow_sample_data(),
    )
    snapshot = None
    if data.ok:
        settings = config.ENGINE_STRATEGY_DEFAULTS.get(
            config.instrument_index().get(symbol).market if symbol in config.instrument_index() else "",
            config.StrategySettings(),
        )
        snapshot = indicators.snapshot(
            data.frame, fast=settings.fast_ma, slow=settings.slow_ma,
            rsi_period=settings.rsi_period,
        )
    return data, snapshot


def _context(symbol: str, timeframe: str) -> ai.AssistantContext:
    user = state.require_user()
    db = state.get_database()
    account = state.get_account()
    data, snapshot = _load(symbol, timeframe)
    row = db.latest_signal_for(int(user["id"]), symbol, timeframe)
    signal = Signal.from_row(row) if row else None
    results = st.session_state.get("scan_results") or []
    conditions = None
    if results:
        import scanner

        conditions = scanner.market_conditions(results)
    # Latest stored reading per instrument/timeframe, so the assistant can rank
    # real stored setups instead of guessing at what is on other screens.
    recent: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in db.list_signals(int(user["id"]), limit=150):
        key = (str(row.get("symbol")), str(row.get("timeframe")))
        if key in seen:
            continue
        seen.add(key)
        recent.append(row)
    open_trades = account.open_positions()
    marks = common.position_marks(open_trades)
    return ai.AssistantContext(
        mode=st.session_state.get("ai_mode", "Beginner"),
        symbol=symbol,
        data=data,
        signal=signal,
        snapshot=snapshot,
        equity=account.equity(marks),
        starting_balance=account.starting_balance,
        open_positions=len(open_trades),
        closed_positions=len(account.closed_positions(limit=500)),
        conditions=conditions,
        recent_signals=recent[:20],
        timeframe=timeframe,
        alerts_unread=db.unread_alert_count(int(user["id"])),
    )


def _ask(question: str, symbol: str, timeframe: str) -> None:
    ctx = _context(symbol, timeframe)
    answer = ai.answer(question, ctx)
    chat = st.session_state.setdefault("ai_chat", [])
    chat.append({"role": "user", "content": question})
    chat.append({"role": "assistant", "content": answer})
    st.session_state["ai_chat"] = chat[-40:]


def render() -> None:
    state.require_user()
    user = state.require_user()
    profile = state.profile()
    idx = config.instrument_index()

    ui.page_header(
        "MNZ AI",
        "Ask about the instrument on screen, a stored signal, an indicator or how the platform "
        "works. Answers are generated from the data actually loaded — no invented prices or news.",
        tag="GROUNDED",
    )

    c1, c2, c3 = st.columns([1.4, 1.7, 1.2])
    with c1:
        available = sorted({
            instrument.symbol for category in config.MARKETS.values()
            if category.available for instrument in category.instruments
        })
        if st.session_state.get("ai_symbol") not in available:
            st.session_state["ai_symbol"] = available[0]
        symbol = st.selectbox(
            "Instrument", available,
            format_func=lambda value: f"{value} — {idx[value].label}" if value in idx else value,
            key="ai_symbol",
        )
    with c2:
        if st.session_state.get("ai_tf") not in config.TIMEFRAMES:
            st.session_state["ai_tf"] = state.current_timeframe()
        timeframe = st.pills(
            "Timeframe", config.TIMEFRAME_ORDER, selection_mode="single", key="ai_tf",
        ) or state.current_timeframe()
    with c3:
        if st.session_state.get("ai_mode") not in {"Beginner", "Professional"}:
            st.session_state["ai_mode"] = profile.get("experience", "Beginner")
        mode = st.pills(
            "Explanation mode", ["Beginner", "Professional"],
            selection_mode="single", key="ai_mode",
        )
    ctx = _context(symbol, timeframe)
    data = ctx.data
    signal = ctx.signal

    left, right = st.columns([1.8, 1], gap="large")

    with left:
        ui.section("Conversation", f"{st.session_state.get('ai_mode', 'Beginner')} mode · {symbol} {timeframe}")
        chat = st.session_state.get("ai_chat", [])
        if not chat:
            st.markdown(
                '<div class="mnz-chat-ai"><div class="who">MNZ AI</div>'
                f"I'm looking at <strong>{symbol}</strong> on <strong>{timeframe}</strong>"
                + (" with a stored signal." if signal else " — no stored signal for this timeframe yet.")
                + " Ask me to explain the reading, an indicator, or how the demo works.</div>",
                unsafe_allow_html=True,
            )
        for message in chat:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        question = st.chat_input(f"Ask about {symbol} or MNZ BOT…")
        if question:
            _ask(question, symbol, timeframe)
            st.rerun()

        st.caption("Suggested questions")
        suggestions = ai.SUGGESTED_QUESTIONS
        for row_start in range(0, len(suggestions), 3):
            columns = st.columns(3)
            for column, suggestion in zip(columns, suggestions[row_start:row_start + 3]):
                if column.button(suggestion, key=f"ai_suggest_{suggestion}", type="secondary"):
                    _ask(suggestion, symbol, timeframe)
                    st.rerun()

        if st.button("Clear conversation", key="ai_clear", type="secondary"):
            st.session_state["ai_chat"] = []
            st.rerun()

    with right:
        ui.section("What the assistant can see", "verified context only")
        if data.ok:
            ui.kpi_row([
                {"label": "Last price", "value": ui.price_fmt(data.last_price),
                 "note": data.status_note()},
                {"label": "Bars", "value": str(data.bars), "note": f"interval {data.interval}"},
            ])
            ui.source_line(data)
        else:
            ui.empty_state(f"No verified data for {symbol}: {data.error}",
                           "The assistant will say so rather than invent a price.")

        if signal:
            ui.signal_card(signal.to_db(), name=idx[symbol].label if symbol in idx else "")
        else:
            ui.notice("No stored signal for this instrument and timeframe.")

        if ctx.conditions:
            ui.section("Scan conditions", "last scan in this session")
            ui.kpi_row([
                {"label": "Bias", "value": ctx.conditions["label"]},
                {"label": "Avg quality", "value": f"{ctx.conditions['avg_quality']}/100"},
            ])
        else:
            ui.notice("No scan has run in this session, so no cross-market picture is available.")

        ui.notice(
            "<strong>Limits.</strong> MNZ AI is a deterministic assistant, not a language model and "
            "not an adviser. It cannot see news and will not speculate about causes it has no data "
            "for."
        )

    ui.footer()
