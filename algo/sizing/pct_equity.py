"""按权益比例控制最大持仓名义：position_pct * equity_base。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PctEquitySizer:
    position_pct: float

    def max_buy_qty(self, *, price: float, current_qty: float, equity_base: float) -> float:
        if self.position_pct <= 0 or equity_base <= 0 or price <= 0:
            return 0.0
        max_notional = equity_base * self.position_pct
        current_notional = abs(current_qty * price)
        remaining_notional = max(0.0, max_notional - current_notional)
        return remaining_notional / price if price > 0 else 0.0

    def max_sell_qty(self, *, price: float, current_qty: float, equity_base: float) -> float:
        # 卖出是减仓/平仓，默认不按 position_pct 再限制
        return max(0.0, current_qty)

