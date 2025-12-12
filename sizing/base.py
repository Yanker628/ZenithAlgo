"""Sizer 抽象与构建逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class Sizer(Protocol):
    """Sizer：根据约束给出买入最大数量。"""

    def max_buy_qty(self, *, price: float, current_qty: float, equity_base: float) -> float: ...

    def max_sell_qty(self, *, price: float, current_qty: float, equity_base: float) -> float: ...


@dataclass(frozen=True)
class NoopSizer:
    def max_buy_qty(self, *, price: float, current_qty: float, equity_base: float) -> float:
        return 0.0

    def max_sell_qty(self, *, price: float, current_qty: float, equity_base: float) -> float:
        return 0.0


def build_sizer(sizing_cfg: dict[str, Any] | None) -> Sizer:
    """从 sizing 配置构建 sizer。

    兼容：
    - type/mode: fixed_notional / pct_equity
    - 未指定 type 时：按旧逻辑允许同时配置（取更严格约束由上层组合实现）
    """
    from sizing.fixed_notional import FixedNotionalSizer
    from sizing.pct_equity import PctEquitySizer

    cfg = sizing_cfg or {}
    mode = str(cfg.get("type") or cfg.get("mode") or "").strip().lower()

    if mode in {"fixed_notional", "fixed-notional"}:
        return FixedNotionalSizer(trade_notional=float(cfg.get("trade_notional", 0.0) or 0.0))
    if mode in {"pct_equity", "pct-equity", "position_pct", "position-pct"}:
        return PctEquitySizer(position_pct=float(cfg.get("position_pct", 0.0) or 0.0))

    # fallback：都不指定时，交由上层兼容逻辑处理（这里给一个 no-op 占位）
    return NoopSizer()

