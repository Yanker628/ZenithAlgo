"""Broker 抽象接口与运行模式定义。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from shared.models.models import OrderSignal, Position


class BrokerMode(Enum):
    """Broker 运行模式枚举。"""

    DRY_RUN = "dry-run"
    PAPER = "paper"
    LIVE = "live"
    LIVE_TESTNET = "live-testnet"
    LIVE_MAINNET = "live-mainnet"


class Broker(ABC):
    """交易执行抽象层。

    子类需要维护本地持仓与 PnL 视图，并实现下单执行。
    """

    positions: dict[str, Position]
    realized_pnl_all: float
    realized_pnl_today: float
    unrealized_pnl: float

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None:
        """获取某个品种的当前持仓。"""

    @abstractmethod
    def execute(self, signal: OrderSignal, **kwargs) -> dict:
        """执行策略信号（允许实现接受额外参数）。"""

