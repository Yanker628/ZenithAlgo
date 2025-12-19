"""账户抽象（预留）。

V2.x 当前以 broker 内部的本地视图为主；账户层用于后续扩展：
- 多币种现金管理
- 多账户/子账户聚合
- 对账与风控口径统一
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from zenith.common.models.models import Position


class BaseAccount(ABC):
    @property
    @abstractmethod
    def positions(self) -> dict[str, Position]:
        raise NotImplementedError

