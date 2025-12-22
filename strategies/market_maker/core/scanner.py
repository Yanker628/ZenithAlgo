import ccxt
import time
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class MarketScanner:
    """
    智能做市选品扫描器
    
    功能:
    1. 发现 MEXC 上的新山寨币
    2. 安全性校验 (Oracle Check): 确认 Binance 是否上线
    3. 流动性校验: 避免极低流动性的盘口
    """
    
    def __init__(self):
        # 初始化交易所 API (只读)
        # ⚠️ 强制指定 defaultType='spot'，避免连接到 fapi/dapi 导致超时
        self.binance = ccxt.binance({'options': {'defaultType': 'spot'}})
        self.mexc = ccxt.mexc({'options': {'defaultType': 'spot'}})
        self.okx = ccxt.okx({'options': {'defaultType': 'spot'}})
        
        # 缓存
        self.safe_symbols_cache = set()
        self.last_update = 0
        
    def refresh_markets(self):
        """刷新市场数据"""
        try:
            # 1. 获取 Binance 所有交易对 (作为白名单)
            self.binance.load_markets()
            binance_symbols = set(self.binance.symbols)
            
            # 2. 获取 OKX 交易对 (辅助白名单)
            self.okx.load_markets()
            okx_symbols = set(self.okx.symbols)
            
            # 合并白名单
            self.safe_symbols_cache = binance_symbols.union(okx_symbols)
            self.last_update = time.time()
            
            logger.info(f"✅ Loaded {len(self.safe_symbols_cache)} safe symbols from Binance/OKX")
            
        except Exception as e:
            logger.error(f"❌ Failed to refresh markets: {e}")

    def analyze_symbol(self, symbol: str) -> Dict:
        """
        分析单个交易对的做市可行性
        
        Returns:
            {
                'is_safe': bool,      # 是否在白名单
                'risk_level': str,    # LOW, MEDIUM, HIGH
                'reason': str
            }
        """
        # 确保缓存不仅仅是空的
        if not self.safe_symbols_cache:
            self.refresh_markets()
            
        # 1. 安全性检查 (External Oracle)
        # 注意: 各交易所命名可能不同 (e.g. BTC/USDT)
        # 简单归一化: 移除 '/' 并大写
        target = symbol.replace('/', '').upper()
        
        is_listed_on_major = False
        for safe_sym in self.safe_symbols_cache:
            if safe_sym.replace('/', '').upper() == target:
                is_listed_on_major = True
                break
                
        if not is_listed_on_major:
            return {
                'is_safe': False,
                'risk_level': 'HIGH',
                'reason': 'Not listed on Binance/OKX (Potential Toxic/Manipulation)'
            }
            
        # 2. 流动性检查 (Mexc Depth)
        try:
            orderbook = self.mexc.fetch_order_book(symbol, limit=5)
            bid = orderbook['bids'][0][0] if orderbook['bids'] else 0
            ask = orderbook['asks'][0][0] if orderbook['asks'] else 0
            
            if bid == 0 or ask == 0:
                return {'is_safe': False, 'risk_level': 'HIGH', 'reason': 'No Liquidity'}
                
            spread = (ask - bid) / bid
            
            # 如果价差过大 (>2%)，说明流动性枯竭
            if spread > 0.02:
                return {
                    'is_safe': True, 
                    'risk_level': 'MEDIUM', 
                    'reason': f'Wide Spread ({spread*100:.2f}%)'
                }
                
            return {
                'is_safe': True, 
                'risk_level': 'LOW', 
                'reason': 'Safe to trade'
            }
            
        except Exception as e:
            logger.error(f"Failed to fetch depth for {symbol}: {e}")
            return {'is_safe': False, 'risk_level': 'UNKNOWN', 'reason': str(e)}

    def scan_opportunities(self, target_symbols: List[str]) -> List[str]:
        """扫描列表并返回安全的标的"""
        safe_list = []
        for sym in target_symbols:
            result = self.analyze_symbol(sym)
            logger.info(f"🔍 Analyzing {sym}: {result['risk_level']} - {result['reason']}")
            
            if result['risk_level'] == 'LOW':
                safe_list.append(sym)
                
        return safe_list


# ===== 测试代码 =====
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = MarketScanner()
    
    targets = ['BTC/USDT', 'ETH/USDT', 'PEPE/USDT', 'FAP/USDT', 'FAKECOIN/USDT']
    
    print("\n🔍 开始智能选品扫描...")
    safe_ones = scanner.scan_opportunities(targets)
    
    print(f"\n✅ 最终推荐做市标的: {safe_ones}")
