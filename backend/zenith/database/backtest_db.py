"""
PostgreSQL 数据库客户端，用于存储回测结果。
"""

import os
import json
from typing import Optional, Dict, Any
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

class BacktestDatabase:
    """PostgreSQL 数据库客户端，用于回测结果存储。"""
    
    def __init__(self, connection_string: Optional[str] = None):
        """初始化数据库连接。"""
        self.connection_string = connection_string or os.getenv(
            "DATABASE_URL",
            "postgresql://zenith:zenith_dev_2024@localhost:5432/zenithalgo"
        )
        
        # 创建引擎和连接池
        self.engine = create_engine(
            self.connection_string,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
        
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def get_session(self) -> Session:
        """获取数据库会话。"""
        return self.SessionLocal()
    
    def save_backtest(
        self,
        run_id: str,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        strategy_name: str,
        params: Dict[str, Any],
        metrics: Dict[str, float],
        equity_curve: Optional[pd.DataFrame] = None,
        trades: Optional[pd.DataFrame] = None,
        score: Optional[float] = None,
        passed: bool = True,
    ) -> int:
        """
        保存完整的回测结果到数据库。
        
        返回:
            backtest_id: 创建的回测记录ID
        """
        with self.get_session() as session:
            # 插入回测记录
            insert_query = text("""
                INSERT INTO backtests (
                    run_id, symbol, timeframe, start_date, end_date,
                    strategy_name, params,
                    total_return, sharpe_ratio, max_drawdown, win_rate, total_trades,
                    score, passed
                ) VALUES (
                    :run_id, :symbol, :timeframe, :start_date, :end_date,
                    :strategy_name, :params,
                    :total_return, :sharpe_ratio, :max_drawdown, :win_rate, :total_trades,
                    :score, :passed
                )
                ON CONFLICT (run_id) DO UPDATE SET
                    total_return = EXCLUDED.total_return,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    max_drawdown = EXCLUDED.max_drawdown,
                    score = EXCLUDED.score
                RETURNING id
            """)
            
            result = session.execute(insert_query, {
                'run_id': run_id,
                'symbol': symbol,
                'timeframe': timeframe,
                'start_date': start_date,
                'end_date': end_date,
                'strategy_name': strategy_name,
                'params': json.dumps(params),
                'total_return': metrics.get('total_return'),
                'sharpe_ratio': metrics.get('sharpe'),
                'max_drawdown': metrics.get('max_drawdown'),
                'win_rate': metrics.get('win_rate'),
                'total_trades': metrics.get('total_trades'),
                'score': score or metrics.get('score', 0.0),
                'passed': passed,
            })
            
            backtest_id = result.fetchone()[0]
            
            # 保存 equity curve
            if equity_curve is not None and not equity_curve.empty:
                equity_records = []
                for _, row in equity_curve.iterrows():
                    equity_records.append({
                        'backtest_id': backtest_id,
                        'timestamp': row.get('timestamp') or row.get('ts'),
                        'equity': float(row['equity']),
                        'drawdown': float(row.get('drawdown', 0.0)),
                        'drawdown_pct': float(row.get('drawdown_pct', 0.0)),
                    })
                
                if equity_records:
                    equity_insert = text("""
                        INSERT INTO equity_curves (backtest_id, timestamp, equity, drawdown, drawdown_pct)
                        VALUES (:backtest_id, :timestamp, :equity, :drawdown, :drawdown_pct)
                        ON CONFLICT (backtest_id, timestamp) DO NOTHING
                    """)
                    session.execute(equity_insert, equity_records)
            
            # 保存 trades
            if trades is not None and not trades.empty:
                trade_records = []
                cumulative = 0.0
                
                for _, row in trades.iterrows():
                    # Map CSV columns to database columns
                    # CSV: fee -> commission, realized_delta -> pnl
                    pnl_value = row.get('realized_delta') or row.get('pnl')
                    commission_value = row.get('fee') or row.get('commission')
                    
                    # Calculate cumulative PnL
                    if pnl_value is not None and pd.notna(pnl_value):
                        cumulative += float(pnl_value)
                    
                    trade_records.append({
                        'backtest_id': backtest_id,
                        'timestamp': row.get('timestamp') or row.get('ts'),
                        'symbol': row.get('symbol', symbol),
                        'side': row['side'],
                        'price': float(row['price']),
                        'qty': float(row['qty']),
                        'pnl': float(pnl_value) if pnl_value is not None and pd.notna(pnl_value) else None,
                        'commission': float(commission_value) if commission_value is not None and pd.notna(commission_value) else None,
                        'cumulative_pnl': cumulative if pnl_value is not None and pd.notna(pnl_value) else None,
                    })
                
                if trade_records:
                    trade_insert = text("""
                        INSERT INTO trades (backtest_id, timestamp, symbol, side, price, qty, pnl, commission, cumulative_pnl)
                        VALUES (:backtest_id, :timestamp, :symbol, :side, :price, :qty, :pnl, :commission, :cumulative_pnl)
                    """)
                    session.execute(trade_insert, trade_records)
            
            session.commit()
            
            return backtest_id
    
    def close(self):
        """关闭数据库连接。"""
        self.engine.dispose()
