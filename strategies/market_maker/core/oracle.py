import ccxt.async_support as ccxt
import asyncio
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class MultiSourceOracle:
    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self.running = False
        
        # 数据缓存
        self.prices: Dict[str, Dict] = {}  # {symbol: {'mid': 100, 'ts': 123456}}
        
        # 交易所实例 (按优先级排序)
        self.exchanges = [
            {'name': 'binance', 'ccxt': ccxt.binance, 'options': {'defaultType': 'spot'}},
            {'name': 'okx', 'ccxt': ccxt.okx, 'options': {'defaultType': 'spot'}},
            {'name': 'bybit', 'ccxt': ccxt.bybit, 'options': {'defaultType': 'spot'}},
            {'name': 'gateio', 'ccxt': ccxt.gateio, 'options': {'defaultType': 'spot'}},
        ]
        
        self.active_exchange = None
        self.active_exchange_name = "None"

    async def connect(self):
        """寻找并连接可用的交易所"""
        logger.info("🔮 Initializing Oracle...")
        
        for ex_config in self.exchanges:
            name = ex_config['name']
            logger.info(f"🔮 Testing Oracle Source: {name.upper()}...")
            
            try:
                # 初始化交易所
                exchange = ex_config['ccxt'](ex_config.get('options', {}))
                exchange.timeout = 5000  # 5s 超时
                
                # 测试连接 (获取第一个 ticker)
                test_symbol = self.symbols[0]
                await exchange.fetch_ticker(test_symbol)
                
                logger.info(f"✅ Oracle Selected: {name.upper()}")
                self.active_exchange = exchange
                self.active_exchange_name = name
                return True
                
            except Exception as e:
                logger.warning(f"❌ Source {name.upper()} failed: {e}")
                if 'exchange' in locals():
                    await exchange.close()
                    
        logger.error("❌ ALL ORACLE SOURCES FAILED! No reference price available.")
        return False

    async def start(self):
        """启动价格轮询循环"""
        if not self.active_exchange:
            success = await self.connect()
            if not success:
                return

        self.running = True
        logger.info(f"🔮 Oracle started using {self.active_exchange_name.upper()}")
        
        while self.running:
            try:
                # 批量获取行情 (如果支持) 或 循环获取
                # 为了通用性，循环获取
                for symbol in self.symbols:
                    ticker = await self.active_exchange.fetch_ticker(symbol)
                    
                    mid_price = (ticker['bid'] + ticker['ask']) / 2
                    self.prices[symbol] = {
                        'mid': mid_price,
                        'bid': ticker['bid'],
                        'ask': ticker['ask'],
                        'ts': asyncio.get_event_loop().time()
                    }
                    
                # 1秒更新一次
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"⚠️ Oracle Fetch Error ({self.active_exchange_name}): {e}")
                await asyncio.sleep(2)
                # 可以在这里添加重新选择源的逻辑
                
    def get_price(self, symbol: str) -> Optional[Dict]:
        """获取最新参考价格"""
        return self.prices.get(symbol)

    async def close(self):
        self.running = False
        if self.active_exchange:
            await self.active_exchange.close()
