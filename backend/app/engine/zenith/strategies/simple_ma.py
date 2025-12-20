"""简单均线交叉策略。

核心逻辑：当短周期均线向上突破长周期均线时买入（金叉），反之卖出（死叉）。
"""

from collections import deque
from datetime import datetime
import math
from typing import Deque

from zenith.common.models.models import Tick, OrderSignal
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
            # 1. 优先使用外部计算好的特征 (features)
            # 适用于回测或已有特征工程的情况
            short_ma = float(tick.features[self.short_feature])
            long_ma = float(tick.features[self.long_feature])
            if math.isnan(short_ma) or math.isnan(long_ma):
                return []
        else:
            if self.require_features:
                return []
            
            # 2. 如果没有特征，则在内存中维护价格队列实时计算 (Streaming 计算)
            self.prices.append(tick.price)
            if len(self.prices) < self.long_window:
                return []

            short_ma = sum(list(self.prices)[-self.short_window:]) / self.short_window
            long_ma = sum(self.prices) / len(self.prices)

        # 信号强度过滤 (Noise Filter)：
        # 如果两条均线过于接近（粘合），往往意味着震荡行情，此时交叉信号不可靠，容易反复止损（Whipsaw）。
        # 通过引入 min_ma_diff 阈值，只有当趋势明显（开口扩大）时才允许触发信号。
        if short_ma is None or long_ma is None:
            return []
        if abs(short_ma - long_ma) < self.min_ma_diff:
            return []

        now = tick.ts
        # 冷却过滤 (Cool-down)：
        # 防止在短时间内对同一信号连续发单（虽然 ClientOrderId 可以去重，但策略层应主动节制）。
        # 例如网络延迟或数据抖动导致短时间内多次收到相似 Tick。
        if now and self.last_trade_ts is not None:
            delta = (now - self.last_trade_ts).total_seconds()
            if delta < self.cooldown_secs:
                return []

        signals: list[OrderSignal] = []

        # 状态机逻辑 (State Machine)：
        # 仅当信号发生翻转（Signal Flip）时才产生动作。
        # 如果当前持有 Long 仓位 (last_signal="long") 且均线仍多头排列，则保持不动。
        if short_ma > long_ma and self.last_signal != "long":
            # 金叉：短周期上穿长周期 -> 买入做多
            signals.append(OrderSignal(symbol=tick.symbol, side="buy", qty=0.0, reason="ma_cross_up"))
            self.last_signal = "long"
            self.last_trade_ts = now
        elif short_ma < long_ma and self.last_signal != "short":
            # 死叉：短周期下穿长周期 -> 卖出做空 (或平多反手)
            # 注意：具体是平仓还是反手开空，取决于 Execution 层和 Config 的 mode (LongOnly vs LS)。
            # 策略层只负责发出 "看空" 信号。
            signals.append(OrderSignal(symbol=tick.symbol, side="sell", qty=0.0, reason="ma_cross_down"))
            self.last_signal = "short"
            self.last_trade_ts = now

        return signals
