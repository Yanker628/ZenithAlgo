"""Broker 抽象接口与运行模式定义。"""

from enum import Enum
from abc import ABC, abstractmethod
from typing import Dict

from market.models import OrderSignal, Position


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

    Attributes
    ----------
    positions:
        当前持仓（symbol -> Position）。
    realized_pnl_all:
        累计已实现 PnL。
    realized_pnl_today:
        当日已实现 PnL。
    unrealized_pnl:
        未实现 PnL（按最后价格估算）。
    """

    positions: Dict[str, Position]
    realized_pnl_all: float
    realized_pnl_today: float
    unrealized_pnl: float

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None:
        """获取某个品种的当前持仓。

        Parameters
        ----------
        symbol:
            交易对，如 "BTCUSDT"。

        Returns
        -------
        Position | None
            若无持仓返回 None。
        """
        ...

    @abstractmethod
    def execute(self, signal: OrderSignal, **kwargs) -> dict:
        """执行策略信号。

        Parameters
        ----------
        signal:
            策略产生的订单信号。
        **kwargs:
            不同 broker 可接受额外参数（例如回测的 `tick_price/ts`）。

        Returns
        -------
        dict
            执行结果，至少包含 `status` 字段。
        """
        ...
