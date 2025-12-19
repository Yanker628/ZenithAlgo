"""MarketClient 事件源（MarketEventSource）。

把 market_client.tick_stream(...) 包装为 EventSource，并在此处集中处理：
- setup/teardown 生命周期
- 断线重连
- 退避与抖动（避免死循环占满 CPU）
"""

from __future__ import annotations

import time
from typing import Iterator

from zenith.core.sources.event_source import EventSource
from zenith.common.models.models import Tick


class MarketEventSource(EventSource):
    def __init__(
        self,
        *,
        market_client,
        symbol: str,
        logger=None,
        backoff_initial_secs: float = 1.0,
        backoff_max_secs: float = 30.0,
        backoff_factor: float = 2.0,
        jitter_secs: float = 0.2,
    ):
        self._client = market_client
        self._symbol = str(symbol)
        self._logger = logger

        self._backoff_initial_secs = float(backoff_initial_secs)
        self._backoff_max_secs = float(backoff_max_secs)
        self._backoff_factor = float(backoff_factor)
        self._jitter_secs = float(jitter_secs)

        self._running = True

    def stop(self) -> None:
        self._running = False

    def setup(self) -> None:
        # 兼容未来 client 需要显式启动的场景
        for name in ("setup", "start", "connect"):
            fn = getattr(self._client, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    # setup 失败不阻断，交给 events() 的重试逻辑兜底
                    if self._logger:
                        self._logger.warning("Market client %s() failed, will retry in loop.", name)
                break

    def teardown(self) -> None:
        self._running = False
        for name in ("teardown", "stop", "close", "disconnect"):
            fn = getattr(self._client, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break

    def events(self) -> Iterator[Tick]:
        backoff = self._backoff_initial_secs
        while self._running:
            try:
                for tick in self._client.tick_stream(self._symbol):
                    yield tick
                    if not self._running:
                        return
                # 正常结束（对实时流不太可能）：也退避一下再继续
                raise RuntimeError("market tick stream ended")
            except Exception as exc:  # pragma: no cover
                if self._logger:
                    self._logger.warning("MarketEventSource error: %s (retry in %.1fs)", exc, backoff)
                sleep_for = min(self._backoff_max_secs, max(0.0, backoff))
                if self._jitter_secs > 0:
                    # 轻量抖动：避免多实例齐刷刷重连
                    sleep_for += (time.time() % self._jitter_secs)
                time.sleep(sleep_for)
                backoff = min(self._backoff_max_secs, max(self._backoff_initial_secs, backoff * self._backoff_factor))

