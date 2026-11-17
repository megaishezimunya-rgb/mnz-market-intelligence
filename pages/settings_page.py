"""Settings: profile, notifications, display, demo safety, help and compatibility."""

from __future__ import annotations

from html import escape as html_escape

import pandas as pd
import streamlit as st

import ai
import config
import notifications
import state
import ui
from data import market_data
from database.database import DELIVERY_HISTORY_LIMIT


def _profile_tab() -> None:
    user = state.require_user()
    profile = state.profile()
    ui.section("User profile", "stored against your account")
    with st.form("profile_form"):
        name = st.text_input("Name", value=profile.get("name") or user["name"])
        email = st.text_input("Email", value=user["email"], disabled=True,
                              help="Email changes are not supported in this build.")
        experience = st.selectbox(
            "Experience level", ["Beginner", "Professional"],
            index=["Beginner", "Professional"].index(profile.get("experience", "Beginner"))
            if profile.get("experience") in {"Beginner", "Professional"} else 0,
        )
        saved = st.form_submit_button("Save profile")
    if saved:
        if len(name.strip()) < 2:
            st.error("Enter a name of at least two characters.")
        else:
            state.get_database().update_user(int(user["id"]), name=name.strip())
            state.save_profile({"name": name.strip(), "experience": experience})
            state.refresh_user()
            ui.flash("Profile saved.")
            st.rerun()

    ui.kpi_row([
        {"label": "Account", "value": "Starter (demo)", "note": "Billing is not implemented"},
        {"label": "Member since", "value": (user.get("created_at") or "").replace("T", " ")[:10]},
        {"label": "Demo account id", "value": f"#{user.get('account_id')}"},
        {"label": "Data isolation", "value": "Per user"},
    ])
    st.caption("Your password is stored as a salted PBKDF2-SHA256 hash, never in plain text.")


def _notifications_tab() -> None:
    user = state.require_user()
    prefs = state.notifications()
    ui.section("Notifications", "which Smart Alerts are created and saved")
    with st.form("notifications_form"):
        enabled = st.checkbox("Enable Smart Alerts", value=bool(prefs.get("enabled", True)))
        in_app = st.checkbox("Create in-app notifications", value=bool(prefs.get("in_app", True)))
        strength = st.selectbox(
            "Minimum signal strength", config.ALERT_STRENGTHS,
            index=config.ALERT_STRENGTHS.index(prefs.get("min_strength", "Moderate")),
        )
        quality = st.slider("Minimum quality score", 0, 100,
                            int(prefs.get("min_quality", config.ALERT_MIN_QUALITY)), 5)
        telegram = st.checkbox(
            "Also send alerts to Telegram",
            value=bool(prefs.get("telegram", False)),
            help="Requires the server to have MNZ_TELEGRAM_BOT_TOKEN and MNZ_TELEGRAM_CHAT_ID set.",
        )
        saved = st.form_submit_button("Save notification preferences")
    if saved:
        state.save_notifications({
            "enabled": enabled, "in_app": in_app,
            "min_strength": strength, "min_quality": int(quality),
            "telegram": bool(telegram),
        })
        ui.flash("Notification preferences saved.")
        st.rerun()
    delivery = notifications.delivery_status()
    if delivery["telegram_configured"]:
        ui.notice(
            "Telegram delivery is configured on this server. Messages are sent for alerts that "
            "pass your thresholds and are still saved in-app if delivery fails."
        )
    else:
        ui.notice(
            "Telegram delivery is not configured on this server. Set "
            f"{notifications.TELEGRAM_TOKEN_ENV} and {notifications.TELEGRAM_CHAT_ENV} as app "
            "secrets, then re-enable the option above. In-app alerts work without them."
        )

    report = notifications.delivery_report()
    ui.section("Delivery status", "server-wide · updated after every Telegram attempt")
    last = report["last"]
    ui.kpi_row([
        {"label": "Last result", "value": "Never attempted" if last is None
         else ("Delivered" if last["ok"] else "Failed"),
         "trend": 0 if last is None else (1 if last["ok"] else -1)},
        {"label": "Last attempt", "value": "—" if last is None
         else last["at"].replace("T", " ")},
        {"label": "Sent / failed", "value": f"{report['sent']} / {report['failed']}"},
        {"label": "Queued now", "value": str(report["pending"]),
         "note": "waiting for the background sender"},
    ])
    if last is not None and not last["ok"]:
        follows = (
            "This was a manual test, so no alert was affected."
            if last.get("alert_id") == "test"
            else "The alert itself is still saved in Alerts; only the Telegram copy was not sent."
        )
        ui.notice(f"Last delivery failed: {last['error'] or 'unknown error'} {follows}", "warn")
    elif last is None:
        st.caption(
            "No Telegram message has been attempted since this server process started. "
            "Counts reset when the app restarts."
        )
    else:
        st.caption(
            f"Alert #{last['alert_id']} was delivered. Counts are for this server process and "
            "reset when the app restarts."
            if last.get("alert_id") else
            "Delivery counters are for this server process and reset when the app restarts."
        )

    if st.button("Send test message", key="tg_send_test", type="secondary"):
        with st.spinner("Sending test message…"):
            st.session_state["tg_test_outcome"] = notifications.send_test_message(
                int(user["id"])
            )
        st.rerun()

    outcome = st.session_state.get("tg_test_outcome")
    if outcome:
        if outcome.get("ok"):
            st.success(
                "Test message delivered. Check the chat configured for this server. "
                "No market signal was attached."
            )
        elif outcome.get("queued"):
            st.info(outcome.get("error", "Test message queued; the result will appear above."))
        else:
            st.warning(f"Test message not sent: {outcome.get('error') or 'unknown error'}")

    history = state.get_database().list_delivery_attempts(int(user["id"]), limit=8)
    ui.section(
        "Recent delivery attempts",
        f"last 8 for this account · newest {DELIVERY_HISTORY_LIMIT} kept",
    )
    if not history:
        st.caption("No delivery attempts recorded for this account yet.")
    else:
        frame = pd.DataFrame([
            {
                "Time": (row["created_at"] or "").replace("T", " "),
                "Result": "Delivered" if row["ok"] else "Failed",
                "Alert": "Manual test" if row["alert_id"] == "test"
                else (f"#{row['alert_id']}" if row["alert_id"] else "—"),
                "Error": row["error"] or "—",
            }
            for row in history
        ])
        ui.html_table(frame)
        st.caption("Stored in the database, so failures remain visible after a restart.")
    ui.notice(
        "Alerts are only created for new directional signals that meet these thresholds and come "
        "from current data. Sample or stale readings never alert, and the number of alerts per day "
        "is capped."
    )


def _display_tab() -> None:
    display = state.display()
    ui.section("Display preferences", "applies across the platform")
    categories = [key for key in config.MARKETS]
    labels = {key: config.MARKETS[key].name for key in categories}
    with st.form("display_form"):
        timeframe = st.selectbox(
            "Default timeframe", config.TIMEFRAME_ORDER,
            index=config.TIMEFRAME_ORDER.index(display.get("timeframe", config.DEFAULT_TIMEFRAME))
            if display.get("timeframe") in config.TIMEFRAME_ORDER else config.TIMEFRAME_ORDER.index(config.DEFAULT_TIMEFRAME),
        )
        chosen = st.multiselect(
            "Monitored market categories",
            categories,
            default=[key for key in display.get("categories", []) if key in categories],
            format_func=lambda key: labels[key],
        )
        compact = st.checkbox("Compact charts", value=bool(display.get("compact", False)))
        sample = st.checkbox(
            "Allow clearly-labelled offline sample data when the provider is unavailable",
            value=bool(display.get("allow_sample", False)),
            help="Sample data is generated locally, watermarked, and can never produce a BUY or SELL signal.",
        )
        saved = st.form_submit_button("Save display preferences")
    if saved:
        state.save_display({
            "timeframe": timeframe,
            "categories": chosen or ["forex", "indices"],
            "compact": compact,
            "allow_sample": sample,
        })
        ui.flash("Display preferences saved.")
        st.rerun()
    if sample:
        ui.notice(
            "Offline sample data is enabled. Charts will be watermarked and the Safety Guard will "
            "block directional signals while it is in use.",
            "warn",
        )


def _demo_tab(account) -> None:
    safety = state.safety()
    ui.section("Demo account and Safety Guard", "virtual money only")
    ui.kpi_row([
        {"label": "Starting balance", "value": ui.money(account.starting_balance)},
        {"label": "Current equity", "value": ui.money(account.equity({}))},
        {"label": "Open positions", "value": str(len(account.open_positions()))},
        {"label": "Mode", "value": "DEMO"},
    ])
    with st.form("safety_form"):
        slots = st.radio("Demo entry slots", config.DEMO_SLOT_CHOICES,
                         index=config.DEMO_SLOT_CHOICES.index(state.max_demo_slots()),
                         horizontal=True)
        risk = st.slider("Risk per simulated trade (% of virtual equity)", 0.25, 5.0,
                         float(safety.get("risk_pct", config.DEMO_RISK_PCT)), 0.25)
        saved = st.form_submit_button("Save demo settings")
    if saved:
        state.save_safety({"max_slots": int(slots), "risk_pct": float(risk)})
        ui.flash("Demo settings saved.")
        st.rerun()
    st.caption(
        "A slot is occupied only after a simulated position is successfully created. "
        "The risk setting sizes entries from the distance to the simulated stop."
    )

    ui.section("Reset demo account", "deletes simulated trades and equity history")
    confirm = st.checkbox("I understand the reset deletes all my simulated positions and history.")
    if st.button("Reset demo account", key="settings_reset_demo", type="secondary"):
        if not confirm:
            st.error("Tick the confirmation box first.")
        else:
            state.get_database().reset_account(account.id)
            state.reload_account()
            ui.flash("Demo account reset to its starting balance. Saved signals were kept.")
            st.rerun()


def _help_tab() -> None:
    ui.section("Help Centre", "how the platform works")
    with st.expander("How the scanner and continuous mode work"):
        st.write(
            "Manual scans fetch the selected instruments once. Continuous scanning repeats the "
            "shortlist on a timer while the Markets tab stays open; Start, Pause, Resume and Stop "
            "control it. Signals are persisted once per bar, so repeated scans do not duplicate "
            "history."
        )
    with st.expander("How signals are produced"):
        st.write(
            "Trend structure, MACD momentum, RSI and market structure are weighted per market into "
            "a score between -1 and +1. Above +0.28 is BUY, below -0.28 is SELL, otherwise WAIT. "
            "Quality (0–100) combines agreement, freshness, history length and volatility. Sample "
            "data caps quality at 30 and cannot be directional."
        )
    with st.expander("Why a signal shows WAIT"):
        st.write(
            "The score is inside the threshold, there are fewer than 60 bars, the bars are stale, "
            "or the data is sample data. The card always states which."
        )
    with st.expander("Demo accounting model"):
        st.write(
            "cash = starting balance − entry costs + realised gross P&L − exit costs. Equity = cash "
            "+ unrealised gross P&L. Notional is not deducted; simulated notional is capped at 10× "
            "virtual equity. TP/SL use ATR-based levels and are checked against the latest delayed "
            "price when you visit the Demo page."
        )
    with st.expander("Why MT5 and Razor Markets show as planned"):
        st.write(
            "No authorised connection exists, so no connection status, balance or account number is "
            "displayed for them. MNZ cannot place orders anywhere."
        )
    st.caption("Indicator definitions are also available in MNZ AI and the public Academy.")

    for name, text in ai.INDICATOR_HELP.items():
        with st.expander(f"Indicator · {name.upper()}"):
            st.write(text)


def _compatibility_tab() -> None:
    ui.section("Platform compatibility", "active means verified, nothing else")
    frame = pd.DataFrame([
        {"Platform": p["name"], "Status": p["status"], "Detail": p["detail"]}
        for p in config.PLANNED_PLATFORMS
    ])
    ui.html_table(frame, min_width=560)
    ui.notice(
        "Only <strong>Yahoo Finance</strong> is active, and it is a read-only delayed data feed — "
        "not a broker. MT5, Razor Markets and Deriv are planned targets with no connection, no "
        "credentials and no balances shown.",
        "warn",
    )
    ui.section("Device support", "one backend, two layouts")
    ui.html_table(pd.DataFrame([
        {"Platform": "Desktop web", "Experience": "Collapsible sidebar, wide chart workspace, multi-column dashboard"},
        {"Platform": "Mobile web", "Experience": "Bottom navigation, stacked cards, touch-sized controls"},
        {"Platform": "Native mobile app", "Experience": "Not available in this build"},
    ]), min_width=520)


def _data_tab(account) -> None:
    ui.section("Market data connection", "monitored, not assumed")
    provider = market_data.provider_status()
    health = state_ping = st.session_state.get("mnz_connection")
    if health:
        ui.kpi_row([
            {"label": "Probe", "value": "Connected" if health["ok"] else "Failed",
             "note": f"{health['latency_ms']} ms"},
            {"label": "Checked", "value": health["checked_at"][11:19] + " UTC"},
            {"label": "Last success", "value": (provider.get("last_success_at") or "—")[11:19]},
            {"label": "Failures", "value": str(provider.get("failures", 0))},
        ])
    else:
        ui.notice("No connection probe has run in this session.")
    c1, c2 = st.columns(2)
    if c1.button("Check connection now", key="settings_ping", type="secondary"):
        from pages import common

        common.connection_health(force=True)
        st.rerun()
    if c2.button("Clear data cache", key="settings_cache", type="secondary"):
        market_data.clear_cache()
        ui.flash("Cached provider responses cleared.")
        st.rerun()
    st.caption(f"Provider: {config.DATA_SOURCE_NAME} · cache TTL {config.DATA_CACHE_TTL_SECONDS}s · "
               f"delayed feed. {config.TIME_SOURCE_NOTE}")

    ui.section("Account and data", "your records only")
    user = state.require_user()
    database = state.get_database()
    durable = database.backend == "PostgreSQL"
    storage_label = "PostgreSQL (durable)" if durable else "SQLite (temporary on this host)"
    rows = [
        {"Item": "Email", "Value": user["email"]},
        {"Item": "User id", "Value": f"#{user['id']}"},
        {"Item": "Demo account", "Value": f"#{account.id} · {account.name}"},
        {"Item": "Signals stored", "Value": str(len(state.get_database().list_signals(int(user["id"]), limit=5000)))},
        {"Item": "Simulated trades", "Value": str(len(account.all_positions()))},
        {"Item": "Journal entries", "Value": str(len(state.get_database().list_journal(int(user["id"]))))},
        {"Item": "Storage", "Value": storage_label},
    ]
    ui.html_table(pd.DataFrame(rows), min_width=420)
    if durable:
        st.caption(
            "PostgreSQL storage is active, so accounts, demo positions and delivery history "
            "survive restarts and redeploys."
        )
    else:
        st.caption(
            "This server is using the local SQLite file, which Streamlit Community Cloud wipes on "
            "restart or redeploy. Add a PostgreSQL connection string as the DATABASE_URL secret "
            "to keep accounts, demo positions and delivery history."
        )

    ui.section("Session", "")
    if st.button("Sign out", key="settings_logout", type="secondary"):
        state.logout()
        st.rerun()
    ui.notice(
        "MNZ never requests brokerage credentials, API keys or card details. "
        "Automated execution is disabled in this build.",
        "warn",
    )


def render() -> None:
    state.require_user()
    account = state.get_account()
    ui.page_header(
        "Settings",
        "Profile, notification thresholds, display, demo safety, help and honest platform "
        "compatibility.",
        tag="ACCOUNT",
    )
    tabs = st.tabs([
        "Profile", "Notifications", "Display", "Demo & Safety",
        "Help Centre", "Compatibility", "Data & Account",
    ])
    with tabs[0]:
        _profile_tab()
    with tabs[1]:
        _notifications_tab()
    with tabs[2]:
        _display_tab()
    with tabs[3]:
        _demo_tab(account)
    with tabs[4]:
        _help_tab()
    with tabs[5]:
        _compatibility_tab()
    with tabs[6]:
        _data_tab(account)
    ui.footer()
