"""信号执行管线（Strategy → Sizing → Risk → Broker）。

该模块用于让 runner/backtest 共用同一段“策略信号处理”逻辑，
减少两处实现漂移。
"""

from __future__ import annotations

from typing import Any

from broker.abstract_broker import Broker
from shared.models.models import OrderSignal, Tick
from algo.risk.manager import RiskManager
from algo.strategy.base import Strategy
from utils.sizer import size_signals


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
) -> list[OrderSignal]:
    """生成可执行信号（含价格、sizing、风控过滤）。"""
    raw_signals = strategy.on_tick(tick)
    if not raw_signals:
        return []

    for sig in raw_signals:
        if sig.price is None:
            sig.price = (last_prices or {}).get(sig.symbol) or tick.price

    sized_signals = size_signals(raw_signals, broker, sizing_cfg, equity_base, logger=logger)
    if not sized_signals:
        return []

    return risk.filter_signals(sized_signals)


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
