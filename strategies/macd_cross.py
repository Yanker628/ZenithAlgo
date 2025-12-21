import pandas as pd
import numpy as np

def strategy(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9, 
             rsi_window: int = 14, rsi_limit: float = 80.0, 
             trend_ema: int = 200, 
             atr_period: int = 14, atr_multiplier: float = 3.0,
             adx_period: int = 14, adx_limit: float = 25.0,
             # --- ✨ 最终参数：根据圣杯回测结果固化 ---
             trailing_pct: float = 0.10) -> pd.Series:
    """
    MACD + RSI + EMA + ATR + ADX + Trailing Stop (终极实战版)
    
    逻辑：
    1. 买入: 全方位过滤 (方向、动能、趋势、强度)
    2. 卖出 (退出/止盈):
       - MACD 死叉 (趋势转弱)
       - 价格跌破 昨天的吊灯线 (盘中触碰，保命止损)
       - 价格从最近高点回撤超过 trailing_pct (移动止盈，锁利)
    """
    
    # --- 1. 指标计算 (纯 Pandas 稳定版) ---
    # MACD
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(alpha=1/rsi_window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/rsi_window, adjust=False).mean()
    rsi = 100 - (100 / (1 + (avg_gain / (avg_loss + 1e-9))))
    
    # EMA 200
    ema_trend = df['close'].ewm(span=trend_ema, adjust=False).mean()
    
    # ATR 计算
    prev_close_for_atr = df['close'].shift(1)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - prev_close_for_atr).abs()
    tr3 = (df['low'] - prev_close_for_atr).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/atr_period, adjust=False).mean()
    
    # ADX 计算
    up_move = df['high'].diff()
    down_move = df['low'].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    smoothed_plus_dm = pd.Series(plus_dm, index=df.index).ewm(alpha=1/adx_period, adjust=False).mean()
    smoothed_minus_dm = pd.Series(minus_dm, index=df.index).ewm(alpha=1/adx_period, adjust=False).mean()
    plus_di = 100 * (smoothed_plus_dm / (atr + 1e-9))
    minus_di = 100 * (smoothed_minus_dm / (atr + 1e-9))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.ewm(alpha=1/adx_period, adjust=False).mean()

    # --- 2. 吊灯止损计算 ---
    highest_high_atr = df['high'].rolling(window=atr_period).max()
    chandelier_exit = highest_high_atr - (atr * atr_multiplier)
    prev_exit = chandelier_exit.shift(1)
    
    # --- 3. 盘中止损模拟 ---
    stop_hit_mask = (df['low'] < prev_exit)
    df.loc[stop_hit_mask, 'close'] = prev_exit[stop_hit_mask] * 0.999
    
    # --- 4. ✨ 移动止盈 (Trailing Stop) 计算 ---
    # 近 10 期最高收盘价作为参考点
    recent_high = df['close'].rolling(window=10).max()
    trailing_stop_price = recent_high * (1 - trailing_pct)
    
    # --- 5. 生成信号 ---
    signals = pd.Series(0, index=df.index)
    
    # 买入: 全方位过滤
    long_condition = (
        (macd_line > signal_line) & 
        (rsi < rsi_limit) & 
        (df['close'] > ema_trend) &
        (adx > adx_limit)
    )
    
    # 卖出: 动能反转 或 跌破止损线 或 触发移动止盈
    exit_condition = (
        (macd_line < signal_line) | 
        (df['close'] < prev_exit) | 
        (df['close'] < trailing_stop_price)
    )
    
    signals[long_condition] = 1
    signals[exit_condition] = 0
    
    return signals
