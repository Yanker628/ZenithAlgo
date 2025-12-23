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
                         inventory_q: float,
                         volatility: float = None,
                         orderbook_depth: float = 1.0) -> Tuple[float, float]:
        """
        计算最优买卖报价 (Bid, Ask) - 增强版
        
        Args:
            mid_price: 当前中间价 (s)
            inventory_q: 当前持仓偏离 (q)，以币为单位 (e.g. +1.5 ETH, -0.5 SOL)
                         如果是多头 q>0，报价会下移以促卖出
                         如果是空头 q<0，报价会上移以促买入
            volatility: 实时波动率（可选，如果不提供则使用sigma参数）
            orderbook_depth: 订单簿深度指标（默认1.0）
        
        Returns:
            (optimal_bid, optimal_ask)
        """
        gamma = self.params.gamma
        sigma = self.params.sigma
        T = self.params.terminal_time
        
        # 1. 计算保留价格 (Reservation Price)
        # r = s - q * gamma * sigma^2 * (T - t)
        # 这是AS模型的核心：根据库存调整中心报价
        reservation_price = mid_price - (inventory_q * gamma * (sigma ** 2) * T)
        
        # 2. 计算自适应价差
        if volatility is None:
            volatility = sigma
            
        half_spread = self.calculate_adaptive_spread(
            mid_price=mid_price,
            inventory_q=inventory_q,
            volatility=volatility,
            orderbook_depth=orderbook_depth
        )
        
        # 3. 计算最终报价
        # 报价围绕保留价格对称分布
        optimal_bid = reservation_price - half_spread
        optimal_ask = reservation_price + half_spread
        
        return optimal_bid, optimal_ask

    def calculate_adaptive_spread(self, 
                                  mid_price: float,
                                  inventory_q: float,
                                  volatility: float,
                                  orderbook_depth: float = 1.0) -> float:
        """
        自适应价差计算 (Adaptive Spread Calculation)
        
        综合考虑多个因素：
        1. 波动率风险：波动率越大，价差越宽
        2. 库存风险：库存偏离越大，价差越宽（降低成交频率）
        3. 订单簿深度：流动性越好，价差可以缩窄
        
        Args:
            mid_price: 中间价
            inventory_q: 库存偏离量（以币为单位）
            volatility: 实时波动率（百分比形式，如0.02表示2%）
            orderbook_depth: 订单簿深度指标（归一化，1.0为正常）
            
        Returns:
            半价差（half spread）的绝对值
        """
        # 1. 基础价差（基于波动率）
        # MEXC零手续费环境：可以使用更窄的价差
        base_spread_pct = volatility * 3  # 3倍波动率（针对零手续费优化）
        
        # 2. 库存风险调整
        # 库存偏离越大，价差越宽，降低成交频率
        inventory_ratio = abs(inventory_q) / 10.0  # 假设10个币为标准单位
        inventory_adjustment = 1.0 + (inventory_ratio * 0.2)  # 库存偏离10个币时价差增加20%
        
        # 3. 流动性调整
        # 订单簿越深，价差可以缩窄
        liquidity_adjustment = 1.0 / max(0.5, orderbook_depth)
        
        # 4. 综合调整
        adjusted_spread_pct = base_spread_pct * inventory_adjustment * liquidity_adjustment
        
        # 5. 限制价差范围（MEXC零手续费优化）
        # 最小0.005%（避免被夹击），最大0.03%（保持竞争力）
        adjusted_spread_pct = max(0.005, min(adjusted_spread_pct, 0.03))
        
        # 6. 转换为绝对价格
        half_spread = mid_price * adjusted_spread_pct / 100 / 2
        
        return half_spread
    
    def update_volatility(self, prices: list):
        """实时更新波动率参数 sigma（使用EWMA）"""
        if len(prices) < 10:
            return
            
        # 计算对数收益率
        log_rets = np.diff(np.log(prices))
        
        # 使用EWMA（指数加权移动平均）计算波动率
        # 给予近期数据更高权重
        weights = np.exp(np.linspace(-1, 0, len(log_rets)))
        weights = weights / weights.sum()
        
        current_vol = np.sqrt(np.sum(weights * log_rets**2))
        
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
