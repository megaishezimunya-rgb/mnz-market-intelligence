"""Public MNZ BOT website.

This is the signed-out surface: it explains the product and hosts Login and
Register. The authenticated application is rendered separately by ``app.py``.
Marketing copy only claims what the build actually does.
"""

from __future__ import annotations

from html import escape

import streamlit as st

import auth
import config
import state
import ui
from database.database import DatabaseUnavailable

NAV = ["Home", "Features", "Platform Compatibility", "Broker", "How It Works",
       "Pricing", "Academy", "Support", "Login", "Register"]


def _go(page: str) -> None:
    st.session_state["public_page"] = page
    st.rerun()


def _hero() -> None:
    st.markdown(
        '<div class="mnz-public mnz-hero">'
        '<div class="eyebrow">Multi-market intelligence · Demo-first</div>'
        '<h1>Read the market.<br>Keep the risk visible.</h1>'
        '<p>MNZ BOT scans forex, global indices and more across seven timeframes, turns '
        'indicators into one explainable signal, and lets you test it in a fully simulated '
        'account. Delayed public data, transparent rules, no broker connection.</p>'
        "</div>",
        unsafe_allow_html=True,
    )
    cta1, cta2, _ = st.columns([1.2, 1.2, 2.6])
    if cta1.button("Create a free demo account", key="home_cta_register", type="primary"):
        _go("Register")
    if cta2.button("Explore the platform", key="home_cta_features", type="secondary"):
        _go("Features")


def _stat_row(items: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div class="mnz-stat"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in items
    )
    st.markdown(f'<div class="mnz-stat-row">{cells}</div>', unsafe_allow_html=True)


def _features() -> None:
    cards = [
        ("SC", "Continuous Scanner", "Scan one instrument or a whole shortlist across M1–D1, with start, pause, resume and stop controls."),
        ("QS", "Signal Quality Score", "Every signal carries a 0–100 quality score built from component agreement, freshness and market regime."),
        ("SG", "MNZ Safety Guard", "Sample data, stale bars and missing history are flagged before a signal can be treated as usable."),
        ("SA", "Smart Alerts", "Threshold-based in-app alerts with a saved history — created only from current, directional signals."),
        ("PC", "Performance Centre", "Virtual equity, drawdown, monthly returns and per-market breakdowns from recorded demo data."),
        ("SL", "Strategy Lab", "Backtest the trend strategy with costs, compare periods and compare markets side by side."),
        ("TJ", "Trading Journal", "Attach notes and tags to simulated trades so decisions can be reviewed honestly."),
        ("EC", "Economic Calendar", "Recurring release windows for awareness, explicitly labelled as schedules rather than a live calendar."),
        ("MC", "Market Conditions", "Breadth of scanned BUY/SELL/WAIT readings, average quality and data freshness in one view."),
    ]
    html = "".join(
        f'<div class="mnz-feature"><div class="icon">{icon}</div><h4>{title}</h4><p>{body}</p></div>'
        for icon, title, body in cards
    )
    st.markdown(f'<div class="mnz-public"><div class="mnz-grid">{html}</div></div>',
                unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_home() -> None:
    _hero()
    _stat_row([
        ("Markets", "5 live + synthetics"),
        ("Timeframes", "M1 → D1"),
        ("Indicators", "RSI · MACD · EMA · SMA · BB · ATR · ADX"),
        ("Account", "100% simulated"),
    ])
    ui.section("What makes MNZ different", "built around honesty, not hype")
    _features()
    st.markdown(
        '<div class="mnz-public"><div class="mnz-band"><h2>Built on data you can audit</h2>'
        "<p>Every chart states its source, interval, bar count and last-bar timestamp. Missing data "
        "produces an explicit message instead of an estimate. Offline sample data is opt-in, "
        "watermarked, and can never produce a BUY or SELL signal.</p></div></div>",
        unsafe_allow_html=True,
    )


def page_features() -> None:
    st.markdown(
        '<div class="mnz-public mnz-hero"><div class="eyebrow">Features</div>'
        "<h1>One platform, six sections.</h1>"
        "<p>Home, Markets, Signals, Demo, MNZ AI and Settings. Secondary tools live inside the "
        "section they belong to, so the product stays calm instead of becoming a wall of buttons.</p>"
        "</div></div>", unsafe_allow_html=True,
    )
    _features()
    st.markdown(
        '<div class="mnz-public"><div class="mnz-band"><h2>MNZ AI, without the fiction</h2>'
        "<p>The assistant explains signals, indicators and market conditions using the exact bars "
        "that were fetched. It has no news feed and will not invent a price or a cause. Beginner and "
        "Professional explanation modes change the depth, never the facts.</p></div></div>",
        unsafe_allow_html=True,
    )


def page_compatibility() -> None:
    st.markdown(
        '<div class="mnz-public mnz-hero"><div class="eyebrow">Platform compatibility</div>'
        "<h1>Connected means verified. Nothing else counts.</h1>"
        "<p>MNZ only shows a connection as active when an authorised connection actually exists. "
        "No balance, account number or status is ever simulated for a third-party platform.</p>"
        "</div></div>", unsafe_allow_html=True,
    )
    rows = "".join(
        f"<tr><td>{p['name']}</td><td>{p['status']}</td><td>{p['detail']}</td></tr>"
        for p in config.PLANNED_PLATFORMS
    )
    st.markdown(
        '<div class="mnz-public"><table class="mnz-html-table" style="background:#151922">'
        "<thead><tr><th>Platform</th><th>Status</th><th>What that means</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    ui.section("Supported markets", "only what the connected feed can serve")
    for key, category in config.MARKETS.items():
        state_text = "Available" if category.available else "Awaiting a data connection"
        st.markdown(
            f'<div class="mnz-card"><strong>{category.name}</strong> · {state_text}'
            f'<div style="font-size:.8rem;color:#8C93A3;margin-top:.35rem">{category.note}</div></div>',
            unsafe_allow_html=True,
        )


def page_broker() -> None:
    st.markdown(
        '<div class="mnz-public mnz-hero"><div class="eyebrow">Broker due diligence</div>'
        "<h1>We check the licence before we name the broker.</h1>"
        "<p>MNZ is not a broker and earns nothing from one. This page records which "
        "entities could be verified, which could not, and what that means before you send "
        "anyone money.</p></div>",
        unsafe_allow_html=True,
    )
    ui.section("Our standard", "six checks before a name appears on this page")
    checks = "".join(
        f'<div class="mnz-feature"><div class="icon">{number}</div>'
        f"<h4>{escape(title)}</h4><p>{escape(body)}</p></div>"
        for number, title, body in config.BROKER_STANDARD
    )
    st.markdown(f'<div class="mnz-public"><div class="mnz-grid">{checks}</div></div>',
                unsafe_allow_html=True)

    ui.section(
        "What we found",
        f"checked {config.BROKER_VERIFICATION_DATE} · a licence check is not a recommendation",
    )
    colours = {
        "bad": config.PALETTE["red"],
        "warn": "#FFFFFF",
        "ok": config.PALETTE["green"],
        "info": config.PALETTE["muted"],
    }
    rows = "".join(
        f"<tr><td><strong>{escape(row['name'])}</strong></td>"
        f"<td>{escape(row['claim'])}</td>"
        f"<td>{escape(row['found'])}</td>"
        f'<td><span style="color:{colours.get(row["tone"], "#FFFFFF")};font-weight:600">'
        f"{escape(row['status'])}</span></td></tr>"
        for row in config.BROKER_REVIEW
    )
    st.markdown(
        '<div class="mnz-public"><div class="mnz-html-table-wrap">'
        '<table class="mnz-html-table" style="background:#151922;min-width:880px">'
        "<thead><tr><th>Entity</th><th>What is claimed</th><th>What we found</th>"
        f"<th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>"
        '<div style="font-size:.72rem;color:#5B657A;line-height:1.7;margin-top:.7rem;'
        f'max-width:90ch">{escape(config.BROKER_METHOD)}</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="mnz-public"><div class="mnz-band">'
        "<h2>Risk notice: derivatives can cost more than your deposit</h2>"
        "<p>CFDs and OTC derivatives are leveraged. You can lose your entire balance and, "
        "on some account types, owe more than you deposited. Your contract is with the "
        "counterparty named in the client agreement — not with the platform you log in "
        "to, and not with MNZ. A licence regulates conduct: it does not insure a deposit, "
        "guarantee a withdrawal, or make a strategy profitable.</p>"
        "<p>Profit screenshots are not a track record. They leave out deposits, open "
        "drawdown, lot escalation and the accounts that did not survive. If someone shows "
        "you results, ask for a verified third-party statement with its age and its "
        "maximum drawdown.</p></div></div>",
        unsafe_allow_html=True,
    )

    ui.section("Verify it yourself", "five minutes, before any deposit")
    steps = [
        ("01", "Search the register",
         "fsca.co.za → Regulated entities → Financial Services Providers. Search the FSP "
         "number and read the legal name printed beside it."),
        ("02", "Match the entity, not the badge",
         "The name beside the number must be the company in your client agreement. "
         "\"Regulated by\" with no matching entity name is a marketing line."),
        ("03", "Ask for the appointment",
         "If a firm acts under someone else's licence, request the juristic "
         "representative appointment in writing and check it against the register."),
        ("04", "Check the counterparty and the exit",
         "Confirm who your contract is with, where client funds are held, and what the "
         "complaint route is if a withdrawal stalls. The FSCA call centre is "
         "0800 20 37 22."),
    ]
    html = "".join(
        f'<div class="mnz-feature"><div class="icon">{number}</div>'
        f"<h4>{escape(title)}</h4><p>{escape(body)}</p></div>"
        for number, title, body in steps
    )
    st.markdown(f'<div class="mnz-public"><div class="mnz-grid">{html}</div></div>',
                unsafe_allow_html=True)

    st.markdown(
        '<div class="mnz-public"><div class="mnz-band">'
        "<h2>No referral links. No partner codes. No commission.</h2>"
        "<p>There is no affiliate link, introducing-broker code, tracked sign-up or paid "
        "placement anywhere on this page or in MNZ. No broker paid for a mention and none "
        "of these names earns us anything. If that ever changes, the disclosure will appear "
        "at the top of this page in the same size text as the claim, above the "
        "verification date, before any link is added.</p></div></div>",
        unsafe_allow_html=True,
    )


def page_how() -> None:
    st.markdown(
        '<div class="mnz-public mnz-hero"><div class="eyebrow">How it works</div>'
        "<h1>From raw bars to a simulated decision.</h1>"
        "<p>No black boxes. Each step below maps to a screen you can inspect.</p></div></div>",
        unsafe_allow_html=True,
    )
    steps = [
        ("01", "Fetch verified bars", "MNZ pulls delayed OHLCV history for the instrument and timeframe, then checks freshness and quality."),
        ("02", "Measure the market", "SMA, EMA, RSI, MACD, Bollinger Bands, ATR and ADX are computed locally from those bars."),
        ("03", "Weighted signal", "Trend, momentum, RSI and structure are weighted per market into one score and a BUY/SELL/WAIT label."),
        ("04", "Quality and safety", "Agreement, freshness and volatility produce a 0–100 quality score; the Safety Guard can veto unusable data."),
        ("05", "Simulate", "Open a virtual position with TP/SL and a risk-based size across 1, 3 or 5 slots. Measure the outcome, review it, journal it."),
    ]
    html = "".join(
        f'<div class="mnz-feature"><div class="icon">{number}</div><h4>{title}</h4><p>{body}</p></div>'
        for number, title, body in steps
    )
    st.markdown(f'<div class="mnz-public"><div class="mnz-grid">{html}</div></div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="mnz-public"><div class="mnz-band"><h2>What MNZ will not do</h2>'
        "<p>It will not invent prices, promise returns, claim a broker connection that does not "
        "exist, or present a simulated result as a live one. Automated execution is disabled by "
        "design.</p></div></div>", unsafe_allow_html=True,
    )


def page_pricing() -> None:
    st.markdown(
        '<div class="mnz-public mnz-hero"><div class="eyebrow">Pricing</div>'
        "<h1>Demo access is free.</h1>"
        "<p>Billing is not implemented in this build. The paid tiers below describe planned "
        "packaging and are not purchasable — every account created today receives the full demo "
        "experience at no cost.</p></div></div>", unsafe_allow_html=True,
    )
    tiers = [
        ("Starter", "$0", "Available now", ["Full demo application", "5 markets + 7 timeframes",
                                            "Signals, scorer and Safety Guard", "Virtual $100 account"], False),
        ("Pro", "Planned", "Not yet available", ["Everything in Starter", "More watchlists and deeper history",
                                                 "Priority alert rules", "Planned MT5/Razor compatibility"], True),
        ("Desk", "Planned", "Not yet available", ["Everything in Pro", "Team workspaces",
                                                  "Exportable research reports", "Planned API access"], False),
    ]
    columns = st.columns(3)
    for column, (tier, price, note, perks, featured) in zip(columns, tiers):
        with column:
            items = "".join(f"<li>{perk}</li>" for perk in perks)
            st.markdown(
                f'<div class="mnz-price{" featured" if featured else ""}">'
                f'<div class="tier">{tier}</div><div class="amount">{price}</div>'
                f'<div style="font-size:.72rem;color:#8C93A3">{note}</div>'
                f"<ul>{items}</ul></div>",
                unsafe_allow_html=True,
            )
    st.markdown(
        '<div class="mnz-public"><div class="mnz-band"><h2>Honest billing status</h2>'
        "<p>There is no checkout, subscription or entitlement system in this version, so nothing "
        "here can charge you. When billing is added, these tiers will be updated before any payment "
        "flow is enabled.</p></div></div>", unsafe_allow_html=True,
    )


def page_academy() -> None:
    st.markdown(
        '<div class="mnz-public mnz-hero"><div class="eyebrow">Academy</div>'
        "<h1>Learn the language of the platform.</h1>"
        "<p>Short, accurate explanations of what MNZ measures. Educational only — not advice.</p>"
        "</div></div>", unsafe_allow_html=True,
    )
    from ai import INDICATOR_HELP

    for name, text in INDICATOR_HELP.items():
        with st.expander(name.upper()):
            st.write(text)
    with st.expander("RISK AND SIMULATION"):
        st.write(
            "MNZ is a simulator. Virtual balances, positions and results are not real money. "
            "A stop loss in MNZ is a simulated level, not an order at a broker. Position sizing in "
            "the demo derives from virtual equity and the distance to the simulated stop."
        )
    with st.expander("READING A SIGNAL QUALITY SCORE"):
        st.write(
            "Quality combines how much the weighted components agree, how fresh the bars are, how "
            "many bars are available and the volatility regime. A high score means the reading is "
            "internally consistent — not that it will be correct. Sample data caps quality at 30."
        )


def page_support() -> None:
    st.markdown(
        '<div class="mnz-public mnz-hero"><div class="eyebrow">Support</div>'
        "<h1>Answers, without a ticket queue.</h1>"
        "<p>Support staffing is not yet part of this build, so there is no fake contact form. "
        "These answers cover the questions the platform can resolve itself.</p></div></div>",
        unsafe_allow_html=True,
    )
    faqs = [
        ("Is my demo balance real?", "No. Every balance, position and result is virtual. MNZ has no broker connection."),
        ("Why does a chart say SAMPLE DATA?", "The live provider could not be reached and the opt-in offline fallback is enabled. Sample data never produces an actionable signal."),
        ("Can I connect MT5 or Razor Markets?", "Not yet. Both are planned compatibility targets and no connection exists."),
        ("Why is a signal WAIT?", "The weighted score is inside the ±0.28 threshold, history is insufficient, or data quality blocked a directional label."),
        ("Where is my data stored?", "In the application database, scoped to your account: PostgreSQL when the host configures it, otherwise a local SQLite file that may reset on redeploy."),
        ("Is MNZ financial advice?", "No. It is an educational analysis and simulation tool."),
    ]
    for question, answer in faqs:
        with st.expander(question):
            st.write(answer)
    st.markdown(
        '<div class="mnz-public"><div class="mnz-band"><h2>Still stuck?</h2>'
        "<p>Sign in and open <strong>Settings → Help Centre</strong>, or ask <strong>MNZ AI</strong> "
        "about the screen you are on. Those answers are tied to the data actually loaded.</p>"
        "</div></div>", unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def _storage_down(exc: Exception, page: str) -> None:
    """Log the real failure and show a short retry instead of a traceback."""
    state.log_storage_error(exc)
    ui.storage_unavailable(f"{page}_storage_retry", f"_mnz_{page}_retry")


def page_login() -> None:
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown(
            '<div class="mnz-public mnz-hero"><div class="eyebrow">Welcome back</div>'
            "<h1>Sign in to MNZ BOT.</h1>"
            "<p>Your signals, demo positions, settings and alert history are stored against your "
            "account.</p></div>", unsafe_allow_html=True,
        )
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="you@example.com", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Sign in")
        retry = st.session_state.pop("_mnz_login_retry", False)
        if submitted or retry:
            wait = auth.throttle.retry_after(email)
            if wait:
                st.warning(
                    f"Too many failed sign-in attempts for this email. "
                    f"Try again in {wait} second(s)."
                )
            else:
                try:
                    user, error = state.auth().authenticate(email, password)
                    token = state.auth().start_session(int(user["id"])) if user and not error else None
                except DatabaseUnavailable as exc:
                    _storage_down(exc, "login")
                else:
                    if error or user is None:
                        wait = auth.throttle.record_failure(email)
                        st.error(error or "Sign-in failed.")
                        if wait:
                            st.warning(
                                f"New attempts for this email are paused for {wait} second(s) "
                                "after repeated failures."
                            )
                        if not state.storage_is_durable():
                            st.warning(
                                "This deployment is still on temporary storage, so an account "
                                "created before the last restart no longer exists and cannot "
                                "sign in. Register again to get a fresh demo account; accounts "
                                "only stay permanent once the owner adds the DATABASE_URL secret."
                            )
                    elif token:
                        auth.throttle.clear(email)
                        state.sign_in(user, token)
                        st.session_state["mnz_page"] = "Home"
                        st.rerun()
        st.caption("No account yet? Use **Register** above.")
    with right:
        st.markdown(
            '<div class="mnz-card" style="margin-top:2.5rem">'
            "<strong>Demo-only platform</strong>"
            '<p style="font-size:.82rem;color:#AEB6C6;line-height:1.6;margin-top:.5rem">'
            "MNZ never asks for brokerage credentials, card details or API keys. The only "
            "credentials it stores are the email and password for this local account.</p></div>",
            unsafe_allow_html=True,
        )


def page_register() -> None:
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown(
            '<div class="mnz-public mnz-hero"><div class="eyebrow">Create an account</div>'
            "<h1>Start with a $100 virtual account.</h1>"
            "<p>Free demo access. No card, no broker login, no execution permissions.</p></div>",
            unsafe_allow_html=True,
        )
        with st.form("register_form"):
            name = st.text_input("Name", placeholder="Your name", key="register_name")
            email = st.text_input("Email", placeholder="you@example.com", key="register_email")
            password = st.text_input("Password", type="password",
                                     help="At least 8 characters.", key="register_password")
            confirm = st.text_input("Confirm password", type="password",
                                    key="register_confirm")
            accepted = st.checkbox(
                "I understand MNZ is a demo and educational tool, not financial advice.",
                key="register_accepted",
            )
            submitted = st.form_submit_button("Create demo account")
        retry = st.session_state.pop("_mnz_register_retry", False)
        if submitted or retry:
            wait = auth.throttle.retry_after(email)
            if password != confirm:
                st.error("The two passwords do not match.")
            elif not accepted:
                st.error("Please confirm you understand this is a demo and educational tool.")
            elif wait:
                st.warning(
                    f"Too many failed attempts for this email. Try again in {wait} second(s)."
                )
            else:
                try:
                    user, problems = state.auth().register(name, email, password)
                    token = (
                        state.auth().start_session(int(user["id"]))
                        if user is not None and not problems else None
                    )
                except DatabaseUnavailable as exc:
                    _storage_down(exc, "register")
                else:
                    if problems:
                        for problem in problems:
                            st.error(problem)
                        if auth.valid_email(email):
                            wait = auth.throttle.record_failure(email)
                            if wait:
                                st.warning(
                                    f"New registration attempts for this email are paused for "
                                    f"{wait} second(s) after repeated failures."
                                )
                    elif user is not None and token:
                        auth.throttle.clear(email)
                        state.sign_in(user, token)
                        st.session_state["mnz_page"] = "Home"
                        st.rerun()
    with right:
        st.markdown(
            '<div class="mnz-card" style="margin-top:2.5rem"><strong>What you get</strong>'
            '<ul style="font-size:.82rem;color:#AEB6C6;line-height:1.8;margin:.6rem 0 0 0;padding-left:1.1rem">'
            "<li>$100 simulated starting balance</li>"
            "<li>Scanner across 5 live markets, M1–D1</li>"
            "<li>Signals, quality scores and Safety Guard</li>"
            "<li>1, 3 or 5 demo position slots</li>"
            "<li>Journal, alerts and performance reports</li>"
            "</ul></div>", unsafe_allow_html=True,
        )


RENDERERS = {
    "Home": page_home,
    "Features": page_features,
    "Platform Compatibility": page_compatibility,
    "Broker": page_broker,
    "How It Works": page_how,
    "Pricing": page_pricing,
    "Academy": page_academy,
    "Support": page_support,
    "Login": page_login,
    "Register": page_register,
}


def render() -> None:
    """Render the public site."""
    page = st.session_state.get("public_page", "Home")
    if page not in RENDERERS:
        page = "Home"

    st.markdown(
        '<div class="mnz-public"><div class="topbar">'
        '<div class="wordmark"><span class="dot"></span>MNZ BOT</div>'
        '<div style="font-size:.68rem;letter-spacing:.14em;color:#8C93A3;text-transform:uppercase">'
        "Market intelligence · demo mode</div></div></div>",
        unsafe_allow_html=True,
    )

    nav = st.pills(
        "Public navigation", NAV, selection_mode="single",
        default=page, key="public_nav_pills", label_visibility="collapsed",
    )
    if nav and nav != page:
        st.session_state["public_page"] = nav
        st.rerun()

    if page in ("Login", "Register"):
        status = state.storage_state()
        if status == "sqlite":
            ui.temporary_storage_notice()
        elif status == "unavailable":
            # Say it before they type, not only after a failed attempt.
            ui.storage_unavailable(f"{page.lower()}_storage_retry")

    RENDERERS[page]()

    st.markdown(
        f'<div class="mnz-public"><div class="fine">{config.DISCLAIMER}<br><br>'
        f"{config.BRAND} v{config.VERSION} · Demo-only · No broker connection.</div></div>",
        unsafe_allow_html=True,
    )
