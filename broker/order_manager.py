"""订单管理器（预留）。

当前系统仍以“信号 -> broker.execute”最小链路为主；
订单管理器用于后续接入：client_order_id、重试、对账等能力。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderRef:
    symbol: str
    client_order_id: str


class OrderManager:
    def __init__(self, *, prefix: str = "ZA"):
        self._prefix = str(prefix)
        self._seq = 0

    def next(self, *, symbol: str) -> OrderRef:
        self._seq += 1
        return OrderRef(symbol=str(symbol), client_order_id=f"{self._prefix}-{symbol}-{self._seq}")

