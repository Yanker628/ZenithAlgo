"""策略抽象接口定义。"""

from abc import ABC, abstractmethod

from zenith.common.models.models import Tick, OrderSignal

class Strategy(ABC):
    """策略抽象基类。"""

    @abstractmethod
    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        """处理单个 Tick 并输出交易信号。

        Parameters
        ----------
        tick:
            市场 Tick 数据。

        Returns
        -------
        list[OrderSignal]
            0~N 个订单信号。
        """
        ...
