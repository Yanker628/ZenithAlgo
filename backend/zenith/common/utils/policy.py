from __future__ import annotations

from typing import Any


def evaluate_policy(
    metrics: dict[str, Any],
    *,
    policy_cfg: dict[str, Any] | None = None,
    stage: str = "research",
    git_dirty: bool | None = None,
) -> dict[str, Any]:
    """
    policy 负责裁决：是否通过，以及原因。
    支持的 policy_cfg（可选）：
    - min_trades: int
    - max_drawdown: float
    - min_sharpe: float
    - min_total_return: float
    - require_clean_git: bool（stage=formal 时更有意义）
    """
    cfg = policy_cfg or {}
    reasons: list[str] = []

    total_trades = int(metrics.get("total_trades", 0) or 0)
    sharpe = float(metrics.get("sharpe", 0.0) or 0.0)
    max_dd = float(metrics.get("max_drawdown", 0.0) or 0.0)
    total_return = float(metrics.get("total_return", 0.0) or 0.0)

    min_trades = cfg.get("min_trades")
    if min_trades is not None and total_trades < int(min_trades):
        reasons.append("low_trades")
    max_drawdown = cfg.get("max_drawdown")
    if max_drawdown is not None and max_dd > float(max_drawdown):
        reasons.append("max_drawdown")
    min_sharpe = cfg.get("min_sharpe")
    if min_sharpe is not None and sharpe < float(min_sharpe):
        reasons.append("min_sharpe")
    min_total_return = cfg.get("min_total_return")
    if min_total_return is not None and total_return < float(min_total_return):
        reasons.append("min_total_return")

    if cfg.get("require_clean_git") and stage == "formal" and git_dirty:
        reasons.append("git_dirty")

    return {"passed": not reasons, "stage": stage, "reasons": reasons}

