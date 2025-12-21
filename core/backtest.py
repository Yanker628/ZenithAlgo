import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class BacktestResult:
    metrics: Dict[str, float]
    equity_curve: pd.Series
    benchmark_equity: pd.Series  # 新增: 买入持仓基准权益
    trades: pd.DataFrame
    signals: pd.DataFrame

class VectorBacktester:
    def __init__(self, data: pd.DataFrame, initial_capital: float = 10000.0, commission: float = 0.0005):
        """
        初始化向量化回测器
        :param data: 包含 ['open', 'high', 'low', 'close', 'volume'] 列且为 datetime索引的 DataFrame
        :param initial_capital: 初始资金，默认 10000.0
        :param commission: 手续费率，默认 0.0005 (0.05%)
        """
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.commission = commission

    def run(self, strategy_func, **params) -> BacktestResult:
        """
        运行回测
        :param strategy_func: 策略函数，接收 (df, **params) 并返回一个信号 Series (1: 做多/买入, -1: 做空/卖出, 0: 空仓/持有)
        """
        # 1. 计算信号 (Calculate Signals)
        signals = strategy_func(self.data, **params)
        
        # 为了避免未来函数偏差 (lookahead bias)，将信号后移一期
        self.data['log_ret'] = np.log(self.data['close'] / self.data['close'].shift(1))
        
        # --- 计算基准 (Benchmark) ---
        # 买入并持有 (Buy & Hold) 的累计收益
        self.data['benchmark_cum_ret'] = self.data['log_ret'].cumsum()
        self.data['benchmark_equity'] = self.initial_capital * np.exp(self.data['benchmark_cum_ret'])

        # --- 计算策略 (Strategy) ---
        # Position 表示在这根 K 线 **结束时** 我们持有的仓位。
        self.data['position'] = signals.shift(1).fillna(0)
        
        # 策略收益 = 上一期仓位 * 本期收益率
        self.data['strategy_ret'] = self.data['position'] * self.data['log_ret']
        
        # 计算手续费 (简化近似：只要仓位发生变化就扣除手续费)
        trades = self.data['position'].diff().fillna(0).abs()
        self.data['strategy_ret'] -= trades * self.commission
        
        # 计算权益曲线 (Equity Curve)
        self.data['cumulative_ret'] = self.data['strategy_ret'].cumsum()
        self.data['equity'] = self.initial_capital * np.exp(self.data['cumulative_ret'])
        
        # 计算指标 (Metrics)
        metrics = self._calculate_metrics(self.data['strategy_ret'])
        
        # 提取交易列表 (简化版)
        trade_logs = self._extract_trades(self.data['position'])

        return BacktestResult(
            metrics=metrics,
            equity_curve=self.data['equity'],
            benchmark_equity=self.data['benchmark_equity'],
            trades=trade_logs,
            signals=signals
        )

    def _calculate_metrics(self, returns: pd.Series) -> Dict[str, float]:
        if len(returns) < 2:
            return {}
        
        days = (self.data.index[-1] - self.data.index[0]).days
        if days == 0: days = 1
        
        # 年化收益率 (Approx CAGR)
        total_ret = np.exp(returns.sum()) - 1
        cagr = (1 + total_ret) ** (365 / days) - 1
        
        # 夏普比率 (Sharpe Ratio) - 假设加密货币 365 天交易
        # 更严谨的做法是将数据重采样到日线，但这里使用每根K线的统计特征进行年化
        sharpe = 0
        std = returns.std()
        if std > 0:
            # 简单的年化夏普比率，假设默认是小时线 (24*365)
            # 如果是4小时线则是 (6*365)，这里粗略按小时线估算，仅供参考
            sharpe = returns.mean() / std * np.sqrt(365 * 24) 
            
        # 最大回撤 (Max Drawdown)
        cum_ret = returns.cumsum()
        peak = cum_ret.cummax()
        drawdown = cum_ret - peak
        max_drawdown = np.exp(drawdown.min()) - 1 # 将对数收益率转回百分比
        
        return {
            "Total Return": total_ret,
            "CAGR": cagr,
            "Sharpe": sharpe,
            "Max Drawdown": max_drawdown
        }

    def _extract_trades(self, position: pd.Series) -> pd.DataFrame:
        """
        从仓位变化中提取具体的交易记录
        """
        trades = []
        # 找出仓位发生变化的时间点
        # diff != 0 意味着仓位变了 (0->1 买入, 1->0 卖出, 1->-1 反手)
        diff = position.diff().fillna(0)
        trade_indices = diff[diff != 0].index
        
        entry_price = 0.0
        entry_time = None
        
        for ts in trade_indices:
            change = diff.loc[ts]
            current_price = self.data.loc[ts, 'close']
            
            # change > 0: 买入 (可能是开多，也可能是平空)
            # 这里简化处理：假设只有做多逻辑 (0 -> 1) 和 平仓 (1 -> 0)
            
            if change > 0: # 买入/开仓
                entry_price = current_price
                entry_time = ts
                
            elif change < 0: # 卖出/平仓
                if entry_time is not None:
                    # 只有之前有开仓才能平仓
                    pnl = (current_price - entry_price) / entry_price
                    # 扣除双边手续费 (简单的估算)
                    pnl -= self.commission * 2
                    
                    trades.append({
                        "Entry Time": entry_time,
                        "Entry Price": entry_price,
                        "Exit Time": ts,
                        "Exit Price": current_price,
                        "PnL": pnl,
                        "PnL %": round(pnl * 100, 2)
                    })
                    entry_time = None # 重置
        
        if not trades:
            return pd.DataFrame()
            
        return pd.DataFrame(trades)
