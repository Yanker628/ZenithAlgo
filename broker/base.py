from enum import Enum
from abc import ABC, abstractmethod
from typing import Dict

from market.models import OrderSignal, Position

class BrokerMode(Enum):
    DRY_RUN = "dry-run"
    PAPER = "paper"
    LIVE = "live"
    LIVE_TESTNET = "live-testnet"
    LIVE_MAINNET = "live-mainnet"

class Broker(ABC):
    positions: Dict[str, Position]
    realized_pnl_all: float
    realized_pnl_today: float
    unrealized_pnl: float

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None:
        ...

    @abstractmethod
    def execute(self, signal: OrderSignal) -> dict:
        """
        执行信号，返回执行结果（成交价、数量、状态等）。
        V1 可简单返回 {"status": "filled"}。
        """
        ...
