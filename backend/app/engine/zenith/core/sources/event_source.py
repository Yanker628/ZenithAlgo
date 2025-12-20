"""事件源抽象（EventSource）。

目标：把“获取下一个事件（Tick/K 线）”从 engine 中剥离出来。
引擎只负责消费事件，不关心事件来自 CSV 还是 WebSocket。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Iterator, Sequence

import pandas as pd

from zenith.common.models.models import Tick


class EventSource(ABC):
    """事件源抽象基类。"""

    def setup(self) -> None:
        """可选初始化钩子（例如建立 WS 连接）。"""

    def teardown(self) -> None:
        """可选清理钩子（例如关闭连接）。"""

    @abstractmethod
    def events(self) -> Iterator[Tick]:
        """核心生成器：产生 Tick 事件流。"""
        raise NotImplementedError


class PandasFrameEventSource(EventSource):
    """把 DataFrame 转成 Tick 事件流。

    约定：df 至少包含列 `ts/symbol/close`；若有特征列会写入 Tick.features。
    """

    def __init__(self, df: pd.DataFrame, *, feature_cols: Sequence[str] | None = None):
        self._df = df
        self._feature_cols = list(feature_cols or [])

    def events(self) -> Iterator[Tick]:
        if self._df.empty:
            return
            yield  # pragma: no cover
        feature_cols = [c for c in self._feature_cols if c in self._df.columns]
        for _, row in self._df.iterrows():
            ts = row["ts"]
            symbol = str(row["symbol"])
            price = float(row["close"])
            features = {}
            if feature_cols:
                for c in feature_cols:
                    v = row[c]
                    if pd.notna(v):
                        features[c] = float(v)
            
            # Auto-include OHLCV if present (Essential for strategy usage)
            for f in ["open", "high", "low", "volume"]:
                if f in self._df.columns:
                    features[f] = float(row[f])

            if not features:
                features = None
            yield Tick(symbol=symbol, price=price, ts=ts, features=features)


class IteratorEventSource(EventSource):
    """把任意 Tick 迭代器包装成 EventSource。"""

    def __init__(self, iterator: Iterable[Tick]):
        self._iterator = iterator

    def events(self) -> Iterator[Tick]:
        yield from self._iterator

