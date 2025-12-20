from __future__ import annotations

from datetime import datetime, timezone

from zenith.core.signal_pipeline import SignalTrace, prepare_signals
from zenith.common.models.models import OrderSignal, Tick


class _Broker:
    def __init__(self):
        self._positions = {}

    def get_position(self, symbol: str):
        return self._positions.get(symbol)


class _Strategy:
    def on_tick(self, tick: Tick):
        # 1) buy：tick.price=0 会导致 sizing 丢弃
        # 2) sell：由 risk 丢弃
        return [
            OrderSignal(symbol=tick.symbol, side="buy", qty=0.0, reason="t"),
            OrderSignal(symbol=tick.symbol, side="sell", qty=1.0, reason="t"),
        ]


class _Risk:
    def filter_signals(self, signals):
        return [s for s in signals if s.side != "sell"]


def test_prepare_signals_signal_trace_counts():
    tick = Tick(symbol="BTCUSDT", price=0.0, ts=datetime.now(timezone.utc))
    trace = SignalTrace()

    res = prepare_signals(
        tick=tick,
        strategy=_Strategy(),
        broker=_Broker(),
        risk=_Risk(),
        sizing_cfg={"type": "fixed_notional", "trade_notional": 100},
        equity_base=1000.0,
        last_prices=None,
        trace=trace,
    )
    assert res == []
    assert trace.to_dict() == {
        "raw": 2,
        "after_sizing": 0,
        "after_risk": 0,
        "dropped_by_sizing": 2,
        "dropped_by_risk": 0,
    }


class _TwoBuyStrategy:
    def on_tick(self, tick: Tick):
        return [
            OrderSignal(symbol=tick.symbol, side="buy", qty=0.0, reason="keep"),
            OrderSignal(symbol=tick.symbol, side="buy", qty=0.0, reason="drop"),
        ]


class _DropByRisk:
    def filter_signals(self, signals):
        return [s for s in signals if getattr(s, "reason", None) != "drop"]


def test_prepare_signals_signal_trace_counts_dropped_by_risk():
    tick = Tick(symbol="BTCUSDT", price=100.0, ts=datetime.now(timezone.utc))
    trace = SignalTrace()

    res = prepare_signals(
        tick=tick,
        strategy=_TwoBuyStrategy(),
        broker=_Broker(),
        risk=_DropByRisk(),
        sizing_cfg={"type": "fixed_notional", "trade_notional": 100},
        equity_base=1000.0,
        last_prices=None,
        trace=trace,
    )
    assert len(res) == 1
    assert trace.to_dict() == {
        "raw": 2,
        "after_sizing": 2,
        "after_risk": 1,
        "dropped_by_sizing": 0,
        "dropped_by_risk": 1,
    }
