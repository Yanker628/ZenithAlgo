#!/usr/bin/env python3
"""
Migrate CSV backtest results to PostgreSQL database.
Reads all CSV files from results/ directory and imports them.
"""

import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values
import json

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zenith:zenith_dev_2024@localhost:5432/zenithalgo")

def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(DATABASE_URL)

def migrate_sweep_results():
    """Migrate sweep.csv files to backtests table"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    sweep_files = list(Path("results/sweep").rglob("sweep.csv"))
    print(f"Found {len(sweep_files)} sweep files to migrate")
    
    total_rows = 0
    
    for sweep_file in sweep_files:
        print(f"\nProcessing: {sweep_file}")
        
        # Extract metadata from path
        parts = sweep_file.parts
        symbol = parts[2] if len(parts) > 2 else "UNKNOWN"
        timeframe = parts[3] if len(parts) > 3 else "UNKNOWN"
        date_range = parts[4] if len(parts) > 4 else "UNKNOWN"
        run_id_base = parts[5] if len(parts) > 5 else datetime.now().strftime("%Y%m%d%H%M%S")
        
        # Parse dates from date_range
        try:
            start_date, end_date = date_range.split("_")
            start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except:
            start_date = datetime(2021, 1, 1)
            end_date = datetime(2024, 1, 1)
        
        # Read CSV
        df = pd.read_csv(sweep_file)
        
        # Prepare data for insertion
        rows = []
        for idx, row in df.iterrows():
            run_id = f"{symbol}_{timeframe}_{run_id_base}_{idx}"
            
            params = {
                'window': int(row.get('window', 0)),
                'k': float(row.get('k', 0)),
                'atr_stop_multiplier': float(row.get('atr_stop_multiplier', 0)),
                'atr_period': int(row.get('atr_period', 0)) if 'atr_period' in row else None,
                'stop_loss': float(row.get('stop_loss', 0)) if 'stop_loss' in row else None,
                'take_profit': float(row.get('take_profit', 0)) if 'take_profit' in row else None,
            }
            
            rows.append((
                run_id,
                symbol,
                timeframe,
                start_date,
                end_date,
                'VolatilityBreakout',
                json.dumps(params),
                float(row.get('total_return', 0)),
                float(row.get('sharpe', 0)),
                float(row.get('max_drawdown', 0)),
                float(row.get('win_rate', 0)),
                int(row.get('total_trades', 0)),
                float(row.get('avg_win', 0)) if 'avg_win' in row else None,
                float(row.get('avg_loss', 0)) if 'avg_loss' in row else None,
                float(row.get('profit_factor', 0)) if 'profit_factor' in row else None,
                float(row.get('expectancy', 0)) if 'expectancy' in row else None,
                float(row.get('avg_trade_return', 0)) if 'avg_trade_return' in row else None,
                float(row.get('std_trade_return', 0)) if 'std_trade_return' in row else None,
                float(row.get('exposure', 0)) if 'exposure' in row else None,
                float(row.get('turnover', 0)) if 'turnover' in row else None,
                float(row.get('score', 0)),
                bool(row.get('passed', True)),
                str(row.get('filter_reason', '')) if pd.notna(row.get('filter_reason')) else None,
            ))
        
        # Batch insert
        if rows:
            execute_values(cur, """
                INSERT INTO backtests (
                    run_id, symbol, timeframe, start_date, end_date,
                    strategy_name, params,
                    total_return, sharpe_ratio, max_drawdown, win_rate, total_trades,
                    avg_win, avg_loss, profit_factor, expectancy,
                    avg_trade_return, std_trade_return, exposure, turnover,
                    score, passed, filter_reason
                ) VALUES %s
                ON CONFLICT (run_id) DO NOTHING
            """, rows)
            
            conn.commit()
            total_rows += len(rows)
            print(f"  Inserted {len(rows)} records")
    
    cur.close()
    conn.close()
    print(f"\n✅ Migration complete! Total records: {total_rows}")

def migrate_equity_curves():
    """Migrate equity.csv files to equity_curves table"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    equity_files = list(Path("results/backtest").rglob("equity.csv"))
    print(f"\nFound {len(equity_files)} equity files to migrate")
    
    for equity_file in equity_files:
        print(f"\nProcessing: {equity_file}")
        
        # Extract metadata
        parts = equity_file.parts
        symbol = parts[2] if len(parts) > 2 else "UNKNOWN"
        timeframe = parts[3] if len(parts) > 3 else "UNKNOWN"
        run_id_part = parts[5] if len(parts) > 5 else "UNKNOWN"
        
        # Find matching backtest_id
        cur.execute("""
            SELECT id FROM backtests 
            WHERE symbol = %s AND timeframe = %s AND run_id LIKE %s
            LIMIT 1
        """, (symbol, timeframe, f"%{run_id_part}%"))
        
        result = cur.fetchone()
        if not result:
            print(f"  ⚠️  No matching backtest found, skipping")
            continue
        
        backtest_id = result[0]
        
        # Read equity CSV
        df = pd.read_csv(equity_file)
        
        # Prepare data
        rows = []
        for _, row in df.iterrows():
            try:
                timestamp = pd.to_datetime(row['ts'])
                rows.append((
                    backtest_id,
                    timestamp,
                    float(row['equity']),
                    float(row.get('drawdown', 0)),
                    float(row.get('drawdown_pct', 0))
                ))
            except Exception as e:
                print(f"  ⚠️  Skipping row: {e}")
                continue
        
        # Batch insert
        if rows:
            execute_values(cur, """
                INSERT INTO equity_curves (
                    backtest_id, timestamp, equity, drawdown, drawdown_pct
                ) VALUES %s
                ON CONFLICT (backtest_id, timestamp) DO NOTHING
            """, rows)
            
            conn.commit()
            print(f"  ✅ Inserted {len(rows)} equity points")
    
    cur.close()
    conn.close()
    print(f"\n✅ Equity migration complete!")

if __name__ == "__main__":
    print("=" * 60)
    print("ZenithAlgo CSV to PostgreSQL Migration")
    print("=" * 60)
    
    try:
        print("\n📊 Phase 1: Migrating sweep results...")
        migrate_sweep_results()
        
        print("\n📈 Phase 2: Migrating equity curves...")
        migrate_equity_curves()
        
        print("\n" + "=" * 60)
        print("✅ ALL MIGRATIONS COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
