from __future__ import annotations

from datetime import datetime, timezone

from broker.backtest_broker import BacktestBroker
from shared.models.models import OrderSignal


def test_backtest_broker_buy_fee_in_cost_and_cash():
    broker = BacktestBroker(initial_equity=1000.0, taker_fee=0.001, slippage_bp=0.0)
    ts = datetime.now(timezone.utc)
    sig = OrderSignal(symbol="BTCUSDT", side="buy", qty=5.0, reason="t")
    res = broker.execute(sig, tick_price=100.0, ts=ts)
    assert res["status"] == "filled"

    fee = 5.0 * 100.0 * 0.001
    assert abs(broker.cash - (1000.0 - 500.0 - fee)) < 1e-9
    pos = broker.get_position("BTCUSDT")
    assert pos is not None
    assert abs(pos.qty - 5.0) < 1e-9
    assert abs(pos.avg_price - ((500.0 + fee) / 5.0)) < 1e-9


def test_backtest_broker_sell_realized_delta_and_cash():
    broker = BacktestBroker(initial_equity=1000.0, taker_fee=0.001, slippage_bp=0.0)
    ts = datetime.now(timezone.utc)
    broker.execute(OrderSignal(symbol="BTCUSDT", side="buy", qty=5.0, reason="t"), tick_price=100.0, ts=ts)
    res = broker.execute(OrderSignal(symbol="BTCUSDT", side="sell", qty=5.0, reason="t"), tick_price=110.0, ts=ts)
    assert res["status"] == "filled"

    buy_fee = 5.0 * 100.0 * 0.001
    avg = (500.0 + buy_fee) / 5.0
    sell_fee = 5.0 * 110.0 * 0.001
    expected_realized = (110.0 - avg) * 5.0 - sell_fee
    assert abs(res["realized_delta"] - expected_realized) < 1e-9

    expected_cash = 1000.0 - 500.0 - buy_fee + 550.0 - sell_fee
    assert abs(broker.cash - expected_cash) < 1e-9


def test_backtest_broker_cash_insufficient_auto_shrink_qty():
    broker = BacktestBroker(initial_equity=100.0, taker_fee=0.0, slippage_bp=0.0)
    ts = datetime.now(timezone.utc)
    res = broker.execute(OrderSignal(symbol="BTCUSDT", side="buy", qty=10.0, reason="t"), tick_price=50.0, ts=ts)
    assert res["status"] == "filled"
    assert abs(res["qty"] - 2.0) < 1e-9
    pos = broker.get_position("BTCUSDT")
    assert pos is not None
    assert abs(pos.qty - 2.0) < 1e-9


def test_backtest_broker_slippage_direction_correct():
    broker = BacktestBroker(initial_equity=1000.0, taker_fee=0.0, slippage_bp=100.0)  # 1%
    ts = datetime.now(timezone.utc)
    res_buy = broker.execute(OrderSignal(symbol="BTCUSDT", side="buy", qty=1.0, reason="t"), tick_price=100.0, ts=ts)
    assert abs(res_buy["slippage_price"] - 101.0) < 1e-9
    res_sell = broker.execute(OrderSignal(symbol="BTCUSDT", side="sell", qty=1.0, reason="t"), tick_price=100.0, ts=ts)
    assert abs(res_sell["slippage_price"] - 99.0) < 1e-9
