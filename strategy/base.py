from abc import ABC, abstractmethod
from typing import List
from market.models import Tick, OrderSignal

class Strategy(ABC):
    @abstractmethod
    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        """
        输入一个 Tick，输出 0~N 个信号。
        """
        ...
