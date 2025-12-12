from __future__ import annotations

from broker.backtest import BacktestBroker
from market.models import OrderSignal, Position
from utils.sizer import size_signals


def test_fixed_notional_sizer_buy_qty():
    broker = BacktestBroker(initial_equity=1000)
    sig = OrderSignal(symbol="BTCUSDT", side="buy", qty=0.0, reason="t", price=100.0)
    sized = size_signals([sig], broker, {"type": "fixed_notional", "trade_notional": 200}, 1000)
    assert len(sized) == 1
    assert abs(sized[0].qty - 2.0) < 1e-9


def test_pct_equity_sizer_buy_qty_respects_existing_position():
    broker = BacktestBroker(initial_equity=1000)
    # 手动注入已有持仓 1 BTC
    broker.positions["BTCUSDT"] = Position(symbol="BTCUSDT", qty=1.0, avg_price=100.0)
    sig = OrderSignal(symbol="BTCUSDT", side="buy", qty=0.0, reason="t", price=100.0)
    sized = size_signals([sig], broker, {"type": "pct_equity", "position_pct": 0.2}, 1000)
    assert len(sized) == 1
    # 最大名义 200，已有名义 100，剩余名义 100 => qty=1
    assert abs(sized[0].qty - 1.0) < 1e-9
