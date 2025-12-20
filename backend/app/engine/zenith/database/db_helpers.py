"""Helper utilities for saving experiment results to PostgreSQL database."""

import os
import pandas as pd
from pathlib import Path
from datetime import datetime
from zenith.database import BacktestDatabase

def save_sweep_results_to_db(
    sweep_csv_path: str,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    strategy_name: str = "VolatilityBreakout",
    verbose: bool = True
):
    """
    Read sweep.csv and save all results to PostgreSQL.
    
    Only saves backtest summary metrics (no equity or trades).
    This minimizes storage while keeping all parameter combinations searchable.
    """
    if not Path(sweep_csv_path).exists():
        print(f"⚠️  Sweep CSV not found: {sweep_csv_path}")
        return 0
    
    # Read CSV
    df = pd.read_csv(sweep_csv_path)
    
    if df.empty:
        print("⚠️  Sweep CSV is empty")
        return 0
    
    # Initialize database
    try:
        db = BacktestDatabase()
    except Exception as e:
        print(f"⚠️  Database connection failed: {e}")
        print("   Results saved to CSV only (database skipped)")
        return 0
    
    saved_count = 0
    run_ts = Path(sweep_csv_path).parent.name  # Extract timestamp from path
    
    for idx, row in df.iterrows():
        try:
            # Extract run ID from file path structure
            # Example: results/sweep/SOLUSDT/1h/2021-01-01_2024-01-01/20251219205516/SOLUSDT/sweep.csv
            run_id = f"{symbol}_{timeframe}_{run_ts}_{idx}"
            
            # Build params dict
            params = {}
            for col in df.columns:
                if col not in ['total_return', 'sharpe', 'max_drawdown', 'win_rate', 
                               'total_trades', 'score', 'passed', 'filter_reason',
                               'avg_win', 'avg_loss', 'profit_factor', 'expectancy',
                               'avg_trade_return', 'std_trade_return', 'exposure', 'turnover']:
                    params[col] = row[col] if pd.notna(row[col]) else None
            
            # Build metrics dict
            metrics = {
                'total_return': row.get('total_return'),
                'sharpe': row.get('sharpe'),
                'max_drawdown': row.get('max_drawdown'),
                'win_rate': row.get('win_rate'),
                'total_trades': int(row['total_trades']) if pd.notna(row.get('total_trades')) else 0,
                'avg_win': row.get('avg_win'),
                'avg_loss': row.get('avg_loss'),
                'profit_factor': row.get('profit_factor'),
                'expectancy': row.get('expectancy'),
                'avg_trade_return': row.get('avg_trade_return'),
                'std_trade_return': row.get('std_trade_return'),
                'exposure': row.get('exposure'),
                'turnover': row.get('turnover'),
                'score': row.get('score', 0.0),
            }
            
            # Save to database (no equity/trades for sweep results)
            db.save_backtest(
                run_id=run_id,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                strategy_name=strategy_name,
                params=params,
                metrics=metrics,
                equity_curve=None,  # Don't save equity for sweep (storage optimization)
                trades=None,         # Don't save trades for sweep
                score=metrics['score'],
                passed=bool(row.get('passed', True)),
            )
            
            saved_count += 1
            
        except Exception as e:
            if verbose:
                print(f"⚠️  Failed to save row {idx}: {e}")
            continue
    
    db.close()
    
    if verbose:
        print(f"✅ Saved {saved_count}/{len(df)} sweep results to PostgreSQL")
    
    return saved_count
