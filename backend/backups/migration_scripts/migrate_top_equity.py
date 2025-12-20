#!/usr/bin/env python3
"""
Migrate ONLY Top-N backtest equity curves to PostgreSQL.
Optimized for minimal storage while ensuring best results have full data.
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

# Configuration
TOP_N_WITH_EQUITY = 10  # Only save equity for top 10 results

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def migrate_top_equity_curves():
    """
    Migrate equity curves ONLY for Top N backtests by score.
    This minimizes storage while ensuring best results have full data.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get Top N backtest IDs
    cur.execute(f"""
        SELECT id, run_id, symbol FROM backtests 
        ORDER BY score DESC 
        LIMIT {TOP_N_WITH_EQUITY}
    """)
    
    top_backtests = cur.fetchall()
    print(f"📊 Targeting Top {TOP_N_WITH_EQUITY} backtests for equity migration")
    print(f"Top backtests: {[f'{b[2]} ({b[1]})' for b in top_backtests[:5]]}")
    
    # Map backtest ID to equity file
    backtest_to_equity = {}
    
    equity_files = list(Path("results/backtest").rglob("equity.csv"))
    print(f"\nFound {len(equity_files)} equity files total")
    
    # Try to map equity files to top backtests
    for backtest_id, run_id, symbol in top_backtests:
        # Extract run_id parts
        parts = run_id.split('_')
        if len(parts) >= 3:
            symbol_part = parts[0]
            timeframe_part = parts[1]
            timestamp_part = parts[2]
            
            # Find matching equity file
            for equity_file in equity_files:
                file_parts = equity_file.parts
                
                # Check if file matches this backtest
                if (len(file_parts) > 5 and 
                    file_parts[2] == symbol_part and 
                    file_parts[3] == timeframe_part and
                    timestamp_part in str(equity_file)):
                    
                    backtest_to_equity[backtest_id] = equity_file
                    print(f"✓ Matched {run_id[:50]}... → {equity_file.name}")
                    break
    
    print(f"\n📈 Successfully matched {len(backtest_to_equity)}/{TOP_N_WITH_EQUITY} top backtests to equity files")
    
    # Migrate matched equity curves
    total_points = 0
    for backtest_id, equity_file in backtest_to_equity.items():
        df = pd.read_csv(equity_file)
        
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
                continue
        
        if rows:
            execute_values(cur, """
                INSERT INTO equity_curves (
                    backtest_id, timestamp, equity, drawdown, drawdown_pct
                ) VALUES %s
                ON CONFLICT (backtest_id, timestamp) DO NOTHING
            """, rows)
            
            conn.commit()
            total_points += len(rows)
            print(f"  ✅ Inserted {len(rows)} points for backtest #{backtest_id}")
    
    cur.close()
    conn.close()
    
    print(f"\n✅ Migration complete!")
    print(f"   Total equity points: {total_points:,}")
    print(f"   Storage: ~{total_points * 50 / 1024 / 1024:.1f} MB")
    return len(backtest_to_equity)

if __name__ == "__main__":
    print("=" * 60)
    print("ZenithAlgo Top-N Equity Migration (Optimized)")
    print("=" * 60)
    
    try:
        matched = migrate_top_equity_curves()
        
        print("\n" + "=" * 60)
        print(f"✅ SUCCESS! {matched}/{TOP_N_WITH_EQUITY} top results have equity curves")
        print("=" * 60)
        print("\n💡 Note: Other results only have summary metrics")
        print("   This saves significant storage space!")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
