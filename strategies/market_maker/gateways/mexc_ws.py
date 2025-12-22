import asyncio
import json
import time
import logging
import websockets
from typing import Dict, Optional, Callable, List

logger = logging.getLogger(__name__)

class MexcWebsocketClient:
    """
    MEXC 高性能 WebSocket 客户端
    
    功能:
    1. 维护实时 Orderbook (Local Cache)
    2. 接收实时成交 (Trade) 用于 VPIN 计算
    3. 自动重连与心跳保活
    """
    
    WS_URL = "wss://wbs.mexc.com/ws"
    
    def __init__(self, symbols: List[str]):
        """
        Args:
            symbols: 订阅的交易对列表 (e.g. ['BTC/USDT', 'ETH/USDT'])
        """
        self.symbols = [s.replace('/', '') for s in symbols] # 格式化为符号 (e.g. BTCUSDT)
        self.running = False
        self.ws = None
        
        # 数据缓存
        self.orderbooks: Dict[str, Dict] = {}  # {symbol: {'bids': [], 'asks': [], 'ts': 0}}
        self.trades: Dict[str, List] = {}      # {symbol: [latest_trades]}
        
        # 价格历史（用于动态价差）
        from collections import deque
        self.price_history = {sym: deque(maxlen=30) for sym in self.symbols}
        self.last_mid_price = {sym: 0.0 for sym in self.symbols}
        
        # 回调函数
        self.on_depth_update = None

    async def _subscribe(self):
        """订阅 Orderbook 和 Deals"""
        for symbol in self.symbols:
            # 尝试小写符号
            lower_sym = symbol.lower()
            
            # 订阅深度
            depth_msg = {
                "method": "SUBSCRIPTION",
                "params": [f"spot@public.limit.depth.v3.api@{symbol}@5"]
            }
            await self.ws.send(json.dumps(depth_msg))
            
            # 订阅成交
            trade_msg = {
                "method": "SUBSCRIPTION",
                "params": [f"spot@public.deals.v3.api@{symbol}"]
            }
            await self.ws.send(json.dumps(trade_msg))
            
            logger.info(f"📡 Subscribed to {symbol}")
        
    async def connect(self):
        """建立连接 (优先 WS，失败则自动切换 REST Polling)"""
        self.running = True
        
        # 尝试启动 WS 连接
        ws_task = asyncio.create_task(self._ws_connect_loop())
        
        # 同时启动 REST Polling (作为保底，或者 WS Blocked 时的主力)
        rest_task = asyncio.create_task(self._rest_polling_loop())
        
        await asyncio.gather(ws_task, rest_task)

    async def _ws_connect_loop(self):
        """WebSocket 连接循环"""
        retry_count = 0
        max_retries = 3  # 最多重试 3 次后放弃 WS
        
        while self.running and retry_count < max_retries:
            try:
                logger.info(f"🔗 Connecting to {self.WS_URL}...")
                # 添加 User-Agent 和 Origin (尝试绕过 WAF)
                ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                origin = "https://www.mexc.com"
                
                async with websockets.connect(self.WS_URL, close_timeout=5, user_agent_header=ua, origin=origin) as ws:
                    self.ws = ws
                    logger.info("✅ MEXC WebSocket Connected")
                    
                    # 订阅行情
                    await self._subscribe()
                    
                    # 开始接收消息
                    await self._message_loop()
                    
            except websockets.exceptions.ConnectionClosedError as e:
                # 检查是否是 1005 错误（服务器主动关闭）
                if e.code == 1005:
                    logger.warning(f"⚠️ WebSocket 1005 错误（服务器关闭连接）- 放弃 WS，使用 REST Polling")
                    retry_count = max_retries  # 停止重试 WS
                    break
                else:
                    logger.warning(f"⚠️ WS Error (Will retry): {e}")
                    retry_count += 1
                    await asyncio.sleep(2)
                    
            except Exception as e:
                logger.warning(f"⚠️ WS Connection failed: {e}")
                retry_count += 1
                await asyncio.sleep(2)
        
        if retry_count >= max_retries:
            logger.info("⚠️ WebSocket 连接失败，完全依赖 REST Polling")

    async def _rest_polling_loop(self):
        """REST API 轮询循环 (Fallback)"""
        import ccxt.async_support as ccxt
        
        logger.info("🔄 Starting REST Polling Fallback...")
        exchange = ccxt.mexc()
        
        try:
            while self.running:
                try:
                    for symbol in self.symbols:
                        # 还原格式 ETHUSDT -> ETH/USDT
                        ccxt_symbol = f"{symbol[:-4]}/{symbol[-4:]}" # 简单假设 USDT 结尾
                        
                        # 1. Fetch Orderbook
                        ob = await exchange.fetch_order_book(ccxt_symbol, limit=5)
                        self.orderbooks[symbol] = {
                            'bids': ob['bids'],
                            'asks': ob['asks'],
                            'ts': time.time()
                        }
                        
                        # 2. 记录价格历史（用于动态价差）
                        if ob['bids'] and ob['asks']:
                            mid_price = (ob['bids'][0][0] + ob['asks'][0][0]) / 2
                            self.price_history[symbol].append({
                                'price': mid_price,
                                'timestamp': time.time()
                            })
                            self.last_mid_price[symbol] = mid_price
                        
                        # 3. Fetch Trades
                        trades = await exchange.fetch_trades(ccxt_symbol, limit=20)
                        self._process_rest_trades(symbol, trades)
                        
                    await asyncio.sleep(1) # 优化：2秒 -> 1秒
                    
                except Exception as e:
                    logger.error(f"❌ REST Polling Error: {e}")
                    await asyncio.sleep(5)
        finally:
            # 确保资源被释放
            await exchange.close()
            logger.info("🔒 REST Polling stopped and resources released")

    def _process_rest_trades(self, symbol, trades):
        """处理 REST 返回的成交数据"""
        clean_trades = []
        for t in trades:
            clean_trades.append({
                'price': t['price'],
                'volume': t['amount'],
                'side': t['side'],
                'ts': t['timestamp']
            })
        self.trades[symbol] = clean_trades
        
    async def _message_loop(self):
        """消息处理循环"""
        while self.running:
            try:
                msg = await self.ws.recv()
                data = json.loads(msg)
                
                # Debug raw msg only if needed
                # logger.info(f"raw_msg: {str(data)[:100]}")
                
                if data.get('msg') == 'ping':
                    await self.ws.send(json.dumps({"msg": "pong"}))
                    continue
                
                if 'c' in data:
                    channel = data['c']
                    if 'limit.depth' in channel:
                        self._handle_depth(data)
                    elif 'deals' in channel:
                        self._handle_trade(data)
                        
            except Exception as e:
                raise e # 让外层重连

    def _handle_depth(self, data):
        """处理深度数据更新"""
        # MEXC 格式: {'c': '...', 'd': {'asks': [{'p': '...', 'v': '...'}], 'bids': [...]}, 's': 'BTCUSDT'}
        # 注意：MEXC返回的即是全量快照(Limit Depth)，直接覆盖即可
        payload = data.get('d', {})
        symbol = data.get('s')  # e.g. BTCUSDT (需转换回 BTC/USDT 映射如果需要)
        
        if not symbol or 'asks' not in payload:
            return

        # 转换数据格式
        bids = [[float(i['p']), float(i['v'])] for i in payload['bids']]
        asks = [[float(i['p']), float(i['v'])] for i in payload['asks']]
        
        self.orderbooks[symbol] = {
            'bids': bids,
            'asks': asks,
            'ts': time.time()
        }
        
        # 触发回调 (如果需要)
        # if self.on_depth_update:
        #     self.on_depth_update(symbol, self.orderbooks[symbol])

    def _handle_trade(self, data):
        """处理成交数据"""
        # payload: {'deals': [{'p': '...', 'v': '...', 't': time, 'S': 1(buy)/2(sell)}]}
        payload = data.get('d', {})
        symbol = data.get('s')
        deals = payload.get('deals', [])
        
        if not deals:
            return
            
        if symbol not in self.trades:
            self.trades[symbol] = []
            
        for deal in deals:
            trade = {
                'price': float(deal['p']),
                'volume': float(deal['v']),
                'side': 'buy' if deal['S'] == 1 else 'sell',
                'ts': deal['t']
            }
            self.trades[symbol].append(trade)
            
        # 保持列表长度，只保留最近 1000 条
        if len(self.trades[symbol]) > 1000:
            self.trades[symbol] = self.trades[symbol][-1000:]

    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """获取本地缓存的订单簿"""
        # symbol: BTC/USDT -> BTCUSDT
        clean_sym = symbol.replace('/', '')
        return self.orderbooks.get(clean_sym)

    def get_recent_trades(self, symbol: str) -> List[Dict]:
        """获取最近成交"""
        clean_sym = symbol.replace('/', '')
        return self.trades.get(clean_sym, [])


# ===== 测试代码 =====
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    async def main():
        client = MexcWebsocketClient(['ETH/USDT'])
        
        # 启动连接任务
        task = asyncio.create_task(client.connect())
        
        # 模拟运行10秒
        print("⏳ Connecting to MEXC WS...")
        await asyncio.sleep(5)
        
        # 打印一次数据
        ob = client.get_orderbook('ETH/USDT')
        if ob:
            print(f"\n📊 ETH/USDT Orderbook:")
            print(f"   Bid1: {ob['bids'][0][0]} (Qty: {ob['bids'][0][1]})")
            print(f"   Ask1: {ob['asks'][0][0]} (Qty: {ob['asks'][0][1]})")
        else:
            print("\n⚠️ No Orderbook data yet")
            
        # 停止
        client.running = False
        await task

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    def _process_rest_trades(self, symbol, trades):
        """处理 REST 返回的成交数据"""
        if not trades:
            return
            
        self.trades[symbol] = {
            'price': trades[-1]['price'],
            'side': trades[-1]['side'],
            'ts': trades[-1]['timestamp']
        }
    
    def calculate_volatility(self, symbol: str) -> float:
        """计算实时波动率（基于本地价格历史，零延迟）"""
        history = self.price_history.get(symbol, [])
        
        if len(history) < 10:
            return 0.01  # 默认波动率 1%
        
        # 提取价格
        prices = [h['price'] for h in history]
        
        # 计算对数收益率
        import numpy as np
        log_returns = np.diff(np.log(prices))
        
        # 标准差（波动率）
        volatility = np.std(log_returns)
        
        # 年化转换（假设每秒1个数据点）
        volatility_pct = volatility * 100  # 转为百分比
        
        return max(0.001, min(volatility_pct, 0.05))  # 限制在 0.001% - 0.05%
