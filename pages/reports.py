"""Performance Reports: virtual equity, drawdown, monthly returns and saved backtests."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import config
import state
import ui
from simulator import portfolio


def _backtest_history(db) -> pd.DataFrame:
    rows = []
    for run in db.list_backtests(limit=50):
        try:
            metrics = json.loads(run.get("metrics_json") or "{}")
        except (TypeError, ValueError):
            metrics = {}
        rows.append({
            "Run": f"#{run['id']}",
            "Date": run["created_at"].replace("T", " "),
            "Market": config.ENGINE_LABELS.get(run["market"], run["market"]),
            "Symbol": run["symbol"],
            "Period": run["period"],
            "Interval": run["interval"],
            "Total return %": round(metrics.get("total_return_pct", float("nan")), 2)
            if isinstance(metrics.get("total_return_pct"), (int, float)) else None,
            "Max drawdown %": round(metrics.get("max_drawdown_pct", float("nan")), 2)
            if isinstance(metrics.get("max_drawdown_pct"), (int, float)) else None,
            "Trades": metrics.get("num_trades"),
            "Win rate %": round(metrics.get("win_rate", float("nan")), 1)
            if isinstance(metrics.get("win_rate"), (int, float)) else None,
            "Data": "Sample" if run.get("is_sample") else "Provider",
        })
    return pd.DataFrame(rows)


def render() -> None:
    account = state.get_account()
    db = state.get_database()
    summary = portfolio.portfolio_summary(account)
    stats = portfolio.performance_stats(account)

    ui.page_header(
        "Performance Reports",
        "Simulated account performance, drawdown history, monthly returns, engine breakdown and saved "
        "backtest results. Every number is derived from local demo records.",
        tag="DEMO ONLY",
    )
    ui.demo_bar(right=f"Virtual equity {ui.money(summary['equity'])}")

    ui.kpi_row([
        {"label": "Starting virtual balance", "value": ui.money(summary["starting_balance"])},
        {"label": "Current equity", "value": ui.money(summary["equity"])},
        {"label": "Total simulated return", "value": ui.pct(summary["total_return_pct"], signed=True),
         "trend": summary["total_return_pct"]},
        {"label": "Max drawdown", "value": ui.pct(summary["max_drawdown_pct"])},
    ])
    ui.kpi_row([
        {"label": "Realised P&L", "value": ui.money(summary["realized_pnl"]), "trend": summary["realized_pnl"]},
        {"label": "Unrealised P&L", "value": ui.money(summary["unrealized_pnl"]), "trend": summary["unrealized_pnl"]},
        {"label": "Win rate", "value": ui.pct(summary["win_rate"], 1),
         "note": f"{summary['closed_positions']} closed trades"},
        {"label": "Total simulated costs", "value": ui.money(summary["total_costs"])},
    ])

    ui.section("Equity curve", "recorded virtual equity snapshots")
    curve = portfolio.equity_curve(account)
    ui.show_chart(ui.equity_chart(curve, account.starting_balance, height=320))
    if stats.get("available"):
        st.caption(
            f"{stats['snapshots']} snapshots from {stats['first']:%Y-%m-%d %H:%M} to "
            f"{stats['last']:%Y-%m-%d %H:%M} · annualised (simulated) "
            f"{ui.pct(stats['annualised_return_pct'], signed=True)} · snapshot volatility "
            f"{ui.pct(stats['volatility_pct'])}"
        )
    else:
        ui.notice(stats["note"] + " Open the Demo Trading or Overview page to record snapshots.")

    ui.section("Drawdown", "peak-to-trough of recorded equity")
    ui.show_chart(ui.drawdown_chart(portfolio.drawdown_series(account), height=240))

    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Monthly returns", "from recorded snapshots")
        monthly = portfolio.monthly_returns(account)
        if monthly.empty:
            ui.notice(
                "Monthly returns need equity snapshots across at least two different months. "
                "There is not enough recorded history yet — no figures are estimated.",
            )
        else:
            ui.show_table(monthly.reset_index())
    with right:
        ui.section("Engine breakdown", "realised simulated P&L by market")
        breakdown = portfolio.engine_breakdown(account)
        if breakdown.empty:
            ui.notice("No simulated trades recorded yet.")
        else:
            ui.show_table(breakdown)

    trade_stats = portfolio.trade_statistics(account.all_positions())
    ui.section("Trade statistics", "closed simulated trades only")
    if trade_stats.empty:
        ui.notice("No closed simulated trades yet.")
    else:
        ui.show_table(trade_stats)

    ui.section("Saved backtest results", "runs saved from Strategy Testing")
    history = _backtest_history(db)
    if history.empty:
        ui.notice("No backtest results have been saved yet. Run one on the Strategy Testing page.")
        if st.button("Open Strategy Testing", type="secondary"):
            state.goto("Strategy Testing")
    else:
        ui.show_table(history, height=320)
        st.caption(
            "Saved metrics are snapshots of past runs. Re-run a strategy to see current data; the "
            "results are not refreshed automatically."
        )

    ui.section("Exports")
    col1, col2 = st.columns(2)
    col1.download_button(
        "Download equity history CSV",
        curve.to_csv(index=False).encode("utf-8"),
        file_name="mnz_equity_history.csv",
        mime="text/csv",
    )
    col2.download_button(
        "Download profit & loss summary CSV",
        pd.DataFrame([
            ("Starting balance", summary["starting_balance"]),
            ("Current equity", summary["equity"]),
            ("Realised P&L", summary["realized_pnl"]),
            ("Unrealised P&L", summary["unrealized_pnl"]),
            ("Total return %", summary["total_return_pct"]),
            ("Maximum drawdown %", summary["max_drawdown_pct"]),
            ("Total costs", summary["total_costs"]),
            ("Closed trades", summary["closed_positions"]),
            ("Open trades", summary["open_positions"]),
        ], columns=["Metric", "Value"]).to_csv(index=False).encode("utf-8"),
        file_name="mnz_performance_summary.csv",
        mime="text/csv",
    )

    ui.notice(
        "Performance figures describe simulated activity only. They are not audited, not comparable to a "
        "broker statement and do not indicate what a real account would have earned. Historical and "
        "simulated results do not guarantee future performance.",
        "warn",
    )
    ui.footer()
