"""
创建测试交易数据并导入到 PostgreSQL
"""

import sys
from datetime import datetime, timedelta
import random
from zenith.database.db_helpers import BacktestDatabase

def create_sample_trades():
    """创建示例交易数据"""
    db = BacktestDatabase()
    
    # 获取一个有 equity curve 的 backtest
    try:
        with db.get_session() as session:
            from sqlalchemy import text
            result = session.execute(text("""
                SELECT b.id, b.symbol, b.start_date, b.end_date
                FROM backtests b
                JOIN equity_curves ec ON b.id = ec.backtest_id
                GROUP BY b.id
                LIMIT 1
            """))
            
            backtest = result.fetchone()
            if not backtest:
                print("❌ No backtest with equity curve found")
                return
            
            backtest_id, symbol, start_date, end_date = backtest
            print(f"✓ Found backtest #{backtest_id}: {symbol}")
            
            # 生成模拟交易
            trades = []
            current_date = start_date
            equity = 10000
            cumulative_pnl = 0
            
            num_trades = random.randint(50, 100)
            days_between_trades = (end_date - start_date).days // num_trades
            
            for i in range(num_trades):
                # 交易时间
                current_date += timedelta(days=days_between_trades + random.randint(0, 3))
                
                # 买入
                side = "BUY" if i % 2 == 0 else "SELL"
                price = 100 + random.uniform(-10, 50)
                qty = random.uniform(0.1, 2.0)
                commission = qty * price * 0.001  # 0.1% 手续费
                
                # 如果是卖出，计算盈亏
                pnl = None
                if side == "SELL" and i > 0:
                    pnl = random.uniform(-50, 150)
                    cumulative_pnl += pnl
                
                trades.append({
                    'backtest_id': backtest_id,
                    'timestamp': current_date,
                    'symbol': symbol,
                    'side': side,
                    'price': price,
                    'qty': qty,
                    'pnl': pnl,
                    'commission': commission,
                    'cumulative_pnl': cumulative_pnl if pnl else None,
                })
            
            # 插入数据库
            insert_query = text("""
                INSERT INTO trades (
                    backtest_id, timestamp, symbol, side,
                    price, qty, pnl, commission, cumulative_pnl
                ) VALUES (
                    :backtest_id, :timestamp, :symbol, :side,
                    :price, :qty, :pnl, :commission, :cumulative_pnl
                )
            """)
            
            for trade in trades:
                session.execute(insert_query, trade)
            
            session.commit()
            
            print(f"✅ Created {len(trades)} sample trades for backtest #{backtest_id}")
            print(f"   Symbol: {symbol}")
            print(f"   Cumulative PnL: ${cumulative_pnl:.2f}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Creating Sample Trades Data")
    print("=" * 60)
    create_sample_trades()
