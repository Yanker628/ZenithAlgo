import pandas as pd
import pandas_ta as ta

def strategy(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """
    MACD Crossover Strategy
    Returns: Series with 1 (Long), -1 (Short), 0 (Neutral)
    """
    # Calculate MACD
    # Ensure we use 'close' column
    macd = df.ta.macd(close='close', fast=fast, slow=slow, signal=signal)
    
    # pandas_ta returns columns like MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    # We need to identify them dynamically or constructing them manually
    macd_col = macd[f'MACD_{fast}_{slow}_{signal}']
    signal_col = macd[f'MACDs_{fast}_{slow}_{signal}']
    
    # Generate Signals
    # 1 where macd > signal (Bulish), -1 where macd < signal (Bearish)
    # This is a "Always In" strategy for simplicity
    
    signals = pd.Series(0, index=df.index)
    signals[macd_col > signal_col] = 1
    signals[macd_col < signal_col] = -1
    
    return signals
