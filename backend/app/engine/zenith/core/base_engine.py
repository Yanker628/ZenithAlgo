"""执行引擎基类（模板模式）。

目标：
- 把“数据推进/事件循环”与“策略/风控/执行/记录”解耦；
- 让 backtest/paper/live 在同一套接口上演进，避免逻辑漂移。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from zenith.core.sources.event_source import EventSource


@dataclass(frozen=True)
class EngineResult:
    """引擎运行结果（统一出口）。"""

    summary: Any
    artifacts: dict[str, Any] | None = None


class BaseEngine(ABC):
    """引擎抽象基类。"""

    @abstractmethod
    def run(self) -> EngineResult:
        raise NotImplementedError

    def run_loop(
        self,
        *,
        source: EventSource,
        on_tick: Callable[[Any], None],
        max_events: int | None = None,
        logger=None,
    ) -> None:
        """统一事件循环：对所有模式（回测/实盘/模拟）复用。"""
        if logger:
            logger.info("Engine loop start: source=%s", source.__class__.__name__)
        source.setup()
        try:
            n = 0
            for tick in source.events():
                on_tick(tick)
                n += 1
                if max_events is not None and n >= max_events:
                    if logger:
                        logger.info("Engine loop reached max_events=%s, stop.", max_events)
                    break
        finally:
            source.teardown()
            if logger:
                logger.info("Engine loop end.")
