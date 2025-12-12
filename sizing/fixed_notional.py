"""固定名义下单：trade_notional / price。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FixedNotionalSizer:
    trade_notional: float

    def max_buy_qty(self, *, price: float, current_qty: float, equity_base: float) -> float:
        if self.trade_notional <= 0 or price <= 0:
            return 0.0
        return self.trade_notional / price

    def max_sell_qty(self, *, price: float, current_qty: float, equity_base: float) -> float:
        if current_qty <= 0:
            return 0.0
        if self.trade_notional <= 0 or price <= 0:
            return current_qty
        return min(current_qty, self.trade_notional / price)

