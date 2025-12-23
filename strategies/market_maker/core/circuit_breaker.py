import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """
    熔断器 (Circuit Breaker)
    
    负责监控系统状态，并在检测到异常时截停交易
    """
    
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.last_heartbeat = time.time()
        self.last_trigger_reason = ""
        
        # 阈值配置
        self.max_drawdown_pct = 2.0  # 最大回撤 2%
        self.max_price_deviation_pct = 1.0  # 最大价格偏差 1%
        self.network_timeout_seconds = 10.0  # 网络超时 10秒
        
    def check_pnl(self, current_pnl: float) -> bool:
        """
        检查PnL是否触及熔断
        
        Args:
            current_pnl: 当前累计盈亏 (USDT)
            
        Returns:
            True: 安全
            False: 熔断触发
        """
        loss_pct = (abs(current_pnl) / self.initial_capital) * 100
        
        if current_pnl < 0 and loss_pct > self.max_drawdown_pct:
            self.last_trigger_reason = f"PnL Loss > {self.max_drawdown_pct}% (Current: -{loss_pct:.2f}%)"
            logger.error(f"🚨 Circuit Breaker Triggered: {self.last_trigger_reason}")
            return False
            
        return True
        
    def check_price_deviation(self, market_price: float, oracle_price: float) -> bool:
        """
        检查价格偏差
        
        Args:
            market_price: 交易所成交价
            oracle_price: Oracle参考价
            
        Returns:
            True: 安全
            False: 熔断触发
        """
        if oracle_price <= 0:
            return True # 忽略无效Oracle
            
        deviation = abs(market_price - oracle_price) / oracle_price * 100
        
        if deviation > self.max_price_deviation_pct:
            self.last_trigger_reason = f"Price Deviation > {self.max_price_deviation_pct}% (Current: {deviation:.2f}%)"
            logger.error(f"🚨 Circuit Breaker Triggered: {self.last_trigger_reason}")
            return False
            
        return True
        
    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = time.time()
        
    def check_network(self) -> bool:
        """
        检查网络心跳
        
        Returns:
            True: 连接正常
            False: 超时熔断
        """
        age = time.time() - self.last_heartbeat
        
        if age > self.network_timeout_seconds:
            self.last_trigger_reason = f"Network Timeout ({age:.1f}s > {self.network_timeout_seconds}s)"
            logger.error(f"🚨 Circuit Breaker Triggered: {self.last_trigger_reason}")
            return False
            
        return True
