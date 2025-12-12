"""趋势过滤策略（Trend Filtered Strategy）。

V2.3 语义：
- 优先从 `Tick.features` 读取指标列（推荐：由 factors 层计算）。
- 若 features 缺失且启用 fallback，则用本地缓冲做简化计算（便于 runner/paper 也能跑）。
"""

from __future__ import annotations

from collections import deque
import math
from typing import Deque

from market.models import OrderSignal, Tick
from strategy.base import Strategy


def _is_finite(x: float | None) -> bool:
    return x is not None and not math.isnan(x) and not math.isinf(x)


class TrendFilteredStrategy(Strategy):
    """趋势过滤策略：Regime + Slope +（可选）ATR trailing stop。

    Entry:
    - 金叉：短均线从 <= 长均线 变为 > 长均线
    - Regime：price > 长均线
    - Slope：长均线斜率 > 阈值（百分比）

    Exit:
    - 可选：ATR 移动止损（从入场后最高价回撤 N*ATR）
    - 可选：死叉（短均线 < 长均线）

    Notes
    -----
    策略只输出方向信号（qty=0），真实下单量由 sizing 统一决定。
    """

    def __init__(
        self,
        short_window: int = 10,
        long_window: int = 60,
        slope_threshold: float = 0.1,
        slope_lookback: int = 5,
        atr_period: int = 14,
        atr_stop_multiplier: float = 2.0,
        short_feature: str = "ma_short",
        long_feature: str = "ma_long",
        atr_feature: str = "atr_14",
        require_features: bool = False,
        fallback_to_local: bool = True,
        stop_on_death_cross: bool = True,
        stop_on_atr: bool = True,
    ):
        self.short_window = int(short_window)
        self.long_window = int(long_window)
        self.slope_threshold = float(slope_threshold)
        self.slope_lookback = int(slope_lookback)
        self.atr_period = int(atr_period)
        self.atr_stop_multiplier = float(atr_stop_multiplier)

        self.short_feature = str(short_feature)
        self.long_feature = str(long_feature)
        self.atr_feature = str(atr_feature)
        self.require_features = bool(require_features)
        self.fallback_to_local = bool(fallback_to_local)
        self.stop_on_death_cross = bool(stop_on_death_cross)
        self.stop_on_atr = bool(stop_on_atr)

        self._in_position = False
        self.entry_price = 0.0
        self.highest_price_since_entry = 0.0

        self._prev_short_ma: float | None = None
        self._prev_long_ma: float | None = None

        maxlen = max(self.long_window + 5, self.atr_period + 5, self.slope_lookback + 5, 32)
        self._closes: Deque[float] = deque(maxlen=maxlen)
        self._highs: Deque[float] = deque(maxlen=maxlen)
        self._lows: Deque[float] = deque(maxlen=maxlen)
        self._trs: Deque[float] = deque(maxlen=maxlen)
        self._long_ma_hist: Deque[float] = deque(maxlen=max(self.slope_lookback + 2, 8))

        self.last_skip_reason: str | None = None

    def _get_feature(self, tick: Tick, name: str) -> float | None:
        if not tick.features:
            return None
        val = tick.features.get(name)
        if val is None:
            return None
        try:
            val_f = float(val)
        except Exception:
            return None
        return val_f if _is_finite(val_f) else None

    def _sma(self, values: list[float], window: int) -> float | None:
        if window <= 0 or len(values) < window:
            return None
        chunk = values[-window:]
        return sum(chunk) / window

    def _update_local_buffers(self, tick: Tick) -> None:
        close = float(tick.price)
        high = float(getattr(tick, "high", close))
        low = float(getattr(tick, "low", close))
        prev_close = self._closes[-1] if self._closes else close

        self._closes.append(close)
        self._highs.append(high)
        self._lows.append(low)

        if hasattr(tick, "high") and hasattr(tick, "low"):
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            tr = max(tr1, tr2, tr3)
        else:
            tr = abs(close - prev_close)
        self._trs.append(tr)

    def _compute_local_indicators(self) -> tuple[float | None, float | None, float | None]:
        closes = list(self._closes)
        short_ma = self._sma(closes, self.short_window)
        long_ma = self._sma(closes, self.long_window)
        atr = self._sma(list(self._trs), self.atr_period)
        return short_ma, long_ma, atr

    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        self.last_skip_reason = None
        signals: list[OrderSignal] = []

        curr_price = float(tick.price)

        short_ma = self._get_feature(tick, self.short_feature)
        long_ma = self._get_feature(tick, self.long_feature)
        atr = self._get_feature(tick, self.atr_feature) if self.atr_feature else None

        if short_ma is None or long_ma is None:
            if self.require_features:
                self.last_skip_reason = "missing_features"
                return []
            if not self.fallback_to_local:
                self.last_skip_reason = "no_fallback"
                return []
            self._update_local_buffers(tick)
            short_ma, long_ma, atr_local = self._compute_local_indicators()
            if short_ma is None or long_ma is None:
                self.last_skip_reason = "insufficient_history"
                return []
            if atr is None:
                atr = atr_local
        else:
            if self.fallback_to_local:
                self._update_local_buffers(tick)

        # slope：使用 long_ma 历史
        self._long_ma_hist.append(float(long_ma))
        slope = None
        if len(self._long_ma_hist) >= self.slope_lookback + 1 and self.slope_lookback > 0:
            prev = self._long_ma_hist[-1 - self.slope_lookback]
            if prev != 0 and _is_finite(prev):
                slope = (float(long_ma) - float(prev)) / float(prev) * 100.0

        prev_short_ma = self._prev_short_ma
        prev_long_ma = self._prev_long_ma
        self._prev_short_ma = float(short_ma)
        self._prev_long_ma = float(long_ma)

        # === Exit ===
        if self._in_position:
            self.highest_price_since_entry = max(self.highest_price_since_entry, curr_price)

            if self.stop_on_atr and _is_finite(atr) and atr and atr > 0:
                stop_price = self.highest_price_since_entry - (self.atr_stop_multiplier * float(atr))
                if curr_price < stop_price:
                    signals.append(
                        OrderSignal(symbol=tick.symbol, side="sell", qty=0.0, reason="atr_trailing_stop")
                    )
                    self._reset_position_state()
                    return signals

            if self.stop_on_death_cross and _is_finite(short_ma) and _is_finite(long_ma):
                if float(short_ma) < float(long_ma):
                    signals.append(
                        OrderSignal(symbol=tick.symbol, side="sell", qty=0.0, reason="ma_death_cross")
                    )
                    self._reset_position_state()
                    return signals

            return []

        # === Entry ===
        if prev_short_ma is None or prev_long_ma is None:
            self.last_skip_reason = "no_prev_ma"
            return []

        is_gold_cross = float(prev_short_ma) <= float(prev_long_ma) and float(short_ma) > float(long_ma)
        if not is_gold_cross:
            self.last_skip_reason = "no_gold_cross"
            return []

        if curr_price <= float(long_ma):
            self.last_skip_reason = "regime_reject"
            return []

        if slope is None or slope <= self.slope_threshold:
            self.last_skip_reason = "slope_reject"
            return []

        signals.append(OrderSignal(symbol=tick.symbol, side="buy", qty=0.0, reason="trend_filtered_entry"))
        self._in_position = True
        self.entry_price = curr_price
        self.highest_price_since_entry = curr_price
        return signals

    def _reset_position_state(self) -> None:
        self._in_position = False
        self.entry_price = 0.0
        self.highest_price_since_entry = 0.0
