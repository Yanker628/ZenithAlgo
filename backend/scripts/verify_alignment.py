
import numpy as np
import pandas as pd
from typing import List
import logging

try:
    from zenith.extensions.rust_wrapper import RustSimulator
except ImportError:
    import sys
    import os
    # Add engine path to sys.path
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../app/engine")))
    from zenith.extensions.rust_wrapper import RustSimulator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VerifyAlignment")

def generate_random_data(n=1000, seed=42):
    np.random.seed(seed)
    # Generate random walk for prices
    returns = np.random.normal(0.0001, 0.01, n)
    price = 100 * np.cumprod(1 + returns)
    
    # Generate High/Low based on Close
    # Low is randomly slightly lower, High is slightly higher
    low = price * (1 - np.random.uniform(0, 0.005, n))
    high = price * (1 + np.random.uniform(0, 0.005, n))
    
    return pd.DataFrame({
        "close": price,
        "high": high,
        "low": low
    })

def verify_ma(sim, df, window=20, atol=1e-8):
    logger.info(f"Verifying SMA (window={window})...")
    # Python (Pandas)
    py_ma = df["close"].rolling(window).mean()
    
    # Rust
    rust_ma = sim.calculate_indicators(df["close"].tolist(), "ma", window)
    rust_ma = pd.Series(rust_ma)

    # Align: Check overlap
    # First (window-1) are NaN in both
    valid_py = py_ma.iloc[window-1:]
    valid_rust = rust_ma.iloc[window-1:]
    
    diff = np.abs(valid_py - valid_rust)
    max_diff = diff.max()
    
    if max_diff > atol:
        logger.error(f"❌ MA Verification Failed! Max Diff: {max_diff}")
        return False
    logger.info(f"✅ MA Aligned. Max Diff: {max_diff:.2e}")
    return True

def verify_stddev(sim, df, window=20, atol=1e-8):
    logger.info(f"Verifying StdDev (window={window})...")
    # Python (Pandas rolling std uses ddof=1 by default, matching Rust's sample stddev assumption)
    py_std = df["close"].rolling(window).std(ddof=1)
    
    # Rust
    rust_std = sim.calculate_indicators(df["close"].tolist(), "stddev", window)
    rust_std = pd.Series(rust_std)

    valid_py = py_std.iloc[window:] # Rolling std often nan for longer? No, window-1 usually.
    valid_rust = rust_std.iloc[window:] # Let's be safe
    
    # Replace any remaining NaNs (e.g. from 0 variance) with 0 or skip
    mask = ~valid_py.isna() & ~valid_rust.isna()
    diff = np.abs(valid_py[mask] - valid_rust[mask])
    max_diff = diff.max()
    
    if max_diff > atol:
        logger.error(f"❌ StdDev Verification Failed! Max Diff: {max_diff}")
        return False
    logger.info(f"✅ StdDev Aligned. Max Diff: {max_diff:.2e}")
    return True

def verify_rsi(sim, df, period=14, atol=1e-8):
    logger.info(f"Verifying RSI (SMA version, period={period})...")
    # Python Manual Implementation (SMA based)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    
    rs = gain / loss
    py_rsi = 100 - (100 / (1 + rs))
    
    # Handle division by zero case (loss=0 -> RSI=100)
    py_rsi = py_rsi.fillna(0) # First period are nan
    py_rsi[loss == 0] = 100
    
    # Rust
    rust_rsi = sim.calculate_indicators(df["close"].tolist(), "rsi", period)
    rust_rsi = pd.Series(rust_rsi)
    
    # Rust returns NaN for first period.
    valid_idx = period + 1 
    
    mask = ~py_rsi.isna() & ~rust_rsi.isna()
    # Slice carefully
    s_py = py_rsi[mask]
    s_rs = rust_rsi[mask]
    
    diff = np.abs(s_py - s_rs)
    max_diff = diff.max()
    
    if max_diff > atol:
        # Check if divergence is due to initial values or calculation method
        logger.error(f"❌ RSI Verification Failed! Max Diff: {max_diff}")
        return False
    logger.info(f"✅ RSI Aligned. Max Diff: {max_diff:.2e}")
    return True

def verify_atr(sim, df, period=14, atol=1e-8):
    logger.info(f"Verifying ATR (SMA version, period={period})...")
    # Python Implementation
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # Rust uses SMA of TR
    py_atr = tr.rolling(period).mean()
    
    # Rust
    rust_atr = sim.calculate_atr(high.tolist(), low.tolist(), close.tolist(), period)
    rust_atr = pd.Series(rust_atr)
    
    # Align
    mask = ~py_atr.isna() & ~rust_atr.isna()
    max_diff = np.abs(py_atr[mask] - rust_atr[mask]).max()
    
    if max_diff > atol:
        logger.error(f"❌ ATR Verification Failed! Max Diff: {max_diff}")
        return False
    logger.info(f"✅ ATR Aligned. Max Diff: {max_diff:.2e}")
    return True

def main():
    logger.info("Initializing Alignment Verification...")
    df = generate_random_data(n=5000)
    sim = RustSimulator()
    
    checks = [
        verify_ma(sim, df, window=20),
        verify_stddev(sim, df, window=20),
        verify_rsi(sim, df, period=14),
        verify_atr(sim, df, period=14)
    ]
    
    if all(checks):
        logger.info("\n🎉 All Alignment Checks Passed! (M7 Goal Met)")
    else:
        logger.error("\n⚠️ Some checks failed. Please review implementation details.")
        exit(1)

if __name__ == "__main__":
    main()
