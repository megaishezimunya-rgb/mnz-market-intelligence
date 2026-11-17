"""Markets: scanner, chart workspace, Strategy Lab, conditions and calendar."""

from __future__ import annotations

from html import escape as html_escape

import numpy as np
import pandas as pd
import streamlit as st

import config
import scanner
import state
import ui
from analysis import backtesting, indicators
from analysis.signals import Signal
from data import market_data
from pages import common

CATEGORY_KEYS = list(config.MARKETS)


def _selected_market() -> str:
    key = st.session_state.get("markets_category", "forex")
    return key if key in config.MARKETS else "forex"


def _timeframe() -> str:
    value = st.session_state.get("markets_tf")
    if value in config.TIMEFRAMES:
        if value != state.display().get("timeframe"):
            state.save_display({"timeframe": value})
        return value
    return state.current_timeframe()


def _run_scan(category_key: str, symbols: list[str], timeframe: str, *, force: bool = True) -> dict:
    with st.spinner(f"Scanning {len(symbols)} instrument(s) on {timeframe}…"):
        results = scanner.scan_many(
            symbols, category_key, timeframe,
            allow_sample=state.allow_sample_data(), force_refresh=force,
        )
    return common.store_scan(state.require_user()["id"], results, timeframe=timeframe,
                             market=category_key)


def _results_table(results) -> None:
    if not results:
        ui.notice("No scan results in this session yet. Press Scan instrument or Scan all.")
        return
    frame = common.quote_row(results)
    ui.html_table(frame, numeric=["Quality", "Score", "Price", "Change %"])
    st.caption(
        "Signals are stored once per bar. WAIT means the weighted score is inside the "
        f"±{config.SIGNAL_BUY_THRESHOLD:.2f} threshold or data quality blocked a direction."
    )


def _continuous_panel(category_key: str, category) -> None:
    cfg = st.session_state.setdefault("scanner", {
        "status": "Stopped", "market": category_key,
        "timeframe": _timeframe(), "interval": 30,
    })
    if cfg.get("market") != category_key:
        cfg.update({"market": category_key, "status": "Stopped"})

    ui.section("Continuous scanner", "scans the shortlist on a timer while this tab is open")
    if not category.available:
        ui.notice(
            f"{category.name} has no connected data source. Continuous scanning is unavailable.",
            "warn",
        )
        return

    shortlist = config.SCAN_SHORTLIST.get(category_key, [i.symbol for i in category.instruments[:4]])
    status = cfg.get("status", "Stopped")
    label = {"Running": "Running", "Paused": "Paused", "Stopped": "Stopped"}.get(status, status)
    st.markdown(
        f'<div class="mnz-card" style="display:flex;gap:.8rem;align-items:center;flex-wrap:wrap">'
        f'<span class="mnz-pill {"strong" if status == "Running" else "wait"}">{label}</span>'
        f'<span style="font-size:.82rem;color:#AEB6C6">Shortlist: '
        f'{", ".join(shortlist)} · {_timeframe()}</span></div>',
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    if col1.button("Start", key="scan_start", type="primary", disabled=status == "Running"):
        cfg.update({"status": "Running", "timeframe": _timeframe()})
        st.rerun()
    if col2.button("Pause", key="scan_pause", type="secondary", disabled=status != "Running"):
        cfg.update({"status": "Paused"})
        st.rerun()
    if col3.button("Resume", key="scan_resume", type="secondary", disabled=status != "Paused"):
        cfg.update({"status": "Running"})
        st.rerun()
    if col4.button("Stop", key="scan_stop", type="secondary", disabled=status == "Stopped"):
        cfg.update({"status": "Stopped"})
        st.rerun()
    interval = col5.selectbox("Interval (s)", [15, 30, 60], index=[15, 30, 60].index(int(cfg.get("interval", 30))),
                              key="scanner_interval")
    cfg["interval"] = int(interval)

    if status == "Running":
        @st.fragment(run_every=int(cfg["interval"]))
        def _live_tick():
            summary = _run_scan(category_key, shortlist, cfg["timeframe"], force=True)
            st.caption(
                f"Tick {config.utcnow().strftime('%H:%M:%S')} UTC · "
                f"{summary['created']} new signal(s) · {summary['alerts']} alert(s)"
            )
            _results_table(st.session_state.get("scan_results"))

        _live_tick()
    else:
        _results_table(st.session_state.get("scan_results"))


def _chart_tab(category_key: str, category, symbol: str, name: str, timeframe: str) -> None:
    data = market_data.get_timeframe_history(
        symbol, timeframe, allow_sample=state.allow_sample_data(),
    )
    settings = config.ENGINE_STRATEGY_DEFAULTS.get(category_key, config.StrategySettings())
    if not data.ok:
        ui.empty_state(
            f"{name} could not be loaded: {data.error}",
            "Try another timeframe or instrument, refresh, or enable offline sample data in Settings.",
        )
        if st.button("Retry data", key="chart_retry"):
            market_data.clear_cache()
            st.rerun()
        return

    snapshot = indicators.snapshot(
        data.frame, fast=settings.fast_ma, slow=settings.slow_ma, rsi_period=settings.rsi_period
    )
    change = None
    if data.bars >= 2:
        previous = float(data.frame["Close"].iloc[-2])
        change = (float(data.last_price) / previous - 1) * 100 if previous else None

    ui.kpi_row([
        {"label": "Last price", "value": ui.price_fmt(data.last_price),
         "note": f"{name} · {timeframe} · {data.interval} bars", "trend": 1 if (change or 0) > 0 else -1 if (change or 0) < 0 else 0},
        {"label": "Latest bar change", "value": ui.pct(change, signed=True), "trend": 1 if (change or 0) > 0 else -1 if (change or 0) < 0 else 0},
        {"label": "Trend structure", "value": snapshot.trend_label, "note": f"SMA {settings.fast_ma}/{settings.slow_ma}"},
        {"label": "RSI / ADX", "value": f"{ui.number(snapshot.rsi, 1)} / {ui.number(snapshot.adx, 1)}",
         "note": snapshot.adx_state},
        {"label": "Volatility (ATR)", "value": ui.pct(snapshot.atr_pct), "note": f"{snapshot.volatility_label} regime"},
    ])

    latest = state.get_database().latest_signal_for(state.require_user()["id"], symbol, timeframe)
    levels = {}
    if latest and latest.get("label") in {"BUY", "SELL"}:
        levels = {"TP": latest.get("tp"), "SL": latest.get("sl")}

    close = data.frame["Close"]
    overlays = {
        f"EMA {settings.fast_ma}": indicators.ema(close, settings.fast_ma),
        f"SMA {settings.slow_ma}": indicators.sma(close, settings.slow_ma),
    }
    ui.show_chart(ui.price_chart(
        data.frame, overlays=overlays, levels=levels, is_sample=data.is_sample,
        height=common.chart_height(460),
    ))
    ui.source_line(data)
    if data.is_sample:
        ui.notice(
            "<strong>SAMPLE DATA.</strong> The live provider was unavailable and offline sample "
            "data is enabled in Settings. No price here is real, and no BUY/SELL signal can be produced.",
            "warn",
        )

    ui.section("Momentum, trend strength and volatility", "computed from these bars")
    ui.show_chart(ui.indicator_chart(
        data.frame,
        indicators.rsi(close, settings.rsi_period),
        indicators.macd(close),
        indicators.adx(data.frame, 14),
        height=common.chart_height(430),
    ))

    readings = pd.DataFrame([
        ("Trend", snapshot.trend_label),
        ("EMA fast", ui.number(snapshot.ema_fast, 4)),
        ("SMA slow", ui.number(snapshot.sma_slow, 4)),
        ("RSI (14)", ui.number(snapshot.rsi, 1)),
        ("MACD histogram", ui.number(snapshot.macd_hist, 4)),
        ("MACD state", snapshot.macd_state),
        ("Bollinger width", ui.pct(snapshot.bb_width)),
        ("ATR (14)", ui.number(snapshot.atr, 4)),
        ("ATR % of price", ui.pct(snapshot.atr_pct)),
        ("ADX (14)", ui.number(snapshot.adx, 1)),
        ("+DI / -DI", f"{ui.number(snapshot.plus_di, 1)} / {ui.number(snapshot.minus_di, 1)}"),
        ("Volume vs 50-bar avg", f"{snapshot.volume_ratio:.2f}x" if np.isfinite(snapshot.volume_ratio) else "n/a"),
        ("Bars loaded", str(snapshot.bars)),
        ("Data quality", data.quality),
    ], columns=["Measure", "Reading"])
    ui.html_table(readings)

    if latest:
        ui.section("Latest stored signal for this chart", "same instrument and timeframe")
        ui.signal_card(latest, name=name)
    else:
        ui.notice("No signal is stored for this instrument/timeframe yet. Press Scan instrument.")
    if st.button("Ask MNZ AI about this chart", key="chart_to_ai", type="secondary"):
        st.session_state["ai_symbol"] = symbol
        state.goto("MNZ AI")


def _strategy_tab(category_key: str, symbol: str, name: str, timeframe: str) -> None:
    tf = config.timeframe(timeframe)
    defaults = config.ENGINE_STRATEGY_DEFAULTS.get(category_key, config.StrategySettings())

    ui.section("Strategy Lab", "moving-average trend strategy with costs")
    with st.form("strategy_lab_form"):
        c1, c2, c3, c4 = st.columns(4)
        fast = c1.number_input("Fast MA", 2, 200, int(min(defaults.fast_ma, 80)), 1)
        slow = c2.number_input("Slow MA", 3, 400, int(min(defaults.slow_ma, 200)), 1)
        cost = c3.number_input("Cost (bps/side)", 0.0, 200.0, float(defaults.cost_bps), 0.5)
        allow_short = c4.checkbox("Allow shorts", value=bool(defaults.allow_short))
        run = st.form_submit_button("Run backtest")

    if run:
        data = market_data.get_timeframe_history(symbol, timeframe,
                                                 allow_sample=state.allow_sample_data())
        if not data.ok:
            st.error(data.error or "No data for this instrument.")
        elif slow <= fast:
            st.error("Slow MA must be longer than fast MA.")
        else:
            settings = config.StrategySettings(
                fast_ma=int(fast), slow_ma=int(slow), cost_bps=float(cost),
                allow_short=bool(allow_short),
            )
            with st.spinner("Running backtest…"):
                result = backtesting.run_backtest(
                    data.frame, settings, symbol=symbol, market=category_key,
                    initial_balance=config.DEMO_STARTING_BALANCE,
                    source=data.source_label, is_sample=data.is_sample,
                )
            st.session_state["bt_result"] = result
            st.session_state["bt_context"] = {"symbol": symbol, "market": category_key,
                                              "timeframe": timeframe, "period": tf.period,
                                              "interval": tf.interval, "is_sample": data.is_sample}

    result = st.session_state.get("bt_result")
    if result is not None:
        if not result.ok:
            ui.empty_state("Backtest could not run.", " ".join(result.warnings) or "Insufficient history.")
        else:
            metrics = result.metrics
            ui.kpi_row([
                {"label": "Simulated total return", "value": ui.pct(metrics.get("total_return_pct"), signed=True),
                 "trend": 1 if (metrics.get("total_return_pct") or 0) > 0 else -1},
                {"label": "Buy & hold", "value": ui.pct(metrics.get("buy_hold_return_pct"), signed=True)},
                {"label": "Max drawdown", "value": ui.pct(metrics.get("max_drawdown_pct"))},
                {"label": "Win rate", "value": ui.pct(metrics.get("win_rate"), 1),
                 "note": f"{metrics.get('num_trades', 0)} simulated trades"},
                {"label": "Profit factor", "value": ui.number(metrics.get("profit_factor"), 2)},
            ])
            if result.fitted:
                ui.notice(
                    f"History was too short for {result.settings.slow_ma} slow bars; the same "
                    "fast/slow ratio was fitted to the window and is reported in the result."
                )
            for warning in result.warnings:
                ui.notice(html_escape(str(warning)), "warn")
            curve = pd.DataFrame({"ts": result.equity_curve.index, "equity": result.equity_curve.to_numpy()})
            ui.show_chart(ui.equity_chart(curve, config.DEMO_STARTING_BALANCE,
                                          height=common.chart_height(300),
                                          title="Simulated backtest equity"))
            ui.section("Simulated trades", "bar-close fills, costs applied on both sides")
            ui.show_table(result.trades_frame(), height=280)
            with st.expander("Metric detail", expanded=False):
                ui.show_table(result.metrics_frame())
            st.caption(
                "Backtests ignore financing, taxes, liquidity and intrabar stop behaviour. "
                "Historical results do not guarantee future performance."
            )
            if st.button("Save this backtest", key="bt_save", type="secondary"):
                context = st.session_state.get("bt_context", {})
                state.get_database().save_backtest({
                    "market": context.get("market", category_key),
                    "symbol": context.get("symbol", symbol),
                    "period": context.get("period", tf.period),
                    "interval": context.get("interval", tf.interval),
                    "settings": result.settings.to_dict(),
                    "metrics": result.metrics,
                    "is_sample": context.get("is_sample", False),
                    "user_id": state.require_user()["id"],
                })
                ui.flash("Backtest saved to your account.")
                st.rerun()

    ui.section("Historical backtesting by period", "same strategy, trailing windows")
    if st.button("Compare periods", key="bt_compare_periods", type="secondary"):
        data = market_data.get_timeframe_history(symbol, timeframe,
                                                 allow_sample=state.allow_sample_data())
        if not data.ok:
            st.error(data.error or "No data for this instrument.")
        else:
            settings = config.StrategySettings(
                fast_ma=int(fast), slow_ma=int(slow), cost_bps=float(cost),
                allow_short=bool(allow_short),
            )
            compare = backtesting.compare_periods(
                data.frame, settings, symbol=symbol, market=category_key,
                initial_balance=config.DEMO_STARTING_BALANCE,
                source=data.source_label, is_sample=data.is_sample,
            )
            st.session_state["bt_periods_result"] = compare
    if isinstance(st.session_state.get("bt_periods_result"), pd.DataFrame):
        ui.show_table(st.session_state["bt_periods_result"])

    ui.section("Strategy comparison across markets", "same timeframe, each market's default structure")
    if st.button("Run market comparison", key="bt_compare_markets", type="secondary"):
        rows = []
        progress = st.progress(0.0)
        markets = [key for key, cat in config.MARKETS.items() if cat.available]
        for index, key in enumerate(markets):
            target = config.SCAN_SHORTLIST.get(key, [config.MARKETS[key].instruments[0].symbol])[0]
            data = market_data.get_timeframe_history(target, timeframe,
                                                     allow_sample=state.allow_sample_data())
            entry = {"Market": config.MARKETS[key].name, "Instrument": target}
            if data.ok:
                settings = config.ENGINE_STRATEGY_DEFAULTS.get(key, config.StrategySettings())
                res = backtesting.run_backtest(
                    data.frame, settings, symbol=target, market=key,
                    initial_balance=config.DEMO_STARTING_BALANCE,
                    source=data.source_label, is_sample=data.is_sample,
                )
                if res.ok:
                    entry.update({
                        "Return %": round(res.metrics["total_return_pct"], 2),
                        "Buy & hold %": round(res.metrics["buy_hold_return_pct"], 2),
                        "Max DD %": round(res.metrics["max_drawdown_pct"], 2),
                        "Trades": res.metrics["num_trades"],
                        "Win rate %": round(res.metrics["win_rate"], 1)
                        if np.isfinite(res.metrics["win_rate"]) else None,
                    })
                else:
                    entry.update({"Return %": None, "Note": res.warnings[0] if res.warnings else "insufficient history"})
            else:
                entry.update({"Return %": None, "Note": data.error})
            rows.append(entry)
            progress.progress((index + 1) / max(len(markets), 1))
        progress.empty()
        st.session_state["bt_markets_result"] = pd.DataFrame(rows)
    if isinstance(st.session_state.get("bt_markets_result"), pd.DataFrame):
        ui.show_table(st.session_state["bt_markets_result"])
        st.caption("Every return above is simulated on delayed historical bars with transaction costs.")

    saved = state.get_database().list_backtests(limit=10, user_id=state.require_user()["id"])
    if saved:
        ui.section("Saved backtests", "your account")
        ui.html_table(pd.DataFrame([
            {
                "When": run["created_at"].replace("T", " ")[:16],
                "Symbol": run["symbol"],
                "Market": config.ENGINE_LABELS.get(run["market"], run["market"]),
                "Period": run["period"],
                "Sample": "Yes" if run["is_sample"] else "No",
            }
            for run in saved
        ]))


def _conditions_tab(timeframe: str) -> None:
    results = st.session_state.get("scan_results") or []
    if not results:
        ui.empty_state(
            "No scan data for a conditions read.",
            "Run Scan All on the Scanner tab first — conditions are derived from the latest scan.",
        )
        return
    conditions = scanner.market_conditions(results)
    ui.kpi_row([
        {"label": "Bias", "value": conditions["label"],
         "note": f"Net balance {conditions.get('net', 0):+.2f}"},
        {"label": "BUY / SELL / WAIT", "value": f"{conditions['bullish']} / {conditions['bearish']} / {conditions['waiting']}",
         "note": f"{conditions['usable']} of {conditions['scanned']} instruments usable"},
        {"label": "Average quality", "value": f"{conditions['avg_quality']}/100"},
        {"label": "Data warnings", "value": str(conditions.get("sample", 0) + conditions.get("stale", 0)),
         "note": f"{conditions.get('sample', 0)} sample · {conditions.get('stale', 0)} stale"},
    ])
    ui.section("Market conditions monitor", f"latest scan · {timeframe}")
    ui.html_table(common.quote_row(results), numeric=["Quality", "Score", "Price", "Change %"])
    st.caption(
        "Breadth is calculated only from instruments actually scanned in this session. "
        "It is not an exchange-wide advance/decline line."
    )


def _calendar_tab() -> None:
    ui.section("Economic calendar", "recurring windows — awareness, not a live feed")
    events = common.upcoming_events(days=14)
    ui.html_table(common.events_frame(events))
    ui.notice(
        "<strong>How to read this.</strong> Session times are fixed. Release rows marked "
        "“typical window” are heuristics, not confirmed dates, and rows marked “check official "
        "calendar” have no date computed at all. MNZ does not stream an economic calendar.",
        "warn",
    )


def render() -> None:
    state.require_user()

    ui.page_header(
        "Markets",
        "Scan, chart and stress-test instruments across forex, global indices, stocks, "
        "commodities and crypto — only where the connected feed has data.",
        tag="DELAYED DATA",
    )

    category_key = st.session_state.get("markets_category", "forex")
    category_keys = [k for k in CATEGORY_KEYS if k != "synthetics"] + ["synthetics"]
    labels = {k: config.MARKETS[k].name for k in category_keys}
    if st.session_state.get("markets_category_select") not in category_keys:
        st.session_state["markets_category_select"] = (
            category_key if category_key in category_keys else "forex"
        )
    chosen = st.selectbox(
        "Market category", category_keys,
        format_func=lambda key: labels[key], key="markets_category_select",
    )
    st.session_state["markets_category"] = chosen
    category_key = chosen
    category = config.MARKETS[category_key]

    top_left, top_mid, top_right = st.columns([1.5, 1.6, 1.1])
    with top_left:
        if category.available:
            symbols = [item.symbol for item in category.instruments]
            if st.session_state.get("markets_symbol") not in symbols:
                st.session_state["markets_symbol"] = symbols[0]
            symbol = st.selectbox(
                "Instrument", symbols, key="markets_symbol",
                format_func=lambda value: f"{value} — {dict((i.symbol, i.label) for i in category.instruments).get(value, value)}",
            )
        else:
            symbol = ""
            st.selectbox("Instrument", ["Awaiting data connection"], disabled=True, key="markets_symbol_none")
    with top_mid:
        timeframe = _timeframe()
        if st.session_state.get("markets_tf") not in config.TIMEFRAMES:
            st.session_state["markets_tf"] = timeframe
        tf_choice = st.pills(
            "Timeframe", config.TIMEFRAME_ORDER,
            selection_mode="single", key="markets_tf",
        )
        timeframe = tf_choice if tf_choice in config.TIMEFRAMES else timeframe
        if config.timeframe(timeframe).note:
            st.caption(config.timeframe(timeframe).note)
    with top_right:
        st.write("")
        scan_one = st.button("Scan instrument", key="scan_one", type="primary",
                             disabled=not category.available)
        scan_all = st.button("Scan all", key="scan_all", type="secondary",
                             disabled=not category.available)

    if not category.available:
        ui.notice(
            f"<strong>{category.name} are not connected.</strong> {category.note} "
            "No synthetic prices are displayed or invented.",
            "warn",
        )

    if category.available and (scan_one or scan_all):
        targets = [symbol] if scan_one else [i.symbol for i in category.instruments]
        summary = _run_scan(category_key, targets, timeframe, force=True)
        ui.flash(f"Scanned {len(targets)} instrument(s): {summary['created']} new signal(s), "
                 f"{summary['alerts']} alert(s).")

    if not category.available:
        ui.footer()
        return

    name = dict((i.symbol, i.label) for i in category.instruments).get(symbol, symbol)
    tab_scanner, tab_chart, tab_lab, tab_conditions, tab_calendar = st.tabs(
        ["Scanner", "Chart & indicators", "Strategy Lab", "Conditions", "Calendar"]
    )
    with tab_scanner:
        _continuous_panel(category_key, category)
        if st.button("Refresh data cache", key="markets_refresh_cache", type="secondary"):
            market_data.clear_cache()
            st.rerun()
    with tab_chart:
        _chart_tab(category_key, category, symbol, name, timeframe)
    with tab_lab:
        _strategy_tab(category_key, symbol, name, timeframe)
    with tab_conditions:
        _conditions_tab(timeframe)
    with tab_calendar:
        _calendar_tab()

    ui.footer()
