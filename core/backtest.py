import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class BacktestResult:
    metrics: Dict[str, float]
    equity_curve: pd.Series
    trades: pd.DataFrame
    signals: pd.DataFrame

class VectorBacktester:
    def __init__(self, data: pd.DataFrame, initial_capital: float = 10000.0, commission: float = 0.0005):
        """
        :param data: DataFrame with columns ['open', 'high', 'low', 'close', 'volume'] and datetime index
        """
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.commission = commission

    def run(self, strategy_func, **params) -> BacktestResult:
        """
        Run the backtest.
        :param strategy_func: Function that takes (df, **params) and returns a Series of signals (1: Buy, -1: Sell, 0: Neutral/Hold)
        """
        # 1. Calculate Signals
        signals = strategy_func(self.data, **params)
        
        # Ensure signals are shifted by 1 to avoid lookahead bias (signal at close of T executes at open of T+1)
        # Note: Vectorized backtests often assume execution at Close of same bar or Open of next. 
        # For simplicity here, we assume execution at Close of the signal bar (Signal generated slightly before close), 
        # OR shift it. Let's assume signal is decided at close, executed at NEXT Open for realism.
        
        # Simple Vector approaches often use Close-to-Close returns.
        # Let's align execution to simple 'position' logic:
        # Position = Signal held.
        
        self.data['log_ret'] = np.log(self.data['close'] / self.data['close'].shift(1))
        
        # Position indicates what we hold at the END of the bar.
        # If signal is generated using data up to T, we can enter at T's close (simplified) or T+1 Open.
        # Let's assume entry at Close for simplicity in vectorization without separate Open price column handling if only Close is used.
        # However, to be safe against lookahead, we usually shift position by 1.
        
        self.data['position'] = signals.shift(1).fillna(0)
        
        # Strategy Returns = Position(T-1) * Returns(T)
        self.data['strategy_ret'] = self.data['position'] * self.data['log_ret']
        
        # Apply commission (simplified approximation: whenever pos changes)
        trades = self.data['position'].diff().fillna(0).abs()
        self.data['strategy_ret'] -= trades * self.commission
        
        # Equity Curve
        self.data['cumulative_ret'] = self.data['strategy_ret'].cumsum()
        self.data['equity'] = self.initial_capital * np.exp(self.data['cumulative_ret'])
        
        # Metrics
        metrics = self._calculate_metrics(self.data['strategy_ret'])
        
        # Extract Trades List (simplified)
        trade_logs = self._extract_trades(self.data['position'])

        return BacktestResult(
            metrics=metrics,
            equity_curve=self.data['equity'],
            trades=trade_logs,
            signals=signals
        )

    def _calculate_metrics(self, returns: pd.Series) -> Dict[str, float]:
        if len(returns) < 2:
            return {}
        
        days = (self.data.index[-1] - self.data.index[0]).days
        if days == 0: days = 1
        
        # Annualized Return (Approx)
        total_ret = np.exp(returns.sum()) - 1
        cagr = (1 + total_ret) ** (365 / days) - 1
        
        # Sharpe (Daily) - assuming crypto 365 days
        # Resample to daily if data is intraday is better, but here we use bar-based approx
        sharpe = 0
        std = returns.std()
        if std > 0:
            # Simple annualized sharpe assuming e.g. 4h bars (6 bars/day * 365) or 1h (24*365)
            # We'll just print consistency for now or use per-bar
            sharpe = returns.mean() / std * np.sqrt(365 * 24) # Assuming hourly default roughly
            
        # Drawdown
        cum_ret = returns.cumsum()
        peak = cum_ret.cummax()
        drawdown = cum_ret - peak
        max_drawdown = np.exp(drawdown.min()) - 1 # convert log ret back to pct
        
        return {
            "Total Return": total_ret,
            "CAGR": cagr,
            "Sharpe": sharpe,
            "Max Drawdown": max_drawdown
        }

    def _extract_trades(self, position: pd.Series) -> pd.DataFrame:
        # A very basic trade extractor from position vector
        # Returns a dataframe of entries and exits
        # TODO: Implement full trade list for visualization
        return pd.DataFrame()
