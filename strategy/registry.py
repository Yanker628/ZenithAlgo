"""策略注册表：字符串 -> Strategy 实现。

V2.3 约定：engine 只负责 orchestration，策略实例必须由配置驱动构建。
"""

from __future__ import annotations

import inspect
from typing import Any, Mapping

from strategy.base import Strategy
from strategy.simple_ma import SimpleMAStrategy
from utils.config_loader import StrategyConfig

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
        name = str(cfg.type or "simple_ma")
        params = cfg.params or {}
    elif isinstance(cfg, Mapping):
        name = str(cfg.get("type") or "simple_ma")
        params = dict(cfg)
        params.pop("type", None)
    else:
        raise ValueError("strategy cfg must be StrategyConfig or dict")

    cls = get_strategy_cls(name)
    kwargs = _filter_init_kwargs(cls, params)
    return cls(**kwargs)  # type: ignore[call-arg]


# 默认注册
register_strategy("simple_ma", SimpleMAStrategy)

