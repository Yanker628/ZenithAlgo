"""因子注册表：字符串 -> 因子实现。"""

from __future__ import annotations

import inspect
from typing import Any, Mapping

import pandas as pd

from algo.factors.atr import ATRFactor
from algo.factors.base import Factor
from algo.factors.ma import MAFactor
from algo.factors.rsi import RSIFactor

_REGISTRY: dict[str, type] = {}


def register_factor(name: str, cls: type) -> None:
    _REGISTRY[name] = cls


def get_factor_cls(name: str) -> type:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown factor: {name}")
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


def build_factors(cfg: Any) -> list[Factor]:
    """从配置构建因子列表。

    支持形态：
    - factors: [{name/type: "ma", params: {...}}, ...]
    - factors: [{type: "ma", window: 5, price_col: "close"}, ...]  # params 直接平铺（兼容）
    - 直接传入 list[dict]
    """
    if cfg is None:
        return []

    items = cfg
    if isinstance(cfg, dict):
        items = cfg.get("factors") or cfg.get("features") or []
    if not isinstance(items, list):
        raise ValueError("factors config must be a list")

    factors: list[Factor] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("factor item must be a dict")
        name = str(item.get("name") or item.get("type") or "")
        reserved = {"name", "type", "params"}
        raw_params = item.get("params", None)
        if raw_params is None:
            params: dict[str, Any] = {k: v for k, v in item.items() if k not in reserved}
        else:
            if not isinstance(raw_params, dict):
                raise ValueError("factor params must be a dict")
            params = dict(raw_params)
            # 兼容：允许 params 外再平铺参数（不覆盖 params 内同名键）
            for k, v in item.items():
                if k in reserved or k in params:
                    continue
                params[k] = v
        if not name:
            raise ValueError("factor item missing name")
        cls = get_factor_cls(name)
        kwargs = _filter_init_kwargs(cls, params)
        try:
            factors.append(cls(**kwargs))
        except TypeError as exc:
            raise ValueError(f"Invalid params for factor '{name}': {params}") from exc
    return factors


def apply_factors(df: pd.DataFrame, factors: list[Factor]) -> pd.DataFrame:
    for f in factors:
        df = f.compute(df)
    return df


# 默认注册
register_factor("ma", MAFactor)
register_factor("rsi", RSIFactor)
register_factor("atr", ATRFactor)
