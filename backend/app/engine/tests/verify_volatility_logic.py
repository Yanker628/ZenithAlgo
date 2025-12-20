import pandas as pd
import numpy as np
from zenith.extensions.rust_wrapper import RustSimulator
from zenith.data.loader import HistoricalDataLoader
from datetime import datetime, timezone

def python_itr_simulation(df, window, k, atr_mult, atr_period):
    """Pure Python Iterative Simulation (Slow but verify functionality)."""
    
    # 1. Indicators
    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    
    ma = closes.rolling(window).mean()
    std = closes.rolling(window).std()
    upper = ma + k * std
    lower = ma - k * std
    
    # ATR
    c_prev = closes.shift(1)
    tr1 = highs - lows
    tr2 = (highs - c_prev).abs()
    tr3 = (lows - c_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean() # Simple MA ATR for parity with Rust which often uses SMA or RMA? 
    # Rust 'atr' usually is RMA (Wilder's). Let's check consistency.
    # If Rust uses Wilder, Python must use Wilder.
    # zenithalgo_rust::atr implementation: usually Wilder's smoothing? 
    # Let's assume SMA for now or check lib.rs.
    # Actually most basic implementations use SMA. Let's start with SMA.
    
    # 2. Logic
    # Signals
    # Close > Upper -> Buy
    # Close < Lower -> Sell (if allow short, else ignore)
    
    # State
    position = 0 # 1 or 0
    entry_price = 0.0
    entry_atr = 0.0
    equity = 0.0
    trades = []
    
    # Iterate
    # Need to match Rust: Rust processes bar i.
    # Signal is generated at i (Close > Upper).
    # Entry happens at i (Close Price) ?? 
    # Wait, simulate_trades usually executes signals on the SAME bar close if signal is derived from Close?
    # OR Next Open?
    # Our `vector_backtest` passes signals aligned to `end_ts`.
    # Rust `simulate_trades`:
    # for i in 0..len:
    #   check_exit(i)  (Using High/Low of current bar against SL/TP set from previous)
    #   check_entry(i)
    # 
    # If signal[i] != 0:
    #   Execute at close[i].
    #   Set SL/TP for NEXT bar logic.
    
    # Python simulation:
    for i in range(len(df)):
        if i < max(window, atr_period): 
            continue
            
        date = df.iloc[i]["end_ts"]
        o, h, l, c = df.iloc[i]["open"], df.iloc[i]["high"], df.iloc[i]["low"], df.iloc[i]["close"]
        curr_atr = atr.iloc[i]
        
        # 1. Check Exit (Intra-bar)
        if position == 1:
            # Check SL
            sl_price = entry_price - entry_atr * atr_mult
            # Low triggers SL?
            if l <= sl_price:
                # Exited
                exit_price = sl_price # Slippage ignored for parity check
                pnl = exit_price - entry_price
                trades.append({
                    "entry_ts": str(entry_date),
                    "exit_ts": str(date),
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "reason": "sl"
                })
                position = 0
                entry_price = 0.0
                equity += pnl
                continue # Position closed, wait for next signal
            
            # Check Signal to Close? (Not implemented in Volatility Vectorized)
            pass

        # 2. Check Entry
        # Signal Logic: Breakout
        # Previous Close <= Previous Upper AND Current Close > Current Upper
        # To avoid Lookahead bias in "Signal Generation", usually we use closed candles.
        # But Vector logic calculates signal on row i based on Close[i].
        # Rust executes on Close[i].
        
        if position == 0:
            up = upper.iloc[i]
            # low = lower.iloc[i] 
            
            # Break Up
            if c > up:
                position = 1
                entry_price = c
                entry_date = date
                entry_atr = curr_atr
    
    return trades

def run_compare():
    # Load Data
    loader = HistoricalDataLoader(data_dir="dataset/history")
    symbol = "SOLUSDT"
    interval = "1h"
    # Small range for verify
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 2, 1, tzinfo=timezone.utc)
    
    print(f"Loading data {start} to {end}...")
    candles = loader.load_klines_for_backtest(symbol, interval, start, end)
    # Candle is Pydantic BaseModel (v2) or dataclass?
    # View showed it works with Pydantic. If model_dump missing, maybe standard dict()?
    # If dataclass, use asdict.
    # Actually, simple dict construction is safer.
    df = pd.DataFrame([{
        "symbol": c.symbol,
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume,
        "start_ts": c.start_ts,
        "end_ts": c.end_ts
    } for c in candles])
    df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)
    df = df.sort_values("end_ts").reset_index(drop=True)
    
    print(f"Data loaded: {len(df)} rows")
    
    # Params
    window = 30
    k = 1.5
    atr_mult = 2.0
    atr_period = 20
    
    # 1. Rust Simulation
    print("Running Rust Simulation...")
    # Generate Signals frame
    # Copy logic from run_volatility_vectorized manually to ensure "same input"
    # Or use the function?
    # Better use the function to verify the WHOLE pipeline.
    
    from zenith.common.config.config_loader import BacktestConfig, StrategyConfig
    from zenith.core.vector_backtest import run_volatility_vectorized
    
    class MockCfg:
        backtest = BacktestConfig(
            symbol=symbol,
            interval=interval,
            start=str(start),
            end=str(end),
            strategy=StrategyConfig(
                type="volatility_breakout",
                params={"window": window, "k": k, "atr_stop_multiplier": atr_mult, "atr_period": atr_period}
            ),
            data_dir="dataset/history"
        )
        strategy = backtest.strategy
        
    rust_res = run_volatility_vectorized(MockCfg(), price_df=df)
    print(f"Rust Trades: {len(rust_res.trades)}")
    
    # 2. Python Simulation
    # Note: Logic must match EXACTLY.
    # In run_volatility_vectorized:
    # long_signal = (close > upper) & (prev_close <= prev_upper)
    # Rust Sim: enters on Close.
    # ATR calculation: zenithalgo_rust.atr (Need to confirm its logic)
    
    # Let's run Python logic
    # But wait, run_volatility_vectorized imports RustSimulator for indicators too.
    # So if Rust indicators are wrong, Python logic using them (via wrapper) will replicate the error.
    # We want INDEPENDENT verification.
    # So we use Pandas rolling for indicators in Python.
    
    py_trades = python_itr_simulation(df, window, k, atr_mult, atr_period)
    print(f"Python Trades: {len(py_trades)}")
    
    # Compare first 5 trades
    print("\n--- Rust Trades Head ---")
    for t in rust_res.trades[:3]:
        print(f"In: {t['entry_ts']}, Price: {t['entry_price']:.4f}, Out: {t['exit_ts']}, Price: {t['exit_price']:.4f}, PnL: {t['pnl']:.4f}")

    print("\n--- Python Trades Head ---")
    for t in py_trades[:3]:
        print(f"In: {t['entry_ts']}, Price: {t['entry_price']:.4f}, Out: {t['exit_ts']}, Price: {t['exit_price']:.4f}, PnL: {t['pnl']:.4f}")

if __name__ == "__main__":
    run_compare()
