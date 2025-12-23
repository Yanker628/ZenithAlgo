import ccxt
from typing import Dict, Optional
import math

class PrecisionHelper:
    """
    交易所精度辅助工具
    
    处理价格和数量的精度舍入，确保符合交易所要求
    """
    
    def __init__(self):
        self.exchange = ccxt.mexc()
        self.markets_loaded = False
        self.precision_cache: Dict[str, Dict] = {}
    
    def load_markets(self):
        """加载市场信息（同步方法，初始化时调用）"""
        if not self.markets_loaded:
            self.exchange.load_markets()
            self.markets_loaded = True
            
            # 缓存精度信息
            for symbol in self.exchange.symbols:
                market = self.exchange.market(symbol)
                
                # 获取原始精度
                p_prec = market.get('precision', {}).get('price', 8)
                a_prec = market.get('precision', {}).get('amount', 8)
                
                # 转换 tick size -> decimal places
                # 如果是小于1的浮点数，说明是tick size，需要转换
                if isinstance(p_prec, float) and 0 < p_prec < 1:
                    p_prec = int(round(-math.log10(p_prec)))
                else:
                    p_prec = int(p_prec)
                    
                if isinstance(a_prec, float) and 0 < a_prec < 1:
                    a_prec = int(round(-math.log10(a_prec)))
                else:
                    a_prec = int(a_prec)

                self.precision_cache[symbol] = {
                    'price': market['precision']['price'],
                    'amount': market['precision']['amount'],
                    'price_precision': p_prec,
                    'amount_precision': a_prec,
                }
    
    def round_price(self, symbol: str, price: float) -> float:
        """
        将价格舍入到交易所允许的精度
        
        Args:
            symbol: 交易对
            price: 原始价格
            
        Returns:
            舍入后的价格
        """
        # 使用缓存的精度（如果market已加载）
        if symbol in self.precision_cache:
            precision = self.precision_cache[symbol]['price_precision']
            return round(price, precision)
        
        # 默认精度：4位小数（适用于大多数USDT交易对）
        return round(price, 4)
    
    def round_amount(self, symbol: str, amount: float) -> float:
        """
        将数量舍入到交易所允许的精度
        
        Args:
            symbol: 交易对
            amount: 原始数量
            
        Returns:
            舍入后的数量
        """
        # 使用缓存的精度（如果available）
        if symbol in self.precision_cache:
            precision = self.precision_cache[symbol]['amount_precision']
            return round(amount, precision)
        
        # 默认精度：4位小数
        return round(amount, 4)
    
    def get_min_order_size(self, symbol: str) -> float:
        """获取最小订单量"""
        if not self.markets_loaded:
            self.load_markets()
        
        market = self.exchange.market(symbol)
        return market.get('limits', {}).get('amount', {}).get('min', 0.0001)
    
    def get_price_tick(self, symbol: str) -> float:
        """获取价格最小变动单位（tick size）"""
        if not self.markets_loaded:
            self.load_markets()
        
        market = self.exchange.market(symbol)
        # 价格tick通常是10^(-precision)
        precision = self.precision_cache.get(symbol, {}).get('price_precision', 4)
        return 10 ** (-precision)

    def get_min_cost(self, symbol: str) -> float:
        """获取最小成交额限制（min notional / min cost）"""
        if not self.markets_loaded:
            self.load_markets()

        market = self.exchange.market(symbol)
        return market.get('limits', {}).get('cost', {}).get('min', 0.0) or 0.0
    
    def validate_order(self, symbol: str, price: float, amount: float) -> tuple:
        """
        验证订单参数是否符合交易所要求
        
        Returns:
            (is_valid, error_message)
        """
        if not self.markets_loaded:
            self.load_markets()
        
        market = self.exchange.market(symbol)
        limits = market.get('limits', {})
        
        # 检查数量
        min_amount = limits.get('amount', {}).get('min', 0)
        max_amount = limits.get('amount', {}).get('max', float('inf'))
        
        if amount < min_amount:
            return False, f"数量太小: {amount} < {min_amount}"
        if amount > max_amount:
            return False, f"数量太大: {amount} > {max_amount}"
        
        # 检查价格
        min_price = limits.get('price', {}).get('min', 0)
        max_price = limits.get('price', {}).get('max', float('inf'))
        
        if price < min_price:
            return False, f"价格太低: {price} < {min_price}"
        if price > max_price:
            return False, f"价格太高: {price} > {max_price}"
        
        # 检查订单价值
        min_cost = limits.get('cost', {}).get('min', 0)
        order_cost = price * amount
        
        if order_cost < min_cost:
            return False, f"订单价值太小: {order_cost} < {min_cost}"
        
        return True, "OK"


# 全局单例
_precision_helper: Optional[PrecisionHelper] = None

def get_precision_helper() -> PrecisionHelper:
    """获取精度辅助工具单例"""
    global _precision_helper
    if _precision_helper is None:
        _precision_helper = PrecisionHelper()
    return _precision_helper
