import ccxt
import time
import logging
import asyncio
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class HighFrequencyExecutor:
    """
    高频做市执行器 (HFT Executor)
    
    专为 MEXC 做市优化:
    1. 非阻塞异步下单
    2. 批量撤单优化
    3. 异常熔断保护
    4. 自动处理精度 (Precision)
    """
    
    def __init__(self, dry_run: bool = True, order_monitor=None):
        self.dry_run = dry_run
        self.order_monitor = order_monitor  # 订单监控器
        
        # 使用 ccxt 连接 MEXC
        # 注意: 实际 key 需从 env 读取
        import os
        from dotenv import load_dotenv
        
        # 确保加载 (executor 可能被其他模块独立调用)
        env_path = os.path.abspath("config/.env")
        load_dotenv(env_path)
        
        api_key = os.getenv("MEXC_API_KEY")
        secret = os.getenv("MEXC_API_SECRET")
        
        if not dry_run and (not api_key or not secret):
            raise ValueError("❌ Missing MEXC API Key for LIVE trading!")
            
        self.exchange = ccxt.mexc({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True, # 遵守限频
            'options': {'defaultType': 'spot'}
        })
        
        self.active_orders: Dict[str, List[str]] = {} # {symbol: [order_ids]}
        self.error_count = 0
        self.markets_loaded = False
        
        # 订单历史追踪
        from collections import deque
        self.order_history = deque(maxlen=10)
        self.total_orders = 0
        self.total_filled = 0
    
    async def initialize(self):
        """初始化市场信息 (精度等)"""
        if self.dry_run:
            return
            
        try:
            logger.info("📡 Loading MEXC markets...")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.exchange.load_markets)
            self.markets_loaded = True
            logger.info(f"✅ Loaded {len(self.exchange.symbols)} markets")
        except Exception as e:
            logger.error(f"❌ Init failed: {e}")
            raise
            
    async def cancel_all_orders(self, symbol: str):
        """撤销某个交易对的所有挂单"""
        if self.dry_run:
            return
            
        try:
            # MEXC 支持按 symbol 批量撤单
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.exchange.cancel_all_orders, symbol)
            # logger.info(f"🗑️ Cancelled all orders for {symbol}")
            self.active_orders[symbol] = []
        except Exception as e:
            self.error_count += 1
            logger.error(f"❌ Cancel failed: {e}")

    async def place_orders(self, symbol: str, bid_price: float, ask_price: float, quantity: float):
        """
        同时挂买单和卖单 (双向报价)
        
        Args:
            quantity: 基础货币数量 (e.g. 0.1 SOL)
        """
        if self.dry_run:
            # logger.info(f"🔧 DRY: Place {symbol} Bid={bid_price} Ask={ask_price} Qty={quantity}")
            return
            
        if not self.markets_loaded:
            await self.initialize()
            
        # 1. 精度处理 (Normalization)
        market = self.exchange.market(symbol)
        price_bid = self.exchange.price_to_precision(symbol, bid_price)
        price_ask = self.exchange.price_to_precision(symbol, ask_price)
        amount = self.exchange.amount_to_precision(symbol, quantity)
        
        # 2. 并发下单
        loop = asyncio.get_event_loop()
        tasks = []
        
        # 买单
        tasks.append(loop.run_in_executor(
            None, 
            self.exchange.create_order, 
            symbol, 'limit', 'buy', amount, price_bid
        ))
        
        # 卖单
        tasks.append(loop.run_in_executor(
            None, 
            self.exchange.create_order, 
            symbol, 'limit', 'sell', amount, price_ask
        ))
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            new_orders = []
            for res in results:
                if isinstance(res, Exception):
                    logger.error(f"❌ Order failed: {res}")
                    self.error_count += 1
                else:
                    order_id = res['id']
                    new_orders.append(order_id)
                    # logger.info(f"✅ Order placed: {res['side']} @ {res['price']}")
                    
                    # 注册订单到监控器
                    if self.order_monitor:
                        self.order_monitor.register_order(
                            order_id=order_id,
                            symbol=symbol,
                            side=res['side'],
                            price=res['price'],
                            amount=res['amount']
                        )
                    
                    # 更新统计
                    self.total_orders += 1
                    self.order_history.append({
                        'time': time.time(),
                        'symbol': symbol,
                        'side': res['side'],
                        'price': res['price'],
                        'bid': bid_price, # 记录当时的报价
                        'ask': ask_price
                    })
            
            self.active_orders[symbol] = new_orders
            
        except Exception as e:
            logger.error(f"❌ Critical Place Error: {e}")
            self.error_count += 1
            
    def check_health(self) -> bool:
        """熔断检查"""
        # 如果连续错误超过 10 次，熔断
        if self.error_count > 10:
            logger.critical("🚨 TRADING HALTED: Too many errors!")
            return False
        return True
    
    async def close(self):
        """关闭并释放资源"""
        # 在 dry_run 模式下,exchange 可能没有打开的连接
        if not self.dry_run and hasattr(self.exchange, 'close'):
            try:
                await self.exchange.close()
                logger.info("✅ Executor closed successfully")
            except Exception as e:
                logger.warning(f"⚠️ Error closing executor: {e}")
