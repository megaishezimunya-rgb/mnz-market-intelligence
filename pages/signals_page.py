"""Signals: Signal Centre, complete history, measured performance and alerts."""

from __future__ import annotations

from datetime import date, timedelta
from html import escape as html_escape

import pandas as pd
import streamlit as st

import config
import scanner
import state
import ui
from analysis import signals
from data import market_data
from pages import common


def _latest_per_instrument(rows: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for row in rows:
        key = (row["symbol"], row.get("timeframe", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _scan(categories: list[str], timeframe: str) -> None:
    user_id = state.require_user()["id"]
    total_created = 0
    total_alerts = 0
    scanned = 0
    for key in categories:
        category = config.MARKETS.get(key)
        if not category or not category.available:
            continue
        targets = config.SCAN_SHORTLIST.get(key, [i.symbol for i in category.instruments[:4]])
        with st.spinner(f"Scanning {category.name}…"):
            results = scanner.scan_many(
                targets, key, timeframe, allow_sample=False, force_refresh=True,
            )
        summary = common.store_scan(user_id, results, timeframe=timeframe, market=key)
        total_created += summary["created"]
        total_alerts += summary["alerts"]
        scanned += len(results)
    ui.flash(
        f"Scanned {scanned} instrument(s) across {len(categories)} market(s): "
        f"{total_created} new signal(s), {total_alerts} alert(s)."
    )


def _window_label(item: dict) -> str:
    if item["state"] == "actionable" and item["minutes_left"] is not None:
        left = int(item["minutes_left"])
        return f"{left // 60}h {left % 60:02d}m left" if left >= 60 else f"{left}m left"
    if item["state"] == "expired":
        return "Expired"
    return "—"


def _trade_plan(latest: list[dict]) -> None:
    """One line per reading: what to do, where the exits are, how long it holds."""
    ui.section(
        "Trade plan",
        "side, entry, stop and target per reading — and when the plan stops counting",
    )
    items = []
    for row in latest:
        item = signals.plan(row)
        item["symbol"] = row.get("symbol", "")
        items.append(item)
    order = {"actionable": 0, "waiting": 1, "expired": 2, "closed": 3}
    items.sort(key=lambda item: order.get(item["state"], 4))

    frame = pd.DataFrame([
        {
            "Symbol": item["symbol"],
            "Bias": item["label"],
            "Action": item["action"],
            "Entry ref": item["entry"],
            "Stop": item["stop"],
            "Target": item["target"],
            "R:R": round(item["risk_reward"], 2) if item["risk_reward"] else None,
            "Valid until (UTC)": (
                item["valid_until"].strftime("%d %b %H:%M") if item["valid_until"] else None
            ),
            "Window": _window_label(item),
            "State": item["state"],
        }
        for item in items
    ])
    ui.html_table(frame, numeric=["Entry ref", "Stop", "Target", "R:R"])

    if not any(item["state"] == "actionable" for item in items):
        ui.notice(
            "No reading is actionable right now. WAIT is a valid answer: sitting out is a "
            "position too."
        )
    st.caption(
        "Levels are the ones stored with the signal (entry = the close it was read from, "
        "stop = 1.5 × ATR, target = 2.6 × ATR). A plan is valid for "
        f"{config.SIGNAL_VALID_BARS} bars of its own timeframe, then it is expired and needs a "
        "fresh scan. Nothing is executed anywhere — this is a demo."
    )


def _signal_centre(timeframe: str) -> None:
    user_id = state.require_user()["id"]
    categories = [k for k, cat in config.MARKETS.items() if cat.available]
    labels = {k: config.MARKETS[k].name for k in categories}

    c1, c2, c3 = st.columns([1.4, 1.6, 1.2])
    with c1:
        category_list = st.multiselect(
            "Markets to scan", categories, default=categories[:3],
            format_func=lambda key: labels[key], key="signals_scan_markets",
        )
    with c2:
        if st.session_state.get("signals_tf") not in config.TIMEFRAMES:
            st.session_state["signals_tf"] = timeframe
        timeframe = st.pills(
            "Timeframe", config.TIMEFRAME_ORDER,
            selection_mode="single", key="signals_tf",
        ) or timeframe
    with c3:
        st.write("")
        scan_now = st.button("Scan selected markets", key="signals_scan", type="primary")

    if scan_now:
        if not category_list:
            st.error("Select at least one market to scan.")
        else:
            _scan(category_list, timeframe)
            st.rerun()

    rows = state.get_database().list_signals(user_id, limit=200)
    latest = _latest_per_instrument(rows)
    if timeframe:
        latest = [row for row in latest if row.get("timeframe") == timeframe] or latest

    if not latest:
        ui.empty_state(
            "No signals stored yet.",
            "Scan selected markets above to create the first signal for each instrument.",
        )
        return

    ui.section("Signal Centre", f"latest stored reading per instrument · {timeframe}")
    columns = st.columns(2)
    for index, row in enumerate(latest[:10]):
        instrument = config.instrument_index().get(row["symbol"])
        with columns[index % 2]:
            ui.signal_card(
                row, name=instrument.label if instrument else "", plan=signals.plan(row)
            )

    _trade_plan(latest)

    ui.section("MNZ Safety Guard", "veto checks before a signal is treated as usable")
    options = {f"{row['symbol']} · {row['label']} · {row['timeframe']} · {row['created_at'][:16]}": row
               for row in latest}
    picked = st.selectbox("Inspect a signal", list(options), key="signals_guard_pick")
    row = options[picked]
    instrument = config.instrument_index().get(row["symbol"])
    data = market_data.get_timeframe_history(
        row["symbol"], row.get("timeframe") or timeframe, allow_sample=False,
    )
    checks = scanner.safety_guard(data, row)
    items = "".join(
        f'<tr><td>{html_escape(check["name"])}</td>'
        f'<td style="color:{"#20D68A" if check["ok"] else "#F04452"};font-weight:600">'
        f'{"PASS" if check["ok"] else "BLOCKED"}</td>'
        f'<td>{html_escape(check["detail"])}</td></tr>'
        for check in checks
    )
    st.markdown(
        '<div class="mnz-html-table-wrap"><table class="mnz-html-table">'
        "<thead><tr><th>Check</th><th>State</th><th>Detail</th></tr></thead>"
        f"<tbody>{items}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    if instrument is not None:
        st.caption(f"{instrument.label} · {instrument.notes}")


def _history(timeframe_filter: str) -> None:
    user_id = state.require_user()["id"]
    rows = state.get_database().list_signals(user_id, limit=500)
    if not rows:
        ui.empty_state("No signal history yet.", "Run a scan in the Signal Centre to start recording.")
        return

    symbols = sorted({row["symbol"] for row in rows})
    c1, c2, c3, c4 = st.columns([1.3, 1.3, 1, 1])
    with c1:
        since = st.date_input("From", value=date.today() - timedelta(days=30), key="hist_since")
    with c2:
        until = st.date_input("To", value=date.today(), key="hist_until")
    with c3:
        picked_symbols = st.multiselect("Instrument", symbols, key="hist_symbols",
                                        placeholder="All instruments")
    with c4:
        label = st.selectbox("Direction", ["All", "BUY", "SELL", "WAIT"], key="hist_label")

    frame = common.signal_frame(rows)
    mask = pd.Series(True, index=frame.index)
    if isinstance(since, date):
        mask &= frame["Created (UTC)"] >= since.isoformat()
    if isinstance(until, date):
        mask &= frame["Created (UTC)"] <= until.isoformat() + " 23:59"
    if picked_symbols:
        mask &= frame["Symbol"].isin(picked_symbols)
    if label != "All":
        mask &= frame["Signal"] == label
    view = frame[mask]

    ui.section("Complete signal history", f"{len(view)} of {len(frame)} stored signals")
    if view.empty:
        ui.notice("No signals match these filters.")
    else:
        ui.html_table(view, numeric=["Quality", "Price", "Entry ref", "TP", "SL"])
        st.download_button(
            "Download signal history (CSV)", view.to_csv(index=False).encode("utf-8"),
            file_name="mnz_signal_history.csv", mime="text/csv", key="hist_csv",
        )

    ui.section("Measured outcomes", "first-touch TP/SL against later bars — never inferred")
    if st.button("Measure unresolved signals", key="hist_measure", type="secondary"):
        with st.spinner("Checking subsequent bars…"):
            measured = common.refresh_signal_outcomes([
                row for row in rows
                if (not picked_symbols or row["symbol"] in picked_symbols)
                and (label == "All" or row["label"] == label)
            ])
        changed = sum(1 for row in measured if row.get("status") in {"Closed", "Unresolved"})
        ui.flash(f"Outcome check complete. {changed} resolved signal(s) now have a measured result.")
        st.rerun()

    detail = st.selectbox(
        "Open a signal", [
            f"#{row['id']} · {row['symbol']} · {row['label']} · {row['timeframe']} · {row['created_at'][:16]}"
            for row in rows
        ], key="hist_detail",
    )
    chosen = rows[[
        f"#{row['id']} · {row['symbol']} · {row['label']} · {row['timeframe']} · {row['created_at'][:16]}"
        for row in rows
    ].index(detail)]
    ui.signal_card(chosen, name=config.instrument_index().get(chosen["symbol"]).label
                   if chosen["symbol"] in config.instrument_index() else "")
    st.caption(
        f"Result: **{signals.outcome_status_label(chosen)}** · quality {chosen['quality']}/100 · "
        f"data {chosen['data_quality']} · source {chosen['source']}."
    )


def _performance() -> None:
    user_id = state.require_user()["id"]
    rows = state.get_database().list_signals(user_id, limit=1000)
    if not rows:
        ui.empty_state("No signals recorded yet.", "Performance is measured only from stored signals.")
        return
    common.refresh_signal_outcomes(rows)
    stats = signals.signal_performance(rows)
    ui.kpi_row([
        {"label": "Stored signals", "value": str(stats["signals"]),
         "note": f"{stats['directional']} directional · {stats['signals'] - stats['directional']} WAIT"},
        {"label": "Resolved", "value": str(stats["resolved"]),
         "note": f"{stats['open']} still pending"},
        {"label": "Simulated TP hits", "value": str(stats["tp_hits"]), "trend": 1 if stats["tp_hits"] else 0},
        {"label": "Simulated SL hits", "value": str(stats["sl_hits"]), "trend": -1 if stats["sl_hits"] else 0},
        {"label": "Resolved hit rate", "value": ui.pct(stats["hit_rate"], 1),
         "note": "TP-first ÷ resolved signals"},
        {"label": "Expectancy", "value": f"{stats['expectancy_r']:+.2f}R"
         if stats["sample_size"] else "n/a", "note": f"average R over {stats['sample_size']} resolved"},
    ])
    ui.notice(
        "Hit rate counts only signals whose simulated TP or SL was actually reached in subsequent "
        "provider bars. Pending and ambiguous signals are excluded, so a small sample can look "
        "extreme. Expectancy is measured in R (reward ÷ simulated risk) and is not a forecast or "
        "a track record of real trading."
    )

    measured = signals.calibration(rows)
    ui.section("Signal Calibration", "measured TP/SL outcomes by market, timeframe and quality")
    if not measured["resolved"]:
        ui.notice(
            "No resolved outcomes yet, so there is nothing to calibrate. A signal only counts "
            "once later bars actually reach its simulated TP or SL; use “Measure unresolved "
            "signals” in History after some time has passed."
        )
    else:
        overall = measured["overall"]
        ui.kpi_row([
            {"label": "Resolved signals", "value": str(overall["resolved"]),
             "note": f"minimum sample {measured['min_sample']} per group"},
            {"label": "TP-first hit rate", "value": ui.pct(overall["hit_rate"], 1),
             "note": f"{overall['tp_hits']} TP · {overall['sl_hits']} SL"},
            {"label": "Expectancy",
             "value": f"{overall['expectancy_r']:+.2f}R" if overall["resolved"] else "n/a",
             "note": "average R per resolved signal",
             "trend": 1 if overall["expectancy_r"] > 0 else -1 if overall["expectancy_r"] < 0 else 0},
            {"label": "Profit factor", "value": ui.number(overall["profit_factor"], 2)},
        ])
        for key, title, note in [
            ("by_market", "By market", "does the edge hold in each market you scan?"),
            ("by_timeframe", "By timeframe", "does the edge survive across horizons?"),
            ("by_quality", "By quality band", "does the quality score separate outcomes?"),
        ]:
            items = measured.get(key) or []
            if not items:
                continue
            ui.section(title, note)
            table = pd.DataFrame([
                {
                    "Group": item["name"],
                    "Resolved": item["resolved"],
                    "TP hit rate %": round(item["hit_rate"], 1) if item["hit_rate"] == item["hit_rate"] else None,
                    "Expectancy (R)": round(item["expectancy_r"], 2) if item["expectancy_r"] == item["expectancy_r"] else None,
                    "Profit factor": round(item["profit_factor"], 2) if item["profit_factor"] == item["profit_factor"] else None,
                    "Sample": "Sufficient" if item["reliable"] else "Too few",
                }
                for item in items
            ])
            ui.html_table(table, numeric=["Resolved", "TP hit rate %", "Expectancy (R)", "Profit factor"])
        st.caption(
            measured["note"] + " Groups marked “Too few” are shown for transparency, not as an "
            "edge, and past simulated outcomes never guarantee future results."
        )

    frame = common.signal_frame(rows)
    resolved = frame[frame["Result"].isin(["TP hit", "SL hit"])]
    if not resolved.empty:
        ui.section("Outcome by instrument", "resolved signals only")
        grouped = resolved.groupby(["Symbol", "Result"]).size().unstack(fill_value=0).reset_index()
        for column in ["TP hit", "SL hit"]:
            if column not in grouped:
                grouped[column] = 0
        grouped["Resolved"] = grouped["TP hit"] + grouped["SL hit"]
        grouped["Hit rate %"] = (grouped["TP hit"] / grouped["Resolved"] * 100).round(1)
        ui.html_table(grouped, numeric=["TP hit", "SL hit", "Resolved", "Hit rate %"])
    else:
        ui.notice(
            "No resolved outcomes yet. Signals need later bars that reach TP or SL; "
            "use “Measure unresolved signals” in History after some time has passed."
        )


def _alerts() -> None:
    user = state.require_user()
    db = state.get_database()
    prefs = state.notifications()
    unread = db.list_alerts(int(user["id"]), unread_only=True, limit=50)
    all_alerts = db.list_alerts(int(user["id"]), limit=200)

    ui.kpi_row([
        {"label": "Unread alerts", "value": str(len(unread))},
        {"label": "Saved alerts", "value": str(len(all_alerts))},
        {"label": "Minimum strength", "value": prefs.get("min_strength", "Moderate")},
        {"label": "Minimum quality", "value": f"{prefs.get('min_quality', config.ALERT_MIN_QUALITY)}/100"},
        {"label": "Alerts enabled", "value": "Yes" if prefs.get("enabled") else "No"},
    ])
    if not prefs.get("enabled"):
        ui.notice("Smart Alerts are switched off in your notification settings.", "warn")

    with st.expander("Notification preferences", expanded=False):
        with st.form("alert_prefs_form"):
            enabled = st.checkbox("Enable Smart Alerts", value=bool(prefs.get("enabled", True)))
            strength = st.selectbox(
                "Minimum signal strength", config.ALERT_STRENGTHS,
                index=config.ALERT_STRENGTHS.index(prefs.get("min_strength", "Moderate")),
            )
            quality = st.slider("Minimum quality score", 0, 100,
                                int(prefs.get("min_quality", config.ALERT_MIN_QUALITY)), 5)
            in_app = st.checkbox("Create in-app notifications",
                                 value=bool(prefs.get("in_app", True)))
            saved = st.form_submit_button("Save preferences")
        if saved:
            state.save_notifications({
                "enabled": enabled, "min_strength": strength,
                "min_quality": int(quality), "in_app": in_app,
            })
            ui.flash("Notification preferences saved.")
            st.rerun()

    ui.section("Unread", "generated from new, current, directional signals")
    if not unread:
        ui.notice("No unread alerts.")
    else:
        for alert in unread:
            severity = "ok" if alert.get("severity") == "buy" else "warn"
            ui.notice(
                f"<strong>{html_escape(alert['title'])}</strong><br>"
                f"{html_escape(alert['message'])}<br>"
                f"<span style='font-size:.7rem;color:#8C93A3'>{alert['created_at'].replace('T', ' ')} UTC</span>",
                severity,
            )

    c1, c2 = st.columns(2)
    if c1.button("Mark all read", key="alerts_read", type="secondary"):
        db.mark_alerts_read(int(user["id"]))
        st.rerun()
    if c2.button("Clear alert history", key="alerts_clear", type="secondary"):
        db.clear_alerts(int(user["id"]))
        ui.flash("Alert history cleared.")
        st.rerun()

    ui.section("Saved alert history", "what was sent, and when")
    if not all_alerts:
        ui.notice("No alerts have been created for this account.")
        return
    frame = pd.DataFrame([
        {
            "When (UTC)": alert["created_at"].replace("T", " ")[:16],
            "Symbol": alert["symbol"],
            "Type": alert["kind"],
            "Title": alert["title"],
            "Read": "Yes" if alert.get("read_at") else "No",
        }
        for alert in all_alerts
    ])
    ui.html_table(frame)


def render() -> None:
    state.require_user()
    ui.page_header(
        "Signals",
        "The Signal Centre, full history with measured outcomes, performance and Smart Alerts. "
        "Every signal is a rule-based reading of delayed bars.",
        tag="RULE-BASED",
    )
    timeframe = state.current_timeframe()
    tab_centre, tab_history, tab_perf, tab_alerts = st.tabs(
        ["Signal Centre", "Signal History", "Performance", "Alerts"]
    )
    with tab_centre:
        _signal_centre(timeframe)
    with tab_history:
        _history(timeframe)
    with tab_perf:
        _performance()
    with tab_alerts:
        _alerts()
    ui.footer()
