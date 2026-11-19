"""Shared helpers for the MNZ BOT pages."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import streamlit as st

import config
import state
from analysis import signals
from data import market_data
from database.database import Database

PAGE_KEYS = ["scanner", "scan_results", "scan_meta", "chat", "ai_symbol"]


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def position_marks(trades, *, allow_sample: bool | None = None) -> dict[str, float]:
    """Last verified price for each symbol held by the supplied trades."""
    marks: dict[str, float] = {}
    for trade in trades:
        key = (trade.symbol, trade.timeframe or state.current_timeframe())
        if trade.symbol in marks:
            continue
        data = market_data.get_timeframe_history(
            trade.symbol, trade.timeframe or state.current_timeframe(),
            allow_sample=state.allow_sample_data() if allow_sample is None else allow_sample,
        )
        if data.ok and data.last_price is not None:
            marks[trade.symbol] = float(data.last_price)
    return marks


def latest_signal_rows(user_id: int, limit: int = 40) -> list[dict]:
    return state.get_database().list_signals(user_id, limit=limit)


def connection_health(*, force: bool = False, max_age_seconds: int = 240) -> dict:
    """Cached provider probe so every page can show an honest connection state."""
    key = "mnz_connection"
    now = config.utcnow()
    stored = st.session_state.get(key)
    if stored and not force:
        try:
            age = (now - datetime.fromisoformat(stored["checked_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = max_age_seconds + 1
        if age < max_age_seconds:
            return stored
    probe = market_data.ping()
    record = {
        "ok": probe["ok"],
        "latency_ms": probe["latency_ms"],
        "error": probe["error"],
        "bars": probe["bars"],
        "checked_at": now.isoformat(timespec="seconds"),
    }
    st.session_state[key] = record
    return record


def timeframe_label() -> str:
    return state.current_timeframe()


def chart_height(base: int = 420) -> int:
    return 320 if state.display().get("compact") else base


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #
def store_scan(user_id: int, results, *, timeframe: str, market: str,
               notify: bool = True) -> dict:
    """Persist new signals and raise qualifying alerts. Returns a summary."""
    db = state.get_database()
    prefs = state.notifications()
    created = 0
    alerts = 0
    stored_rows: list[dict] = []
    for result in results:
        if not result.ok or result.signal is None:
            continue
        row, is_new = scanner_persist(db, user_id, result.signal)
        if row:
            stored_rows.append(row)
        if is_new:
            created += 1
            if notify and row:
                alert = scanner_alert(db, user_id, row, prefs, timeframe=timeframe)
                if alert:
                    alerts += 1
    st.session_state["scan_results"] = results
    st.session_state["scan_meta"] = {
        "market": market,
        "timeframe": timeframe,
        "at": config.utcnow().isoformat(timespec="seconds"),
        "count": len(results),
        "created": created,
        "alerts": alerts,
    }
    return {"created": created, "alerts": alerts, "stored": len(stored_rows)}


def scanner_persist(db: Database, user_id: int, signal):
    from scanner import persist_signal

    return persist_signal(db, user_id, signal)


def scanner_alert(db: Database, user_id: int, row: dict, prefs: dict, *, timeframe: str):
    from scanner import maybe_alert

    return maybe_alert(db, user_id, row, prefs, timeframe=timeframe)


def refresh_signal_outcomes(rows: list[dict], *, limit: int = 60) -> list[dict]:
    """Measure unresolved directional signals against later bars.

    Only signals that already have a stored TP/SL are evaluated, and only
    against bars that actually exist. Nothing is inferred beyond first touch.
    """
    db = state.get_database()
    cache: dict[tuple[str, str], object] = {}
    evaluated = 0
    for row in rows[:limit]:
        if row.get("label") not in {"BUY", "SELL"}:
            continue
        if (row.get("status") or "Open") != "Open":
            continue
        if row.get("tp") is None or row.get("sl") is None:
            continue
        key = (row["symbol"], row.get("timeframe") or config.DEFAULT_TIMEFRAME)
        if key not in cache:
            cache[key] = market_data.get_timeframe_history(
                key[0], key[1], allow_sample=False,
            )
        outcome = signals.evaluate_outcome(row, cache[key])
        if outcome:
            db.update_signal(int(row["id"]), outcome)
            row.update(outcome)
            evaluated += 1
    return rows


def signal_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    out = []
    for row in rows:
        out.append({
            "Symbol": row.get("symbol", ""),
            "Market": config.ENGINE_LABELS.get(row.get("market", ""), row.get("market", "")),
            "Signal": row.get("label", ""),
            "Timeframe": row.get("timeframe", ""),
            "Strength": row.get("strength", ""),
            "Quality": row.get("quality", 0),
            "Price": row.get("price"),
            "Entry ref": row.get("entry_ref"),
            "TP": row.get("tp"),
            "SL": row.get("sl"),
            "Result": signals.outcome_status_label(row),
            "Created (UTC)": (row.get("created_at") or "").replace("T", " ")[:16],
        })
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- #
# Economic calendar (recurring windows, explicitly not a live calendar)
# --------------------------------------------------------------------------- #
def _next_weekday(weekday: int, hour: int, minute: int, now: datetime | None = None) -> datetime:
    now = now or config.utcnow()
    delta = (weekday - now.date().weekday()) % 7
    candidate = datetime.combine(now.date() + timedelta(days=delta), time(hour, minute))
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def _next_nth_weekday(weekday: int, nth: int, hour: int, minute: int,
                      now: datetime | None = None) -> datetime:
    now = now or config.utcnow()
    year, month = now.year, now.month
    for _ in range(14):
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        day = 1 + offset + 7 * (nth - 1)
        if day <= monthrange(year, month)[1]:
            candidate = datetime(year, month, day, hour, minute)
            if candidate > now:
                return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1
    return now


def upcoming_events(days: int = 14, now: datetime | None = None) -> list[dict]:
    now = now or config.utcnow()
    events = [
        {
            "name": "London session opens",
            "when": _next_weekday(0, 8, 0, now),
            "schedule": "Monday–Friday, 08:00 UTC",
            "note": "Liquidity rises in European pairs.",
            "certainty": "Fixed schedule",
        },
        {
            "name": "New York session opens",
            "when": _next_weekday(0, 13, 30, now),
            "schedule": "Monday–Friday, 13:30 UTC",
            "note": "US data and equity-index activity cluster here.",
            "certainty": "Fixed schedule",
        },
        {
            "name": "London session closes",
            "when": _next_weekday(0, 16, 30, now),
            "schedule": "Monday–Friday, 16:30 UTC",
            "note": "Liquidity typically thins afterwards.",
            "certainty": "Fixed schedule",
        },
        {
            "name": "US non-farm payrolls",
            "when": _next_nth_weekday(4, 1, 13, 30, now),
            "schedule": "First Friday, 13:30 UTC (typical)",
            "note": "High-impact US labour release; spread and volatility risk.",
            "certainty": "Typical window",
        },
        {
            "name": "US CPI",
            "when": _next_nth_weekday(1, 2, 13, 30, now),
            "schedule": "Usually the second Tuesday, 13:30 UTC (typical)",
            "note": "Inflation release; exact date varies.",
            "certainty": "Typical window",
        },
        {
            "name": "FOMC decision",
            "when": None,
            "schedule": "Eight scheduled meetings a year",
            "note": "Dates are set by the Federal Reserve — confirm on the official calendar.",
            "certainty": "Check official calendar",
        },
        {
            "name": "ECB Governing Council",
            "when": None,
            "schedule": "Scheduled meetings",
            "note": "Confirm on the ECB official calendar; MNZ has no live calendar feed.",
            "certainty": "Check official calendar",
        },
    ]
    horizon = now + timedelta(days=days)
    visible = [e for e in events if e["when"] is None or e["when"] <= horizon]
    for event in visible:
        event["when_text"] = event["when"].strftime("%a %d %b · %H:%M") if event["when"] else "Varies"
        event["in_hours"] = (
            round((event["when"] - now).total_seconds() / 3600, 1) if event["when"] else None
        )
    return sorted(visible, key=lambda e: (e["when"] is None, e["when"] or now))


def events_frame(events: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Event": event["name"],
            "Next window (UTC)": event["when_text"],
            "Typical schedule": event["schedule"],
            "Certainty": event["certainty"],
            "Why it matters": event["note"],
        }
        for event in events
    ])


# --------------------------------------------------------------------------- #
# Misc formatting
# --------------------------------------------------------------------------- #
def finite(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def quote_row(results) -> pd.DataFrame:
    rows = []
    for result in results:
        metrics = (result.signal.metrics or {}) if result.signal else {}
        confirmations = metrics.get("confirmations")
        rows.append({
            "Instrument": result.symbol,
            "Name": result.name,
            "Signal": result.label,
            "Strength": result.strength,
            "Quality": result.quality,
            "Evidence": f"{confirmations}/4" if confirmations else "—",
            "Higher TF": metrics.get("higher_alignment", "—"),
            "Score": round(result.score, 2),
            "Price": result.price,
            "Change %": round(result.change_pct, 2) if result.change_pct is not None else None,
            "Data": (result.signal.data_quality if result.signal else "unavailable"),
            "Status": result.error or "OK",
        })
    return pd.DataFrame(rows)
