import math
import numpy as np
from dataclasses import dataclass
from typing import Tuple

@dataclass
class ASParams:
    gamma: float = 0.5      # 风险厌恶系数 (0.1 ~ 1.0)
    sigma: float = 0.2      # 市场波动率 (年化 -> 秒级需转换)
    k: float = 1.5          # 订单簿流动性参数 (Order Arrival Intensity)
    terminal_time: float = 1.0 # T-t (通常设为 1，表示归一化的时间单位)

class AvellanedaStoikovModel:
    """
    Avellaneda-Stoikov 定价模型 (High-Frequency Trading)
    
    论文: "High-frequency trading in a limit order book" (2008)
    
    核心公式:
    1. 保留价格 r(s, q) = s - q * gamma * sigma^2 * (T-t)
    2. 最优价差 delta = (2/gamma) * ln(1 + gamma/k)
    """
    
    def __init__(self, params: ASParams):
        self.params = params
        
    def calculate_quotes(self, 
                         mid_price: float, 
                         inventory_q: float) -> Tuple[float, float]:
        """
        计算最优买卖报价 (Bid, Ask)
        
        Args:
            mid_price: 当前中间价 (s)
            inventory_q: 当前持仓偏离 (q)，以币为单位 (e.g. +1.5 ETH, -0.5 SOL)
                         如果是多头 q>0，报价会下移以促卖出
                         如果是空头 q<0，报价会上移以促买入
        
        Returns:
            (optimal_bid, optimal_ask)
        """
        gamma = self.params.gamma
        sigma = self.params.sigma
        T = self.params.terminal_time
        k = self.params.k
        
        # 1. 计算保留价格 (Reservation Price)
        # r = s - q * gamma * sigma^2 * (T - t)
        reservation_price = mid_price - (inventory_q * gamma * (sigma ** 2) * T)
        
        # 2. 计算最优价差 (Optimal Spread)
        # delta = (2/gamma) * ln(1 + gamma/k)
        # 注意：这里计算的是"半价差" (Half Spread) 还是 "全价差"?
        # 原论文公式得出的 delta 是 spread around reservation price
        # Bid = r - delta/2
        # Ask = r + delta/2
        
        
        # 原始 AS 公式对小价格币种产生极大价差，改用百分比方法
        # spread = (2 / gamma) * math.log(1 + gamma / k)  # 弃用
        
        # 使用固定百分比价差（0.02% 目标，根据 MEXC 真实数据优化）
        # MEXC 实测：BTC 0.001%, ETH 0.015%, SOL 0.016%
        # 我们设置为 0.02%（略宽于 MEXC，保留盈利空间）
        spread_pct = sigma * 50  # sigma=0.0004 -> 0.02%
        spread_pct = max(0.01, min(spread_pct, 0.5))  # 限制范围 0.01% - 0.5%
        half_spread = mid_price * spread_pct / 100 / 2
        
        # 结合波动率动态调整价差 (Vol-adjusted Spread)
        # 波动率越大，价差应该越宽
        # 这里的简单实现假设 sigma 已经包含在 risk term 中，但 standard AS spread 
        # 其实对 volatility 不敏感，实战中通常会加上 sigma 项
        
        # 3. 计算最终报价
        optimal_bid = reservation_price - half_spread
        optimal_ask = reservation_price + half_spread
        
        return optimal_bid, optimal_ask

    def update_volatility(self, prices: list):
        """实时更新波动率参数 sigma"""
        if len(prices) < 10:
            return
            
        # 计算对数收益率
        log_rets = np.diff(np.log(prices))
        
        # 计算标准差 (秒级)
        current_vol = np.std(log_rets)
        
        # 平滑更新 (EMA)
        self.params.sigma = 0.9 * self.params.sigma + 0.1 * current_vol


# ===== 测试代码 =====
if __name__ == "__main__":
    params = ASParams(gamma=0.5, sigma=2.0, k=1.5)
    model = AvellanedaStoikovModel(params)
    
    mid = 100.0
    
    print(f"基准价格 (s): ${mid}")
    print(f"{'库存(q)':^10} | {'Bid':^10} | {'Ask':^10} | {'Skew':^10}")
    print("-" * 50)
    
    for q in [10, 5, 0, -5, -10]:
        bid, ask = model.calculate_quotes(mid, q)
        skew = (bid + ask) / 2 - mid
        print(f"{q:^10.1f} | {bid:^10.2f} | {ask:^10.2f} | {skew:^10.2f}")
        
    print("\n结论:")
    print("1. 库存 > 0 (多头): 报价下移，试图卖出")
    print("2. 库存 < 0 (空头): 报价上移，试图买入")
