"""信号执行管线（Strategy → Sizing → Risk → Broker）。

该模块用于让 runner/backtest 共用同一段“策略信号处理”逻辑，
减少两处实现漂移。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from zenith.execution.abstract_broker import Broker
from zenith.common.models.models import OrderSignal, Tick
from zenith.strategies.risk.manager import RiskManager
from zenith.strategies.base import Strategy
from zenith.common.utils.client_order_id import make_client_order_id
from zenith.common.utils.sizer import size_signals


@dataclass
class SignalTrace:
    """信号“尸检”统计（只计数，不改变接口行为）。"""

    raw: int = 0
    after_sizing: int = 0
    after_risk: int = 0
    dropped_by_sizing: int = 0
    dropped_by_risk: int = 0

    def to_dict(self) -> dict[str, int]:
        return {k: int(v) for k, v in asdict(self).items()}


def prepare_signals(
    *,
    tick: Tick,
    strategy: Strategy,
    broker: Broker,
    risk: RiskManager,
    sizing_cfg: dict[str, Any] | None,
    equity_base: float,
    last_prices: dict[str, float] | None = None,
    logger=None,
    trace: SignalTrace | None = None,
) -> list[OrderSignal]:
    """生成可执行信号（含价格、sizing、风控过滤）。"""
    raw_signals = strategy.on_tick(tick)
    if trace is not None:
        trace.raw += len(raw_signals or [])
    if not raw_signals:
        return []

    for sig in raw_signals:
        if sig.price is None:
            sig.price = (last_prices or {}).get(sig.symbol) or tick.price

    sized_signals = size_signals(raw_signals, broker, sizing_cfg, equity_base, logger=logger)
    if trace is not None:
        trace.after_sizing += len(sized_signals or [])
        trace.dropped_by_sizing += max(0, len(raw_signals) - len(sized_signals or []))
    if not sized_signals:
        return []

    risk_passed = risk.filter_signals(sized_signals)
    if trace is not None:
        trace.after_risk += len(risk_passed or [])
        trace.dropped_by_risk += max(0, len(sized_signals) - len(risk_passed or []))
    if not risk_passed:
        return []

    strategy_id = getattr(strategy, "strategy_id", None) or strategy.__class__.__name__
    for idx, sig in enumerate(risk_passed):
        if getattr(sig, "client_order_id", None):
            continue
        sig.client_order_id = make_client_order_id(
            strategy_id=str(strategy_id),
            symbol=str(sig.symbol),
            side=str(sig.side),
            intent_ts=tick.ts,
            signal_seq=idx,
            reason=sig.reason,
        )
    return risk_passed


def execute_signals(
    *,
    signals: list[OrderSignal],
    broker: Broker,
    execute_kwargs: dict[str, Any] | None = None,
) -> list[dict]:
    """执行信号列表并返回执行结果。"""
    if not signals:
        return []
    kwargs = execute_kwargs or {}
    results: list[dict] = []
    for sig in signals:
        results.append(broker.execute(sig, **kwargs))
    return results
