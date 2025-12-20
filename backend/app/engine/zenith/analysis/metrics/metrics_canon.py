from __future__ import annotations

from typing import Any


CANONICAL_METRIC_KEYS: list[str] = [
    "total_return",
    "max_drawdown",
    "sharpe",
    "win_rate",
    "avg_win",
    "avg_loss",
    "total_trades",
    "profit_factor",
    "expectancy",
    "avg_trade_return",
    "std_trade_return",
    "exposure",
    "turnover",
]


def canonicalize_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """将 metrics 规范化为固定 key 集合（缺失补默认值）。"""
    m = metrics or {}
    out: dict[str, Any] = {}
    for k in CANONICAL_METRIC_KEYS:
        v = m.get(k)
        if v is None:
            v = 0.0 if k != "total_trades" else 0
        out[k] = v
    return out


def validate_metrics_schema(metrics: dict[str, Any]) -> None:
    """最小 schema 校验：确保 canonical keys 齐全。"""
    missing = [k for k in CANONICAL_METRIC_KEYS if k not in metrics]
    if missing:
        raise ValueError(f"metrics missing keys: {missing}")

