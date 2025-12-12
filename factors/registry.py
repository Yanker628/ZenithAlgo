"""因子注册表：字符串 -> 因子实现。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from factors.atr import ATRFactor
from factors.base import Factor
from factors.ma import MAFactor
from factors.rsi import RSIFactor

_REGISTRY: dict[str, type] = {}


def register_factor(name: str, cls: type) -> None:
    _REGISTRY[name] = cls


def get_factor_cls(name: str) -> type:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown factor: {name}")
    return _REGISTRY[name]


def build_factors(cfg: Any) -> list[Factor]:
    """从配置构建因子列表。

    支持形态：
    - factors: [{name: "ma", params: {...}}, ...]
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
        params = item.get("params") or {}
        if not name:
            raise ValueError("factor item missing name")
        if not isinstance(params, dict):
            raise ValueError("factor params must be a dict")
        cls = get_factor_cls(name)
        factors.append(cls(**params))
    return factors


def apply_factors(df: pd.DataFrame, factors: list[Factor]) -> pd.DataFrame:
    for f in factors:
        df = f.compute(df)
    return df


# 默认注册
register_factor("ma", MAFactor)
register_factor("rsi", RSIFactor)
register_factor("atr", ATRFactor)

