"""多账户聚合（预留）。"""

from __future__ import annotations

from shared.models.models import Position

from broker.accounts.base_account import BaseAccount


class MultiAccount(BaseAccount):
    def __init__(self, accounts: list[BaseAccount]):
        self._accounts = list(accounts)

    @property
    def positions(self) -> dict[str, Position]:
        merged: dict[str, Position] = {}
        for account in self._accounts:
            for sym, pos in account.positions.items():
                if sym not in merged:
                    merged[sym] = Position(symbol=sym, qty=pos.qty, avg_price=pos.avg_price)
                else:
                    merged[sym].qty += pos.qty
        return merged

