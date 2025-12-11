from collections import deque
from datetime import datetime
from typing import Deque

from market.models import Tick, OrderSignal
from .base import Strategy


class SimpleMAStrategy(Strategy):
    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        min_ma_diff: float = 0.5,  # 最小 MA 差值（单位：价格）
        cooldown_secs: int = 10,  # 冷却时间，避免频繁交易（单位：秒）
    ):
        self.short_window = short_window
        self.long_window = long_window
        self.min_ma_diff = min_ma_diff
        self.cooldown_secs = cooldown_secs
        self.last_trade_ts: datetime | None = None
        self.prices: Deque[float] = deque(maxlen=long_window)
        self.last_signal: str | None = None  # "long" / "short" / None

    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        self.prices.append(tick.price)
        if len(self.prices) < self.long_window:
            return []

        short_ma = sum(list(self.prices)[-self.short_window:]) / self.short_window
        long_ma = sum(self.prices) / len(self.prices)

        # 信号强度过滤
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
            signals.append(OrderSignal(symbol=tick.symbol, side="buy", qty=0.1, reason="ma_cross_up"))
            self.last_signal = "long"
            self.last_trade_ts = now
        elif short_ma < long_ma and self.last_signal != "short":
            signals.append(OrderSignal(symbol=tick.symbol, side="sell", qty=0.1, reason="ma_cross_down"))
            self.last_signal = "short"
            self.last_trade_ts = now

        return signals
