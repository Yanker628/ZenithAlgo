from __future__ import annotations

import collections
from typing import Any, Deque

from algo.strategy.base import Strategy
from shared.models.models import OrderSignal, Tick

class VolatilityBreakoutStrategy(Strategy):
    """
    波动率突破策略 (Bollinger Breakout)。
    
    逻辑:
    1. 计算布林带: Mid = MA(Close, N), Upper = Mid + K * StdDev, Lower = Mid - K * StdDev
    2. 如果 Close > Upper: 开多 (Buy)
    3. 如果 Close < Lower: 开空 (Sell) - (如果允许做空)
    4. 止损/止盈: 固定百分比 or ATR
    
    Params:
    - window: MA窗口 (default 20)
    - k: 标准差倍数 (default 2.0)
    """

    def __init__(
        self,
        window: int = 20,
        k: float = 2.0,
        stop_loss: float = 0.05,
        take_profit: float = 0.1,
    ):
        super().__init__()
        self.window = int(window)
        self.k = float(k)
        self.stop_loss = float(stop_loss)
        self.take_profit = float(take_profit)
        
        # 缓存价格用于计算指标
        self._closes: Deque[float] = collections.deque(maxlen=self.window)
        self._position = 0.0 # 简单状态追踪: 1=Long, -1=Short, 0=Flat

    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        self._closes.append(tick.price)
        
        if len(self._closes) < self.window:
            return []
            
        # 计算指标 (Naive Python Implementation for Event-Driven)
        # 在 Vector 模式下会用 Rust 计算，这里是 Event-Driven 的 fallback 或者实盘逻辑
        closes = list(self._closes)
        avg = sum(closes) / len(closes)
        
        # StdDev
        variance = sum((x - avg) ** 2 for x in closes) / (len(closes) - 1)
        std_dev = variance ** 0.5
        
        upper = avg + self.k * std_dev
        lower = avg - self.k * std_dev
        
        price = tick.price
        signal = None
        
        # 状态机逻辑
        if self._position == 0:
            if price > upper:
                # Breakout Up -> Buy
                signal = OrderSignal(
                    symbol=tick.symbol,
                    side="buy", # SignalType.BUY -> "buy"
                    qty=1.0, # Placeholder
                    price=price,
                    reason="bollinger_break_up"
                )
                self._position = 1
            elif price < lower:
                # Breakout Down -> Sell (Optional, for now just Long logic or specific short)
                # 假设支持做空
                signal = OrderSignal(
                    symbol=tick.symbol,
                    side="sell", # SignalType.SELL -> "sell"
                    qty=1.0,
                    price=price,
                    reason="bollinger_break_down"
                )
                self._position = -1
                
        elif self._position == 1:
            # 持多仓
            # 退出条件: 回归均值? 或者反向突破? 
            # 简单起见: 价格跌破均线平仓 (Mean Reversion Exit)
            if price < avg:
                 signal = OrderSignal(
                    symbol=tick.symbol,
                    side="sell",
                    qty=1.0,
                    price=price,
                    reason="ma_exit_long"
                )
                 self._position = 0
                 
        elif self._position == -1:
            # 持空仓
            # 退出条件: 价格升破均线平仓
            if price > avg:
                 signal = OrderSignal(
                    symbol=tick.symbol,
                    side="buy",
                    qty=1.0,
                    price=price,
                    reason="ma_exit_short"
                )
                 self._position = 0

        return [signal] if signal else []
