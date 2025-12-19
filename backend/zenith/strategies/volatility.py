from __future__ import annotations

import collections
from typing import Any, Deque

from zenith.strategies.base import Strategy
from zenith.common.models.models import OrderSignal, Tick

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
        atr_period: int = 14,
        atr_stop_multiplier: float = 0.0,
        use_ma_exit: bool = False,
    ):
        super().__init__()
        self.window = int(window)
        self.k = float(k)
        # 固定比例 止损/止盈 (后备方案)
        self.stop_loss = float(stop_loss)
        self.take_profit = float(take_profit)
        
        # ATR 动态止损
        self.atr_period = int(atr_period)
        self.atr_stop_multiplier = float(atr_stop_multiplier)
        self.use_ma_exit = use_ma_exit
        
        # Buffers
        maxlen = max(self.window, self.atr_period) + 1
        self._closes: Deque[float] = collections.deque(maxlen=maxlen)
        self._highs: Deque[float] = collections.deque(maxlen=maxlen)
        self._lows: Deque[float] = collections.deque(maxlen=maxlen)
        
        # State
        self._position = 0.0 # 1=Long, -1=Short, 0=Flat
        self._sl_price = 0.0 # Stopped out price
        self._tp_price = 0.0 # Take profit price (if using fixed/ATR TP)

    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        # 从 features 提取 OHLC (由 EventSource 填充)
        # 如果缺失，回退到使用 tick.price
        high = tick.price
        low = tick.price
        close = tick.price
        price = tick.price
        
        if tick.features:
            high = tick.features.get("high", high)
            low = tick.features.get("low", low)
            close = tick.features.get("close", close)
        
        self._closes.append(close)
        self._highs.append(high) 
        self._lows.append(low)
        
        if len(self._closes) < max(self.window, self.atr_period):
            return []
            
        # 1. 计算指标
        closes = list(self._closes)
        avg = sum(closes[-self.window:]) / self.window
        
        # StdDev
        variance = sum((x - avg) ** 2 for x in closes[-self.window:]) / (self.window - 1)
        std_dev = variance ** 0.5
        
        upper = avg + self.k * std_dev
        lower = avg - self.k * std_dev
        
        # ATR 计算 (简化的 TR 移动平均)
        current_atr = 0.0
        if self.atr_stop_multiplier > 0:
            highs = list(self._highs)
            lows = list(self._lows)

            trs = []
            # 我们从列表末尾倒序迭代
            # We iterate backwards from end
            for i in range(1, self.atr_period + 1):
                idx = -i
                if abs(idx-1) > len(closes): break
                h = highs[idx]
                l = lows[idx]
                cp = closes[idx-1]
                tr = max(h - l, abs(h - cp), abs(l - cp))
                trs.append(tr)
            
            if len(trs) == self.atr_period:
                current_atr = sum(trs) / self.atr_period
        signal = None
        
        # Debug Logic removed


        # 2. Check Exits (SL/TP)
             
        # 2. 检查退出 (止损/止盈)
        if self._position == 1:
            # 多头退出
            # ATR 止损 (使用 Low 进行 bar 内止损检查)
            if self.atr_stop_multiplier > 0 and self._sl_price > 0:
                check_price = low if low > 0 else price
                if check_price <= self._sl_price:
                    # 在止损价处执行 (如果是跳空? 模拟中通常按 SL 价格或下一根 Open? 
                    # 现实中，如果 Low < SL，我们在 SL 处止损)
                    # 但 Event Source 提供的是 Tick(price=Close)。
                    # Broker 在 Tick Price 处成交。
                    # 理想情况下我们应该发送单独的信号?
                    # 暂时方案: 当 Low < SL 时，发出 Sell 信号。Broker 按 'price' (Close) 成交。
                    # 这意味着滑点。
                    # 为了匹配 Rust (Rust 可能根据 SL 触发计算 PnL?)，Rust 返回的 output (.., pnl) 使用的是 SL 价格?
                    # Rust output: `exit_price` 是 SL 价格 (简单模拟无滑点)。
                    # Python Event: 按 Close 成交。
                    # 我们无法在不使用 STOP 订单类型的情况下完全匹配 PnL。
                    # 但“时机”将匹配。立即触发总比等到 Close < SL 好。
                    signal = OrderSignal(
                        symbol=tick.symbol, 
                        side="sell", 
                        qty=1.0, 
                        price=price, 
                        reason="atr_sl_long"
                    )
                    self._position = 0
                    self._sl_price = 0.0
                    return [signal]
            
            # 简单 MA 退出 (可选)
            if self.use_ma_exit and price < avg:
                 signal = OrderSignal(
                     symbol=tick.symbol, 
                     side="sell", 
                     qty=1.0, 
                     price=price, 
                     reason="ma_exit_long"
                 )
                 self._position = 0
                 return [signal]

        elif self._position == -1:
            # 空头退出
             if self.atr_stop_multiplier > 0 and self._sl_price > 0:
                check_price = high if high > 0 else price
                # 空头止损在入场价上方
                if check_price >= self._sl_price:
                    signal = OrderSignal(
                        symbol=tick.symbol, 
                        side="buy", 
                        qty=1.0, 
                        price=price, 
                        reason="atr_sl_short"
                    )
                    self._position = 0
                    self._sl_price = 0.0
                    return [signal]
            
             if self.use_ma_exit and price > avg:
                 signal = OrderSignal(
                     symbol=tick.symbol, 
                     side="buy", 
                     qty=1.0, 
                     price=price, 
                     reason="ma_exit_short"
                 )
                 self._position = 0
                 return [signal]
        
        # 3. 检查入场
        if self._position == 0:
            if price > upper:
                # 向上突破 -> 做多
                # 使用当前 ATR 设置止损
                sl_price = 0.0
                if self.atr_stop_multiplier > 0:
                    dist = current_atr * self.atr_stop_multiplier
                    sl_price = price - dist
                
                signal = OrderSignal(
                    symbol=tick.symbol, 
                    side="buy", 
                    qty=1.0, 
                    price=price, 
                    reason="bollinger_break_up"
                )
                self._position = 1
                self._sl_price = sl_price
                
            elif price < lower:
                # 向下突破 -> 做空
                sl_price = 0.0
                if self.atr_stop_multiplier > 0:
                    dist = current_atr * self.atr_stop_multiplier
                    sl_price = price + dist # 空头止损在入场价上方
                    
                signal = OrderSignal(
                    symbol=tick.symbol, 
                    side="sell", 
                    qty=1.0, 
                    price=price, 
                    reason="bollinger_break_down"
                )
                self._position = -1
                self._sl_price = sl_price

        return [signal] if signal else []
