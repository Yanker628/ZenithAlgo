from __future__ import annotations

from typing import Any


def compute_diagnostics(metrics: dict[str, Any]) -> dict[str, bool]:
    """
    诊断只回答“发生了什么”，不负责裁决。
    阈值为保守默认，可在未来配置化。
    """
    total_trades = int(metrics.get("total_trades", 0) or 0)
    exposure = float(metrics.get("exposure", 0.0) or 0.0)
    sharpe = float(metrics.get("sharpe", 0.0) or 0.0)
    max_dd = float(metrics.get("max_drawdown", 0.0) or 0.0)
    total_return = float(metrics.get("total_return", 0.0) or 0.0)

    low_trades = total_trades < 10
    low_exposure = exposure < 0.05
    unstable_sharpe = (abs(sharpe) < 0.2) and (max_dd > 0.2)
    negative_edge = (total_return <= 0.0) and (sharpe < 0.0)

    return {
        "low_trades": low_trades,
        "low_exposure": low_exposure,
        "unstable_sharpe": unstable_sharpe,
        "negative_edge": negative_edge,
    }

