from __future__ import annotations
from typing import Any

class Sizer:
    def max_buy_qty(self, price: float, current_qty: float, equity_base: float) -> float:
        return 0.0
    
    def max_sell_qty(self, price: float, current_qty: float, equity_base: float) -> float:
        return float('inf')

class FixedNotionalSizer(Sizer):
    def __init__(self, trade_notional: float):
        self.trade_notional = float(trade_notional)

    def max_buy_qty(self, price: float, current_qty: float, equity_base: float) -> float:
        if price <= 0: return 0.0
        return self.trade_notional / price

    def max_sell_qty(self, price: float, current_qty: float, equity_base: float) -> float:
        if price <= 0: return 0.0
        return self.trade_notional / price

class PctEquitySizer(Sizer):
    def __init__(self, position_pct: float):
        self.position_pct = float(position_pct)

    def max_buy_qty(self, price: float, current_qty: float, equity_base: float) -> float:
        if price <= 0 or self.position_pct <= 0: return 0.0
        max_notional = equity_base * self.position_pct
        current_notional = current_qty * price
        remaining = max(0.0, max_notional - current_notional)
        return remaining / price

    def max_sell_qty(self, price: float, current_qty: float, equity_base: float) -> float:
        return float('inf')

def build_sizer(cfg: dict[str, Any]) -> Sizer | None:
    mode = str(cfg.get("type") or cfg.get("mode") or "").strip().lower()
    if mode == "fixed_notional":
        tn = cfg.get("trade_notional")
        if tn is not None:
             return FixedNotionalSizer(tn)
    elif mode == "pct_equity":
        pp = cfg.get("position_pct")
        if pp is not None:
             return PctEquitySizer(pp)
    return None
