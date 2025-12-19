"""
Tick 级高频剥头皮策略 (仅用于测试系统吞吐量和延迟).
逻辑：维护最近 N 个 Tick 的价格均值。价格上穿均值卖出，下穿均值买入。
"""
from collections import deque
from datetime import datetime, timedelta, timezone
from zenith.strategies.base import Strategy
from zenith.common.models.models import Tick, OrderSignal

class TickScalper(Strategy):
    def __init__(self, window: int = 20, threshold: float = 0.0001):
        """
        Args:
            window: 计算最近多少个 Tick 的均值
            threshold: 触发交易的偏离阈值 (百分比，0.0001 = 0.01%)
        """
        super().__init__()
        self.window = window
        self.threshold = threshold
        self.prices = deque(maxlen=window)
        self.last_signal_ts = datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _as_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        tick_ts = self._as_utc(tick.ts)
        self.prices.append(tick.price)
        
        # 1. 数据不足时不交易
        if len(self.prices) < self.window:
            return []

        # 2. 计算 Tick 均值
        avg_price = sum(self.prices) / len(self.prices)
        
        # 3. 计算偏离度
        deviation = (tick.price - avg_price) / avg_price
        
        # 4. 生成信号 (反转策略：涨多了卖，跌多了买)
        signal = None
        
        # 为了防止一秒内发太多单，可以加个简单的冷却 (可选)
        if tick_ts - self.last_signal_ts < timedelta(seconds=1): # 1秒冷却
            return []

        if deviation > self.threshold:
            # 价格高于均值 -> 卖出平仓或做空
            signal = OrderSignal(
                symbol=tick.symbol,
                side="sell",
                qty=0.0, # 让 sizing 模块决定数量
                reason=f"scalp_sell_dev_{deviation:.5f}"
            )
        elif deviation < -self.threshold:
            # 价格低于均值 -> 买入
            signal = OrderSignal(
                symbol=tick.symbol,
                side="buy",
                qty=0.0, 
                reason=f"scalp_buy_dev_{deviation:.5f}"
            )

        if signal:
            self.last_signal_ts = tick_ts
            return [signal]
        
        return []
