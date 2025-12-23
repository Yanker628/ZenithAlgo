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
        self._data_event = asyncio.Event()
        
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
        """建立连接 (WebSocket 优先，REST Polling 作为 fallback)"""
        self.running = True

        ws_task = asyncio.create_task(self._ws_connect_loop())
        rest_task = None

        try:
            # 给 WS 一个短窗口抢先提供数据；若无数据则启动 REST fallback
            try:
                await asyncio.wait_for(self._data_event.wait(), timeout=3.0)
                logger.info("✅ Using WebSocket as primary market data source")
            except asyncio.TimeoutError:
                logger.warning("⚠️ WS not ready in 3s, starting REST polling fallback")
                rest_task = asyncio.create_task(self._rest_polling_loop())

            while self.running:
                if ws_task.done():
                    if rest_task is None:
                        logger.warning("⚠️ WS stopped, switching to REST polling fallback")
                        rest_task = asyncio.create_task(self._rest_polling_loop())
                    await rest_task
                    break

                if rest_task is not None and rest_task.done():
                    break

                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass
        finally:
            if rest_task is not None and not rest_task.done():
                rest_task.cancel()
                try:
                    await rest_task
                except asyncio.CancelledError:
                    pass
            if not ws_task.done():
                ws_task.cancel()
                try:
                    await ws_task
                except asyncio.CancelledError:
                    pass

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
        """REST API 轮询循环（核心数据源）"""
        import ccxt.async_support as ccxt
        
        # 启动延迟，确保对象初始化完成
        await asyncio.sleep(0.5)
        
        logger.info("🔄 Starting REST Polling...")
        exchange = ccxt.mexc({
            'enableRateLimit': True,
            'timeout': 10000,  # 10秒超时
        })
        
        iteration = 0
        
        try:
            logger.info(f"📊 REST Polling ready for symbols: {self.symbols}")
            
            while self.running:
                iteration += 1
                
                # 定期输出心跳日志
                if iteration % 10 == 1:
                    logger.info(f"🔁 REST Polling iteration #{iteration}")
                
                try:
                    for symbol in self.symbols:
                        # 检查运行状态
                        if not self.running:
                            break
                        
                        # 符号转换: ETHUSDT -> ETH/USDT
                        if symbol.endswith('USDT'):
                            base = symbol[:-4]
                            ccxt_symbol = f"{base}/USDT"
                        else:
                            logger.warning(f"⚠️ 不支持的符号格式: {symbol}")
                            continue
                        
                        # 获取订单簿
                        ob = await exchange.fetch_order_book(ccxt_symbol, limit=5)
                        self.orderbooks[symbol] = {
                            'bids': ob['bids'][:5],
                            'asks': ob['asks'][:5],
                            'ts': time.time()
                        }
                        if not self._data_event.is_set():
                            self._data_event.set()
                        
                        # 首次成功输出确认
                        if iteration == 1:
                            logger.info(f"✅ {symbol} orderbook ready: bid={ob['bids'][0][0]}, ask={ob['asks'][0][0]}")
                        
                        # 更新价格历史（用于波动率计算）
                        if ob['bids'] and ob['asks']:
                            mid_price = (ob['bids'][0][0] + ob['asks'][0][0]) / 2
                            self.price_history[symbol].append({
                                'price': mid_price,
                                'timestamp': time.time()
                            })
                            self.last_mid_price[symbol] = mid_price
                        
                        # 获取成交数据（非关键，失败不影响）
                        try:
                            trades = await exchange.fetch_trades(ccxt_symbol, limit=20)
                            self._process_rest_trades(symbol, trades)
                        except Exception:
                            pass  # 成交数据不是必须的
                    
                    # 每秒更新一次
                    await asyncio.sleep(1)
                    
                except asyncio.CancelledError:
                    # 正常取消，向上传播
                    raise
                except Exception as e:
                    # 单次迭代错误，记录后继续
                    logger.error(f"❌ REST Polling iteration error: {e}")
                    await asyncio.sleep(5)  # 错误后等待5秒再重试
                    
        except asyncio.CancelledError:
            logger.info("🛑 REST Polling cancelled")
        except Exception as e:
            logger.error(f"❌ REST Polling fatal error: {e}")
        finally:
            # 确保资源释放
            try:
                await exchange.close()
                logger.info("🔒 REST Polling stopped and resources released")
            except Exception as e:
                logger.error(f"⚠️ Error closing exchange: {e}")

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
        if not self._data_event.is_set():
            self._data_event.set()
        
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
    
    def is_data_ready(self) -> bool:
        """检查是否有可用数据"""
        return len(self.orderbooks) > 0
    
    def get_data_age(self, symbol: str) -> float:
        """
        获取数据年龄（秒）
        
        Returns:
            数据年龄，如果无数据返回无穷大
        """
        clean_sym = symbol.replace('/', '')
        ob = self.orderbooks.get(clean_sym)
        if ob:
            return time.time() - ob['ts']
        return float('inf')
    
    def calculate_volatility(self, symbol: str) -> float:
        """计算实时波动率（基于本地价格历史,零延迟）"""
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
        await asyncio.sleep(3)
        
        # 第一次检查
        ob = client.get_orderbook('ETH/USDT')
        if ob:
            print(f"\n📊 ETH/USDT Orderbook (3s):") 
            print(f"   Bid1: {ob['bids'][0][0]} (Qty: {ob['bids'][0][1]})")
            print(f"   Ask1: {ob['asks'][0][0]} (Qty: {ob['asks'][0][1]})")
        else:
            print("\n⚠️ No Orderbook data yet (3s), waiting...")
            
            # 再等5秒
            await asyncio.sleep(5)
            ob = client.get_orderbook('ETH/USDT')
            if ob:
                print(f"\n📊 ETH/USDT Orderbook (8s):")
                print(f"   Bid1: {ob['bids'][0][0]} (Qty: {ob['bids'][0][1]})")
                print(f"   Ask1: {ob['asks'][0][0]} (Qty: {ob['asks'][0][1]})")
            else:
                print("\n❌ Still no Orderbook data after 8s")
            
        # 停止
        client.running = False
        await task

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
