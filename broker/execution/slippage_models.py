"""滑点模型。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SlippageModel(ABC):
    @abstractmethod
    def apply(self, *, price: float, side: str) -> float:
        raise NotImplementedError


class BpsSlippageModel(SlippageModel):
    """按 bp（万分比）施加滑点。买单抬高、卖单压低。"""

    def __init__(self, bp: float = 0.0):
        self.bp = float(bp)

    def apply(self, *, price: float, side: str) -> float:
        if self.bp == 0.0:
            return float(price)
        delta = float(price) * (self.bp / 10000.0)
        return float(price) + delta if side == "buy" else float(price) - delta

