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
        # ⚠️ 设置超时为 2 秒，避免在受限网络下阻塞太久
        self.binance = ccxt.binance({
            'options': {'defaultType': 'spot'},
            'timeout': 2000  # 2秒超时
        })
        self.mexc = ccxt.mexc({
            'options': {'defaultType': 'spot'},
            'timeout': 2000
        })
        self.okx = ccxt.okx({
            'options': {'defaultType': 'spot'},
            'timeout': 2000
        })
        
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
        """扫描列表并返回安全的标的（默认低风险）"""
        return self.scan(target_symbols, mode="low_risk")

    def scan(
        self,
        target_symbols: List[str],
        *,
        mode: str = "low_risk",
        limit: Optional[int] = None,
        min_depth_qty: float = 50.0,
        min_spread_pct: float = 0.005,
        max_spread_pct: float = 0.5,
    ) -> List[str]:
        """
        mode:
          - low_risk: 只返回 LOW 风险
          - high_spread: 在“安全白名单”内按价差/深度打分，优先挑价差更大且深度足够的币（适合刷量/捕捉更宽点差）
        """
        if mode == "high_spread":
            ranked = self.rank_by_spread(
                target_symbols,
                min_depth_qty=min_depth_qty,
                min_spread_pct=min_spread_pct,
                max_spread_pct=max_spread_pct,
            )
            symbols = [s for s, _ in ranked]
            return symbols[:limit] if limit else symbols

        safe_list: List[str] = []
        for sym in target_symbols:
            result = self.analyze_symbol(sym)
            logger.info(f"🔍 Analyzing {sym}: {result['risk_level']} - {result['reason']}")
            if result['risk_level'] == 'LOW':
                safe_list.append(sym)
        return safe_list[:limit] if limit else safe_list

    def rank_by_spread(
        self,
        target_symbols: List[str],
        *,
        min_depth_qty: float = 50.0,
        min_spread_pct: float = 0.005,
        max_spread_pct: float = 0.5,
    ) -> List[tuple[str, dict]]:
        """
        返回按“可做市价差”排序的标的列表（先做白名单校验，再按价差与深度筛选）。
        score = spread_pct * depth_score，其中 depth_score 由前5档均值深度归一化。
        """
        if not self.safe_symbols_cache:
            self.refresh_markets()

        results: List[tuple[str, dict]] = []
        for sym in target_symbols:
            # 白名单校验（避免挑到极端操纵盘）
            target = sym.replace('/', '').upper()
            listed = any(s.replace('/', '').upper() == target for s in self.safe_symbols_cache)
            if not listed:
                continue

            try:
                ob = self.mexc.fetch_order_book(sym, limit=5)
                bids = ob.get("bids") or []
                asks = ob.get("asks") or []
                if not bids or not asks:
                    continue
                bid = float(bids[0][0])
                ask = float(asks[0][0])
                if bid <= 0 or ask <= 0 or ask <= bid:
                    continue

                spread_pct = (ask - bid) / bid * 100.0
                if spread_pct < min_spread_pct or spread_pct > max_spread_pct:
                    continue

                bid_depth = sum(float(x[1]) for x in bids[:5])
                ask_depth = sum(float(x[1]) for x in asks[:5])
                depth_qty = (bid_depth + ask_depth) / 2.0
                if depth_qty < min_depth_qty:
                    continue

                depth_score = max(0.5, min(2.0, depth_qty / 100.0))
                score = spread_pct * depth_score
                results.append(
                    (
                        sym,
                        {
                            "score": score,
                            "spread_pct": spread_pct,
                            "depth_qty": depth_qty,
                            "bid": bid,
                            "ask": ask,
                        },
                    )
                )
            except Exception:
                continue

        results.sort(key=lambda x: x[1]["score"], reverse=True)
        return results


# ===== 测试代码 =====
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = MarketScanner()
    
    targets = ['BTC/USDT', 'ETH/USDT', 'PEPE/USDT', 'FAP/USDT', 'FAKECOIN/USDT']
    
    print("\n🔍 开始智能选品扫描...")
    safe_ones = scanner.scan_opportunities(targets)
    
    print(f"\n✅ 最终推荐做市标的: {safe_ones}")
