import numpy as np
import zenithalgo_rust
import pandas as pd

def test_rust():
    print("Testing Rust simulate_trades...")
    n = 100
    timestamps = np.arange(n, dtype=np.int64) * 1000 # seconds
    # Up trend
    closes = np.linspace(100, 200, n)
    opens = closes - 0.5
    highs = closes + 1.0
    lows = closes - 1.0
    
    signals = np.zeros(n, dtype=np.int32)
    # Buy at 10
    signals[10] = 1 
    # Sell at 90
    signals[90] = -1
    
    sl_pct = 0.05
    tp_pct = 0.10
    
    print(f"Signals: {signals[10]}, {signals[90]}")
    
    try:
        equity, trades = zenithalgo_rust.simulate_trades(
            timestamps.tolist(),
            opens.tolist(),
            highs.tolist(),
            lows.tolist(),
            closes.tolist(),
            signals.tolist(),
            sl_pct,
            tp_pct
        )
        print(f"Equity len: {len(equity)}")
        print(f"Trades len: {len(trades)}")
        print(f"Trades: {trades}")
        if len(trades) > 0:
            print("SUCCESS: Trades generated")
        else:
            print("FAILURE: No trades")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_rust()
