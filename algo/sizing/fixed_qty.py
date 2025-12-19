from dataclasses import dataclass

@dataclass(frozen=True)
class FixedQtySizer:
    qty: float = 1.0

    def max_buy_qty(self, *, price: float, current_qty: float, equity_base: float) -> float:
        return self.qty

    def max_sell_qty(self, *, price: float, current_qty: float, equity_base: float) -> float:
        return self.qty
