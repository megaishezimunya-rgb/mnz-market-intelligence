"""Tests for the demo account, virtual trades and portfolio analytics."""

from __future__ import annotations

import pytest

import config
from database.database import Database
from simulator import portfolio
from simulator.demo_account import DemoAccount
from simulator.virtual_trades import VirtualTrade, validate_trade


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "mnz_test.db")


@pytest.fixture()
def account(db):
    return DemoAccount.get_or_create(db, "Test Demo", 10_000.0)


def test_new_account_starts_at_virtual_balance(account):
    assert account.starting_balance == pytest.approx(10_000.0)
    assert account.cash == pytest.approx(10_000.0)
    assert account.equity({}) == pytest.approx(10_000.0)
    assert account.open_positions() == []
    assert account.closed_positions() == []


def test_open_and_close_long_profit(account):
    trade, problems = account.open_position(
        symbol="TEST", market="stocks", side="Long", quantity=10, price=100.0, cost_bps=0.0,
    )
    assert problems == []
    assert trade is not None and trade.is_open
    assert account.cash == pytest.approx(10_000.0)
    assert account.equity({"TEST": 110.0}) == pytest.approx(10_100.0)

    closed, problems = account.close_position(trade.id, 110.0, cost_bps=0.0)
    assert problems == []
    assert closed.realized_pnl == pytest.approx(100.0)
    assert account.cash == pytest.approx(10_100.0)
    assert account.closed_positions()[0].status == "closed"
    assert account.stats()["win_rate"] == pytest.approx(100.0)


def test_short_position_profit(account):
    trade, _ = account.open_position(
        symbol="TEST", market="crypto", side="Short", quantity=5, price=200.0, cost_bps=0.0,
    )
    assert account.unrealized_pnl({"TEST": 180.0}) == pytest.approx(100.0)
    closed, _ = account.close_position(trade.id, 180.0, cost_bps=0.0)
    assert closed.net_pnl() == pytest.approx(100.0)


def test_costs_are_charged_on_both_sides(account):
    trade, _ = account.open_position(
        symbol="TEST", market="forex", side="Long", quantity=10, price=100.0, cost_bps=10.0,
    )
    assert trade.costs == pytest.approx(1.0)  # 1,000 notional * 10bps
    assert account.cash == pytest.approx(9_999.0)
    closed, _ = account.close_position(trade.id, 100.0, cost_bps=10.0)
    assert closed.costs == pytest.approx(2.0)
    assert closed.net_pnl() == pytest.approx(-2.0)
    assert account.cash == pytest.approx(9_998.0)


def test_invalid_orders_are_rejected(account):
    _, problems = account.open_position(symbol="", market="stocks", side="Sideways",
                                        quantity=0, price=0, cost_bps=999)
    assert len(problems) >= 3
    _, problems = account.open_position(symbol="TEST", market="stocks", side="Long",
                                        quantity=10, price=100.0, cost_bps=0)
    assert problems == []
    open_trade = account.open_positions()[0]
    _, problems = account.close_position(open_trade.id, -5)
    assert problems


def test_notional_guard_blocks_margin_style_bets(account):
    _, problems = account.open_position(
        symbol="TEST", market="stocks", side="Long", quantity=500, price=1_000.0, cost_bps=0.0,
    )
    assert problems and "equity" in problems[0].lower()


def test_drawdown_from_recorded_snapshots(account):
    trade, _ = account.open_position(
        symbol="TEST", market="stocks", side="Long", quantity=50, price=100.0, cost_bps=0.0,
    )
    account.snapshot({"TEST": 100.0}, throttle_seconds=0)
    account.snapshot({"TEST": 90.0}, throttle_seconds=0)
    drawdown = account.maximum_drawdown()
    assert drawdown["pct"] == pytest.approx(5.0, rel=1e-6)
    assert drawdown["points"] >= 2
    account.close_position(trade.id, 90.0, cost_bps=0.0)


def test_persistence_and_reset(db, account):
    account.open_position(symbol="TEST", market="stocks", side="Long",
                          quantity=1, price=100.0, cost_bps=0.0)
    reloaded = DemoAccount.load(db, account.id)
    assert len(reloaded.open_positions()) == 1

    reloaded.reset()
    assert reloaded.open_positions() == []
    assert reloaded.closed_positions() == []
    assert reloaded.cash == pytest.approx(reloaded.starting_balance)
    # A reset restores this account's own starting balance, not the global default.
    assert reloaded.equity({}) == pytest.approx(reloaded.starting_balance)


def test_portfolio_helpers(account):
    account.open_position(symbol="TEST", market="stocks", side="Long",
                          quantity=2, price=100.0, cost_bps=0.0)
    summary = portfolio.portfolio_summary(account, {"TEST": 105.0})
    assert summary["equity"] == pytest.approx(10_010.0)
    assert summary["open_positions"] == 1
    assert summary["unrealized_pnl"] == pytest.approx(10.0)

    allocation = portfolio.market_allocation(account, {"TEST": 105.0})
    assert not allocation.empty
    assert allocation.iloc[0]["Market"] == "Stocks"

    curve = portfolio.equity_curve(account)
    assert not curve.empty
    assert "equity" in curve.columns
    assert "ts" in curve.columns

    assert portfolio.monthly_returns(account).empty
    assert "Trades" in portfolio.engine_breakdown(account).columns


def test_monthly_returns_across_calendar_months(db, account):
    for stamp, equity in [
        ("2026-01-31T10:00:00", 10_000.0),
        ("2026-02-28T10:00:00", 10_100.0),
        ("2026-03-31T10:00:00", 10_000.0),
    ]:
        db.add_snapshot({
            "account_id": account.id, "ts": stamp, "equity": equity, "cash": equity,
            "unrealized_pnl": 0.0, "realized_pnl": 0.0,
        })
    table = portfolio.monthly_returns(account)
    assert not table.empty
    assert table.loc[2026, "Feb"] == pytest.approx(1.0)
    assert table.loc[2026, "Mar"] == pytest.approx(-0.9901, rel=1e-3)


def test_trade_frame_and_validation_helpers(account):
    from simulator.virtual_trades import trades_frame

    trade, _ = account.open_position(symbol="TEST", market="indices", side="Long",
                                     quantity=1, price=1000.0, cost_bps=0.0)
    frame = trades_frame([VirtualTrade.from_row({
        "id": trade.id, "account_id": account.id, "symbol": trade.symbol,
        "market": trade.market, "side": trade.side, "quantity": trade.quantity,
        "entry_price": trade.entry_price, "entry_time": trade.entry_time,
        "costs": 0.0, "status": "open",
    })], {"TEST": 1010.0})
    assert frame.iloc[0]["Unrealised P&L"] == pytest.approx(10.0)
    assert validate_trade("long", 1, 10, 5) == []
    assert validate_trade("long", 0, 10, 5)
