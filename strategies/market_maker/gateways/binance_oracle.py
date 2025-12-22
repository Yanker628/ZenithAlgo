import asyncio
import json
import logging
import websockets
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

class BinancePriceOracle:
    """
    Binance 价格预言机 (WebSocket)
    
    功能:
    1. 提供全网最准确的参考价格 (Reference Price)
    2. 提供 BBO (Best Bid Offer) 用于构建安全区间
    """
    
    WS_URL = "wss://stream.binance.com:9443/ws"
    
    def __init__(self, symbols: List[str]):
        """
        Args:
            symbols: 交易对列表 (e.g. ['BTC/USDT'])
        """
        self.symbols = [s.replace('/', '').lower() for s in symbols] # binance需小写 btcusdt
        self.running = False
        self.ws = None
        
        # 价格缓存
        self.prices: Dict[str, Dict] = {} # {symbol: {'bid': 0, 'ask': 0, 'ts': 0}}
        
    async def connect(self):
        """建立 WebSocket 连接"""
        self.running = True
        
        # 构建订阅流名称: <symbol>@bookTicker
        streams = [f"{s}@bookTicker" for s in self.symbols]
        stream_url = f"{self.WS_URL}/{'/'.join(streams)}"
        
        while self.running:
            try:
                async with websockets.connect(stream_url) as ws:
                    self.ws = ws
                    logger.info("✅ Binance Oracle Connected")
                    
                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        
                        # 处理 bookTicker 推送
                        # {'u': 400900217, 's': 'BNBUSDT', 'b': '25.35190000', 'B': '31.21000000', 'a': '25.36520000', 'A': '40.66000000'}
                        if 'b' in data and 'a' in data:
                            self._handle_ticker(data)
                            
            except Exception as e:
                logger.error(f"❌ Oracle Error: {e}")
                await asyncio.sleep(2)  # 重连
                logger.info("🔄 Oracle Reconnecting...")

    def _handle_ticker(self, data):
        """处理 Ticker 数据"""
        symbol = data['s'].upper()
        bid = float(data['b'])
        ask = float(data['a'])
        
        self.prices[symbol] = {
            'bid': bid,
            'ask': ask,
            'mid': (bid + ask) / 2,
            'ts': asyncio.get_event_loop().time()
        }

    def get_price(self, symbol: str) -> Optional[Dict]:
        """获取参考价格"""
        clean_sym = symbol.replace('/', '').upper() # 统一用大写
        return self.prices.get(clean_sym)


# ===== 测试代码 =====
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        oracle = BinancePriceOracle(['ETH/USDT', 'SOL/USDT'])
        
        task = asyncio.create_task(oracle.connect())
        
        print("⏳ Waiting for Binance prices...")
        await asyncio.sleep(3)
        
        for _ in range(3):
            data = oracle.get_price('ETH/USDT')
            if data:
                print(f"🔮 Oracle ETH: Mid=${data['mid']:.2f} (Bid:{data['bid']} Ask:{data['ask']})")
            await asyncio.sleep(1)
            
        oracle.running = False
        await task

    asyncio.run(main())
