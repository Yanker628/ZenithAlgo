import asyncio
import logging
from typing import Dict, List, Callable, Optional
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)

class OrderMonitor:
    """
    订单成交监控器
    
    使用MEXC WebSocket监听订单状态变化，
    在订单成交时触发回调更新库存和统计
    """
    
    def __init__(self, exchange, inventory_manager):
        """
        Args:
            exchange: ccxt交易所实例
            inventory_manager: 库存管理器实例
        """
        self.exchange = exchange
        self.inventory_manager = inventory_manager
        self.running = False
        
        # 订单跟踪
        self.active_orders: Dict[str, Dict] = {}  # {order_id: order_info}
        self.filled_orders: deque = deque(maxlen=100)  # 最近100笔成交
        
        # 统计数据
        self.stats = {
            'total_filled': 0,
            'total_buy': 0,
            'total_sell': 0,
            'total_volume': 0.0,
            'realized_pnl': 0.0, # Cash Flow PnL
        }
        
        # 回调函数
        self.on_order_filled: Optional[Callable] = None
        self.on_order_cancelled: Optional[Callable] = None
        
    def register_order(self, order_id: str, symbol: str, side: str, 
                      price: float, amount: float):
        """
        注册新订单到监控系统
        
        Args:
            order_id: 订单ID
            symbol: 交易对
            side: 'buy' 或 'sell'
            price: 订单价格
            amount: 订单数量
        """
        self.active_orders[order_id] = {
            'id': order_id,
            'symbol': symbol,
            'side': side,
            'price': price,
            'amount': amount,
            'filled': 0.0,
            'status': 'open',
            'timestamp': datetime.now(),
        }
        logger.info(f"📝 注册订单: {order_id} {symbol} {side} {amount}@{price}")
    
    async def sync_open_orders(self):
        """启动时同步挂单状态"""
        logger.info("🔄 Syncing open orders from exchange...")
        try:
            # 获取所有挂单 (需要在IO线程运行如果exchange是同步的，这里假设executor.exchange是同步ccxt实例? 
            # 实际上main.py传进来的是 ccxt.mexc instances. 如果是同步的直接调，如果是异步的需要await.
            # 观察 main.py: HighFrequencyExecutor用的是 ccxt.async_support?
            # 检查 HighFrequencyExecutor code... 假设是异步的，或者用 run_in_executor compatible way
            
            # 安全起见，尝试探测是否是协程
            if asyncio.iscoroutinefunction(self.exchange.fetch_open_orders):
                open_orders = await self.exchange.fetch_open_orders()
            else:
                open_orders = await asyncio.get_event_loop().run_in_executor(
                    None, self.exchange.fetch_open_orders
                )

            for order in open_orders:
                order_id = order['id']
                if order_id not in self.active_orders:
                    self.register_order(
                        order_id, 
                        order['symbol'], 
                        order['side'], 
                        order['price'], 
                        order['amount']
                    )
            logger.info(f"✅ Synced {len(open_orders)} open orders.")
        except Exception as e:
            logger.error(f"❌ Failed to sync open orders: {e}")

    async def watch_orders_polling(self):
        """
        轮询方式监控订单状态（备选方案）
        
        每秒查询一次所有活跃订单的状态
        """
        logger.info("🔍 启动订单轮询监控...")
        
        while self.running:
            try:
                # 获取所有活跃订单ID
                order_ids = list(self.active_orders.keys())
                
                for order_id in order_ids:
                    if order_id not in self.active_orders:
                        continue
                    
                    order_info = self.active_orders[order_id]
                    symbol = order_info['symbol']
                    
                    try:
                        # 查询订单状态
                        if asyncio.iscoroutinefunction(self.exchange.fetch_order):
                            order = await self.exchange.fetch_order(order_id, symbol)
                        else:
                            order = await asyncio.get_event_loop().run_in_executor(
                                None,
                                self.exchange.fetch_order,
                                order_id,
                                symbol
                            )
                        
                        # 处理订单状态变化
                        await self._handle_order_update(order)
                        
                    except Exception as e:
                        logger.error(f"❌ 查询订单{order_id}失败: {e}")
                
                # 每秒查询一次
                await asyncio.sleep(1.0)
                
            except Exception as e:
                logger.error(f"❌ 订单监控循环错误: {e}")
                await asyncio.sleep(5.0)
    
    async def watch_orders_websocket(self):
        """
        WebSocket方式监控订单（推荐方式）
        
        使用CCXT的watch_orders实时监听订单变化
        """
        logger.info("📡 启动订单WebSocket监控...")
        
        try:
            while self.running:
                try:
                    # 使用CCXT的watch_orders
                    if asyncio.iscoroutinefunction(self.exchange.watch_orders):
                        orders = await self.exchange.watch_orders()
                    else:
                        # 如果不支持watch_orders (同步库)，报错退出
                        logger.error("❌ Exchange does not support async watch_orders")
                        break
                    
                    for order in orders:
                        await self._handle_order_update(order)
                        
                except Exception as e:
                    logger.error(f"❌ WebSocket监控错误: {e}")
                    await asyncio.sleep(5.0)
                    
        except asyncio.CancelledError:
            logger.info("📡 WebSocket监控已停止")
    
    async def _handle_order_update(self, order: Dict):
        """
        处理订单状态更新
        
        Args:
            order: CCXT订单对象
        """
        order_id = order['id']
        status = order['status']
        symbol = order['symbol']
        side = order['side']
        filled = order.get('filled', 0)
        
        # 更新本地订单状态
        if order_id in self.active_orders:
            self.active_orders[order_id]['status'] = status
            self.active_orders[order_id]['filled'] = filled
        
        # 处理完全成交
        if status == 'closed' and filled > 0:
            await self._on_order_filled(order)
            
        # 处理取消
        elif status == 'canceled':
            await self._on_order_cancelled(order)
    
    async def _on_order_filled(self, order: Dict):
        """订单成交处理"""
        order_id = order['id']
        symbol = order['symbol']
        side = order['side']
        price = order['price']
        filled = order['filled']
        
        logger.info(f"✅ 订单成交: {order_id} {symbol} {side} {filled}@{price}")
        
        # 更新库存
        cost = order.get('cost', filled * price)
        if hasattr(self.inventory_manager, "apply_fill"):
            try:
                fee = 0.0
                fee_info = order.get("fee")
                if isinstance(fee_info, dict) and fee_info.get("currency") == "USDT":
                    fee = float(fee_info.get("cost") or 0.0)
                self.inventory_manager.apply_fill(symbol, side, filled, price, fee_usdt=fee)
            except Exception:
                self.inventory_manager.update_inventory(symbol, side, filled)
        else:
            self.inventory_manager.update_inventory(symbol, side, filled)
        
        # 更新统计
        self.stats['total_filled'] += 1
        if side == 'buy':
            self.stats['total_buy'] += 1
            # Cash Flow: Outflow (Negative)
            self.stats['realized_pnl'] -= cost
        else:
            self.stats['total_sell'] += 1
            # Cash Flow: Inflow (Positive)
            self.stats['realized_pnl'] += cost
            
        self.stats['total_volume'] += cost
        
        # 记录成交历史
        self.filled_orders.append({
            'id': order_id,
            'symbol': symbol,
            'side': side,
            'price': price,
            'amount': filled,
            'timestamp': datetime.now(),
        })
        
        # 从活跃订单中移除
        if order_id in self.active_orders:
            del self.active_orders[order_id]
        
        # 触发回调
        if self.on_order_filled:
            await self.on_order_filled(order)
    
    async def _on_order_cancelled(self, order: Dict):
        """订单取消处理"""
        order_id = order['id']
        symbol = order['symbol']
        
        logger.info(f"🗑️ 订单已取消: {order_id} {symbol}")
        
        # 从活跃订单中移除
        if order_id in self.active_orders:
            del self.active_orders[order_id]
        
        # 触发回调
        if self.on_order_cancelled:
            await self.on_order_cancelled(order)
    
    async def start(self, use_websocket: bool = True):
        """
        启动订单监控
        
        Args:
            use_websocket: True使用WebSocket, False使用轮询
        """
        self.running = True
        
        # 启动前先同步一次挂单
        await self.sync_open_orders()
        
        if use_websocket and hasattr(self.exchange, 'watch_orders'):
            logger.info("📡 使用WebSocket方式监控订单")
            await self.watch_orders_websocket()
        else:
            logger.info("🔍 使用轮询方式监控订单")
            await self.watch_orders_polling()
    
    def stop(self):
        """停止订单监控"""
        self.running = False
        logger.info("🛑 订单监控已停止")
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return {
            **self.stats,
            'active_orders': len(self.active_orders),
            'recent_fills': list(self.filled_orders)[-10:],  # 最近10笔
        }
        
    def get_session_pnl(self):
        """获取Session PnL (Cash Flow)"""
        return self.stats['realized_pnl']
    
    def get_active_orders(self) -> List[Dict]:
        """获取所有活跃订单"""
        return list(self.active_orders.values())
