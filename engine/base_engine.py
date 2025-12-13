"""执行引擎基类（模板模式）。

目标：
- 把“数据推进/事件循环”与“策略/风控/执行/记录”解耦；
- 让 backtest/paper/live 在同一套接口上演进，避免逻辑漂移。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EngineResult:
    """引擎运行结果（统一出口）。"""

    summary: dict[str, Any]
    artifacts: dict[str, Any] | None = None


class BaseEngine(ABC):
    """引擎抽象基类。"""

    @abstractmethod
    def run(self) -> EngineResult:
        raise NotImplementedError

