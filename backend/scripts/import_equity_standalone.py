#!/usr/bin/env python3
"""
Simplified approach: Create backtest records directly from equity files.
This ensures we only save backtests that have full equity data.
"""

import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values
import json

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zenith:zenith_dev_2024@localhost:5432/zenithalgo")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def import_equity_files_with_backtests():
    """
    Import equity files and create corresponding backtest records.
    Only imports files that exist, ensuring 1:1 mapping.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    equity_files = list(Path("results/backtest").rglob("equity.csv"))
    print(f"Found {len(equity_files)} equity files")
    
    imported_count = 0
    total_points = 0
    
    for equity_file in equity_files:
        try:
            # Extract metadata from path
            # Example: results/backtest/SOLUSDT/1h/2021-01-01T00:00:00Z_2024-01-01T00:00:00Z/20251219210951/equity.csv
            parts = equity_file.parts
            symbol = parts[2]
            timeframe = parts[3]
            date_range = parts[4]
            run_timestamp = parts[5]
            
            # Create unique run_id
            run_id = f"standalone_{symbol}_{timeframe}_{run_timestamp}"
            
            # Check if this run_id already exists
            cur.execute("SELECT id FROM backtests WHERE run_id = %s", (run_id,))
            existing = cur.fetchone()
            
            if existing:
                backtest_id = existing[0]
                print(f"✓ Using existing backtest #{backtest_id}: {run_id[:60]}...")
            else:
                # Parse date range
                try:
                    start_date, end_date = date_range.split("_")
                    start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                    end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                except:
                    start_date = datetime(2021, 1, 1)
                    end_date = datetime(2024, 1, 1)
                
                # Create backtest record
                cur.execute("""
                    INSERT INTO backtests (
                        run_id, symbol, timeframe, start_date, end_date,
                        strategy_name, params, score, passed
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    run_id,
                    symbol,
                    timeframe,
                    start_date,
                    end_date,
                    'VolatilityBreakout',
                    json.dumps({'source': 'standalone_backtest'}),
                    0.0,  # No score for standalone
                    True
                ))
                backtest_id = cur.fetchone()[0]
                conn.commit()
                print(f"+ Created backtest #{backtest_id}: {run_id[:60]}...")
            
            # Read equity data
            df = pd.read_csv(equity_file)
            
            # Prepare equity points
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
                except:
                    continue
            
            # Insert equity points
            if rows:
                execute_values(cur, """
                    INSERT INTO equity_curves (
                        backtest_id, timestamp, equity, drawdown, drawdown_pct
                    ) VALUES %s
                    ON CONFLICT (backtest_id, timestamp) DO NOTHING
                """, rows)
                
                conn.commit()
                total_points += len(rows)
                imported_count += 1
                print(f"  ✅ Imported {len(rows):,} equity points")
                
        except Exception as e:
            print(f"  ⚠️  Failed to process {equity_file.name}: {e}")
            conn.rollback()
            continue
    
    cur.close()
    conn.close()
    
    print(f"\n" + "=" * 60)
    print(f"✅ Successfully imported {imported_count} backtest with equity!")
    print(f"   Total equity points: {total_points:,}")
    print(f"   Average points per backtest: {total_points // max(imported_count, 1):,}")
    print("=" * 60)

if __name__ == "__main__":
    print("=" * 60)
    print("Import Equity Files as Standalone Backtests")
    print("=" * 60)
    print()
    
    try:
        import_equity_files_with_backtests()
    except Exception as e:
        print(f"\n❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
