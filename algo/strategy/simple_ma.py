"""简单均线交叉策略。"""

from collections import deque
from datetime import datetime
import math
from typing import Deque

from shared.models.models import Tick, OrderSignal
from .base import Strategy


class SimpleMAStrategy(Strategy):
    """简单移动均线交叉策略。

    Parameters
    ----------
    short_window:
        短期均线窗口。
    long_window:
        长期均线窗口。
    min_ma_diff:
        触发信号的最小均线差（去抖动）。
    cooldown_secs:
        信号冷却时间（秒）。
    """

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        min_ma_diff: float = 0.5,  # 最小 MA 差值（单位：价格）
        cooldown_secs: int = 10,  # 冷却时间，避免频繁交易（单位：秒）
        short_feature: str = "ma_short",
        long_feature: str = "ma_long",
        require_features: bool = False,
    ):
        self.short_window = short_window
        self.long_window = long_window
        self.min_ma_diff = min_ma_diff
        self.cooldown_secs = cooldown_secs
        self.short_feature = short_feature
        self.long_feature = long_feature
        self.require_features = require_features
        self.last_trade_ts: datetime | None = None
        self.prices: Deque[float] = deque(maxlen=long_window)
        self.last_signal: str | None = None  # "long" / "short" / None

    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        """输入 Tick 输出 MA 交叉信号。"""
        short_ma: float | None = None
        long_ma: float | None = None

        if tick.features and self.short_feature in tick.features and self.long_feature in tick.features:
            short_ma = float(tick.features[self.short_feature])
            long_ma = float(tick.features[self.long_feature])
            if math.isnan(short_ma) or math.isnan(long_ma):
                return []
        else:
            if self.require_features:
                return []
            self.prices.append(tick.price)
            if len(self.prices) < self.long_window:
                return []

            short_ma = sum(list(self.prices)[-self.short_window:]) / self.short_window
            long_ma = sum(self.prices) / len(self.prices)

        # 信号强度过滤
        if short_ma is None or long_ma is None:
            return []
        if abs(short_ma - long_ma) < self.min_ma_diff:
            return []

        now = tick.ts
        # 冷却过滤
        if now and self.last_trade_ts is not None:
            delta = (now - self.last_trade_ts).total_seconds()
            if delta < self.cooldown_secs:
                return []

        signals: list[OrderSignal] = []

        if short_ma > long_ma and self.last_signal != "long":
            signals.append(OrderSignal(symbol=tick.symbol, side="buy", qty=0.0, reason="ma_cross_up"))
            self.last_signal = "long"
            self.last_trade_ts = now
        elif short_ma < long_ma and self.last_signal != "short":
            signals.append(OrderSignal(symbol=tick.symbol, side="sell", qty=0.0, reason="ma_cross_down"))
            self.last_signal = "short"
            self.last_trade_ts = now

        return signals
