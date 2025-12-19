"""策略注册表：字符串 -> Strategy 实现。"""

from __future__ import annotations

import inspect
from typing import Any, Mapping

from algo.strategy.base import Strategy
from algo.strategy.simple_ma import SimpleMAStrategy
from algo.strategy.trend_filter import TrendFilteredStrategy
from algo.strategy.tick_scalper import TickScalper
from algo.strategy.volatility import VolatilityBreakoutStrategy

from shared.config.config_loader import StrategyConfig

_REGISTRY: dict[str, type[Strategy]] = {}


def register_strategy(name: str, cls: type[Strategy]) -> None:
    _REGISTRY[name] = cls


def get_strategy_cls(name: str) -> type[Strategy]:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown strategy: {name}")
    return _REGISTRY[name]


def _filter_init_kwargs(cls: type, params: Mapping[str, Any]) -> dict[str, Any]:
    """过滤出 __init__ 支持的参数，避免配置里多字段导致报错。"""
    try:
        sig = inspect.signature(cls.__init__)
    except Exception:
        return dict(params)

    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return dict(params)

    allowed = {name for name in sig.parameters.keys() if name != "self"}
    return {k: v for k, v in params.items() if k in allowed}


def build_strategy(cfg: StrategyConfig | Mapping[str, Any] | None) -> Strategy:
    """从配置构建策略实例。

    支持：
    - StrategyConfig（来自 utils.config_loader）
    - dict（含 type + 参数字段）
    """
    if cfg is None:
        return SimpleMAStrategy()

    if isinstance(cfg, StrategyConfig):
        name = str(cfg.type)
        params = cfg.params or {}
    elif isinstance(cfg, Mapping):
        name = str(cfg.get("type"))
        params = dict(cfg)
        params.pop("type", None)
    else:
        raise ValueError("strategy cfg must be StrategyConfig or dict")

    cls = get_strategy_cls(name)
    kwargs = _filter_init_kwargs(cls, params)
    strat = cls(**kwargs)
    # 用于幂等下单等场景：提供稳定的策略标识（来自配置注册名）
    try:
        setattr(strat, "strategy_id", name)
    except Exception:
        pass
    return strat


# 默认注册
register_strategy("simple_ma", SimpleMAStrategy)
register_strategy("trend_filtered", TrendFilteredStrategy)
register_strategy("tick_scalper", TickScalper)
register_strategy("volatility_breakout", VolatilityBreakoutStrategy)
