"""Demo trading centre: $100 balance, slots, TP/SL enforcement."""

from __future__ import annotations

import pytest

import config
from simulator.demo_account import DemoAccount


@pytest.fixture()
def account(db):
    return DemoAccount.get_or_create(db, "Slots Demo", config.DEMO_STARTING_BALANCE)


def test_default_demo_balance_is_100(account):
    assert account.starting_balance == pytest.approx(100.0)
    assert account.cash == pytest.approx(100.0)
    assert account.equity({}) == pytest.approx(100.0)


def test_slot_is_only_occupied_by_a_created_position(account):
    assert account.open_positions() == []
    trade, problems = account.open_position(
        symbol="EURUSD=X", market="forex", side="Long", quantity=0.01,
        price=1.1000, tp=1.1100, sl=1.0900, slot=1,
    )
    assert problems == []
    assert trade is not None and trade.slot == 1
    assert [t.slot for t in account.open_positions()] == [1]
    assert trade.tp == pytest.approx(1.1100)
    assert trade.sl == pytest.approx(1.0900)


def test_duplicate_slot_is_rejected(account):
    account.open_position(symbol="EURUSD=X", market="forex", side="Long",
                          quantity=0.01, price=1.1, slot=2)
    trade, problems = account.open_position(
        symbol="GBPUSD=X", market="forex", side="Long", quantity=0.01,
        price=1.2, slot=2,
    )
    assert trade is None
    assert any("already occupied" in problem for problem in problems)


def test_invalid_target_order_is_rejected(account):
    trade, problems = account.open_position(
        symbol="EURUSD=X", market="forex", side="Long", quantity=0.01,
        price=1.10, tp=1.05, sl=1.00, slot=1,
    )
    assert trade is None
    assert any("stop must be below entry" in problem for problem in problems)

    short, problems = account.open_position(
        symbol="EURUSD=X", market="forex", side="Short", quantity=0.01,
        price=1.10, tp=1.15, sl=1.20, slot=1,
    )
    assert short is None
    assert any("target must be below entry" in problem for problem in problems)


def test_long_tp_and_sl_are_processed(account):
    trade, _ = account.open_position(
        symbol="EURUSD=X", market="forex", side="Long", quantity=1,
        price=100.0, tp=105.0, sl=95.0, slot=1,
    )
    results = account.process_protective_exits({"EURUSD=X": 105.4})
    assert results and results[0]["result"] == "TP"
    closed = account.closed_positions()[0]
    assert closed.exit_price == pytest.approx(105.0)
    assert closed.realized_pnl is not None and closed.realized_pnl > 0


def test_short_sl_is_processed(account):
    account.open_position(
        symbol="BTC-USD", market="crypto", side="Short", quantity=0.01,
        price=50000.0, tp=45000.0, sl=52000.0, slot=1,
    )
    results = account.process_protective_exits({"BTC-USD": 52_100.0})
    assert results and results[0]["result"] == "SL"
    assert account.closed_positions()[0].exit_price == pytest.approx(52000.0)


def test_closing_updates_virtual_cash_and_equity(account):
    trade, _ = account.open_position(
        symbol="EURUSD=X", market="forex", side="Long", quantity=1,
        price=100.0, cost_bps=0.0, slot=1,
    )
    cash_after_open = account.cash
    closed, problems = account.close_position(trade.id, 110.0, cost_bps=0.0)
    assert problems == []
    assert closed.realized_pnl == pytest.approx(10.0)
    assert account.cash == pytest.approx(cash_after_open + 10.0)
    assert account.equity({}) == pytest.approx(110.0)
    assert account.open_positions() == []
