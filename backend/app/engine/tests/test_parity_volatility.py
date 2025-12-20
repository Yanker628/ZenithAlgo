import sys
import logging
from datetime import datetime, timezone
import pandas as pd
from zenith.common.config.config_loader import BacktestConfig, StrategyConfig
from zenith.core.vector_backtest import run_volatility_vectorized
from zenith.core.backtest_engine import BacktestEngine
from zenith.data.loader import HistoricalDataLoader

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s [%(levelname)s] %(message)s')

def run_parity_test():
    symbol = "SOLUSDT"
    interval = "1h"
    start = datetime(2024, 1, 3, tzinfo=timezone.utc)
    end = datetime(2024, 2, 1, tzinfo=timezone.utc)
    
    # Load Data
    loader = HistoricalDataLoader(data_dir="dataset/history")
    candles = loader.load_klines_for_backtest(symbol, interval, start, end)
    df = pd.DataFrame([{
        "symbol": c.symbol, "open": c.open, "high": c.high, "low": c.low, "close": c.close,
        "volume": c.volume, "start_ts": c.start_ts, "end_ts": c.end_ts, "ts": c.end_ts
    } for c in candles])
    df["ts"] = pd.to_datetime(df["end_ts"], utc=True)
    df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)
    df = df.sort_values("end_ts").reset_index(drop=True)

    print(f"Data Loaded: {len(df)} rows")

    # Config
    params = {
        "window": 30,
        "k": 1.5,
        "atr_stop_multiplier": 2.0,
        "atr_period": 20,
        "stop_loss": 0.0, # Disable fixed SL
        "take_profit": 0.0, # Disable fixed TP
    }

    # 1. Vector Run (Rust)
    print("\n--- Vector Engine (Rust) ---")
    
    class MockCfg:
        backtest = BacktestConfig(
            symbol=symbol, interval=interval, start=str(start), end=str(end),
            strategy=StrategyConfig(type="volatility_breakout", params=params),
            data_dir="dataset/history"
        )
        strategy = backtest.strategy
    
    vec_res = run_volatility_vectorized(MockCfg(), price_df=df)
    print(f"Vector Trades: {len(vec_res.trades)}")
    print(f"Vector Sharpe: {vec_res.metrics.get('sharpe', 0):.4f}")
    
    # 2. Event Run (Python)
    print("\n--- Event Engine (Python) ---")
    
    # Creating a temp config file for BacktestEngine since it loads from file usually.
    # Or override internal config loading? 
    # BacktestEngine can take cfg_obj if modified properly, but standard init requires path.
    # Let's verify BacktestEngine.__init__ signature. 
    # It seems to take `cfg_path`.
    
    # We will write a temp config.
    import yaml
    temp_cfg_path = "config/temp_parity.yml"
    cfg_dict = {
        "symbol": symbol,
        "timeframe": interval,
        "strategy": {"type": "volatility_breakout", "params": params},
        "backtest": {
            "symbol": symbol, "interval": interval, "start": str(start), "end": str(end),
            "data_dir": "dataset/history",
            "initial_equity": 10000,
            "fees": {"maker": 0, "taker": 0, "slippage_bp": 0}, # Zero fees for parity check
            "skip_plots": True
        }
    }
    with open(temp_cfg_path, "w") as f:
        yaml.dump(cfg_dict, f)
        
    # Subclass to capture broker
    class TestEngine(BacktestEngine):
        def run(self):
            res = super().run()
            self.captured_broker = self.broker
            return res
            
    event_engine = TestEngine(cfg_path=temp_cfg_path)
    evt_res = event_engine.run()
    
    evt_trades = event_engine.captured_broker.trades if event_engine.captured_broker else []
    
    print(f"Event Trades: {len(evt_trades)}")
    evt_metrics = evt_res.summary.metrics if evt_res.summary else {}
    print(f"Event Sharpe: {getattr(evt_metrics, 'sharpe', 0):.4f}")
    
    # Compare
    print("\n--- Comparison ---")
    print("Rust Trades:")
    for t in vec_res.trades:
        print(f"  {t['entry_ts']} -> {t['exit_ts']} | PnL: {t['pnl']:.4f}")
    
    print("Python Trades:")
    for t in evt_trades:
        print(f"  Raw: {t}")
        # Trade dict keys: symbol, side, qty, entry_price, exit_price, entry_ts, exit_ts, pnl
        print(f"  {t.get('entry_ts')} -> {t.get('exit_ts')} | PnL: {t.get('pnl', 0):.4f}")
    # Relax tolerance for timestamps (Vector uses Close Time? Event uses Close Time?)
    # Vector simulation executes AT CLOSE of bar i.
    # Event engine processes bar i, generates signal?
    # Python Event Engine: on_tick(bar_i) -> appends close -> checks signal -> returns signal.
    # If signal, engine executes ON NEXT TICK? Or same tick?
    # ZenithAlgo BacktestEngine usually mimics execution:
    # If fill_at_same_bar = True/False?
    # Default BacktestSimulator usually fills at NEXT OPEN.
    # Rust Sim fills at CURRENT CLOSE (implicitly).
    # 
    # WAIT. Major discrepancy:
    # Rust Vector (`simulate_trades`): if signal at i, trade at close[i].
    # Python Event: on_tick(i) signal -> Broker receives -> fills at Open[i+1]?
    # Let's check `BacktestFillSimulator`.
    
    return vec_res, evt_trades

if __name__ == "__main__":
    run_parity_test()
