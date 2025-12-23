
import asyncio
import logging
import signal
import time
import os
from typing import Any, Callable, Dict, List, Optional

from strategies.market_maker.gateways.mexc_ws import MexcWebsocketClient
from strategies.market_maker.core.oracle import MultiSourceOracle
from strategies.market_maker.core.algo import AvellanedaStoikovModel, ASParams
from strategies.market_maker.core.scanner import MarketScanner
from strategies.market_maker.core.executor import HighFrequencyExecutor
from strategies.market_maker.core.inventory_manager import InventoryManager
from strategies.market_maker.core.config import EngineConfig
from strategies.market_maker.core.precision import get_precision_helper
from strategies.market_maker.core.order_monitor import OrderMonitor
from strategies.market_maker.core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

class MarketMakerEngine:
    """
    高频做市商策略引擎 (HFT Market Making Engine)
    
    架构:
    [Mexc WS] --> (Depth/Trade) --> [Engine] <-- (Ref Price) <-- [Binance Oracle]
                                      |
                                  [AS Algo]
                                      |
                                  (Quotes)
                                      |
                                  [Executor]
    """
    
    def __init__(
        self,
        symbols: List[str],
        dry_run: bool = True,
        *,
        scan_symbols: bool = True,
        scanner: MarketScanner | None = None,
        mexc_ws=None,
        oracle=None,
        executor: HighFrequencyExecutor | None = None,
        inventory_manager: InventoryManager | None = None,
        precision=None,
        circuit_breaker: CircuitBreaker | None = None,
        now_fn=None,
        config: EngineConfig | None = None,
    ):
        self.symbols = symbols
        self.dry_run = dry_run
        self.running = False
        self._now = now_fn or time.time
        self.config = config or EngineConfig.from_env()
        
        # 1. 组件初始化
        self.scanner = scanner or MarketScanner()

        if scan_symbols:
            # 过滤不安全的币种
            # ⚠️ 在受限网络下，Scanner 可能会失败。为了稳定性，我们优先尝试 Scan，失败则Fallback
            try:
                self.safe_symbols = self.scanner.scan_opportunities(symbols)
            except Exception as e:
                logger.warning(f"⚠️ Scanner failed ({e}), using provided symbols.")
                self.safe_symbols = []
        else:
            self.safe_symbols = list(symbols)

        if not self.safe_symbols:
            logger.warning("⚠️ No safe symbols found or Scanner failed! Using provided symbols only.")
            self.safe_symbols = list(symbols)
            
        print(f"✅ Safe Symbols to MM: {self.safe_symbols}")
        
        # 通信层 (必须在 __init__ 中全部初始化)
        self.mexc_ws = mexc_ws or MexcWebsocketClient(self.safe_symbols)
        # 使用多源 Oracle (Binance -> OKX -> Bybit -> Gate)
        self.oracle = oracle or MultiSourceOracle(self.safe_symbols)
        
        # 算法模型 (为每个币种创建一个 AS 模型实例)
        self.algos: Dict[str, AvellanedaStoikovModel] = {}
        for sym in self.safe_symbols:
            # 参数优化（基于 MEXC 真实数据）
            # MEXC 实测价差: 0.001% - 0.016%
            # 目标: 0.02%（略宽于 MEXC，保留盈利空间）
            params = ASParams(
                gamma=0.1,       # 风险厌恶系数
                sigma=0.0004,    # 波动率参数 (0.0004 * 50 = 0.02%)
                k=0.5            # 流动性参数
            )
            self.algos[sym] = AvellanedaStoikovModel(params)
            
        # 4. 执行器 (Executor)
        self.executor = executor or HighFrequencyExecutor(dry_run=dry_run)
        
        # 5. 库存管理器 (Inventory Manager)
        self.inventory_manager = inventory_manager or InventoryManager(
            executor=self.executor,
            symbols=self.safe_symbols,
            dry_run=dry_run,
        )
        
        # 6. 日志与回调
        self.suppress_logs = False
        self.on_tick_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        
        # 7. 订单跟踪（用于避免频繁撤单）
        self.last_orders: Dict[str, Dict] = {}  # {symbol: {'bid': price, 'ask': price}}
        self._last_refresh_ts: Dict[str, float] = {}
        self._last_warn_ts: Dict[str, float] = {}
        
        # 8. 精度处理工具
        self.precision = precision or get_precision_helper()
        if not precision:
            try:
                self.precision.load_markets()
            except Exception as e:
                logger.warning(f"⚠️ 无法加载市场信息: {e}")
        
        # 9. 订单监控器（仅实盘模式）
        self.order_monitor = None
        if not dry_run:
            self.order_monitor = OrderMonitor(self.executor.exchange, self.inventory_manager)
            # 设置成交回调
            self.order_monitor.on_order_filled = self.on_order_filled
            # 将监控器传递给executor
            self.executor.order_monitor = self.order_monitor

        # 10. 熔断器 (Circuit Breaker)
        self.circuit_breaker = circuit_breaker or CircuitBreaker(initial_capital=self.inventory_manager.usdt_balance or 100.0)
        
    async def fetch_account_balances(self):
        """获取账户余额（从InventoryManager缓存获取）"""
        if self.dry_run:
            return {'USDT': 100.0}
        
        # 直接从InventoryManager获取最新状态 (WebSocket实时更新)
        stats = self.inventory_manager.get_statistics()
        result = {'USDT': stats.get('usdt_balance', 0.0)}
        
        # 提取各币种余额
        positions = stats.get('positions', {})
        for sym in self.safe_symbols:
            coin = sym.split('/')[0]
            if sym in positions:
                result[coin] = positions[sym]['quantity']
            else:
                result[coin] = 0.0
                
        return result
    
    def calculate_order_size(self, symbol: str, mid_price: float) -> float:
        """
        计算订单数量（基于余额和风险暴露）
        
        Args:
            symbol: 交易对
            mid_price: 当前市场价格
            
        Returns:
            订单数量（基础货币），已处理精度
        """
        # 获取USDT余额
        usdt_balance = float(self.inventory_manager.usdt_balance or 0.0)
        if usdt_balance <= 0 or mid_price <= 0:
            return 0.0
        
        # 单个订单最大使用 5% 的USDT余额
        max_order_value = usdt_balance * 0.05
        
        # 根据价格计算数量
        quantity = max_order_value / mid_price
        
        # 获取最小订单量
        min_quantity = self.precision.get_min_order_size(symbol)
        
        # 确保不小于最小订单量
        quantity = max(quantity, min_quantity * 1.1)  # 留10%余量

        # 最小成交额校验：如果交易所 min_cost 比 5% 额度还大，则直接跳过避免无意义报错
        is_valid, msg = self.precision.validate_order(symbol, mid_price, quantity)
        if not is_valid and "订单价值太小" in msg:
            try:
                market_min_cost = float(getattr(self.precision, "get_min_cost")(symbol))  # type: ignore[misc]
            except Exception:
                market_min_cost = 0.0

            if market_min_cost > 0:
                needed_qty = market_min_cost / mid_price
                if (needed_qty * mid_price) > max_order_value:
                    return 0.0
                quantity = max(quantity, needed_qty)
        
        # 精度处理：舍入到交易所允许的精度
        quantity = self.precision.round_amount(symbol, quantity)

        # 防止数量为0（精度舍入后）
        if quantity <= 0:
            return 0.0
        
        return quantity
    
    async def refresh_orders(self, symbol: str, bid: float, ask: float):
        """
        刷新订单：撤销旧订单并下新订单
        
        优化：仅当价格变化超过阈值时才刷新，避免频繁撤单
        
        Args:
            symbol: 交易对
            bid: 买单价格
            ask: 卖单价格
        """
        # 最小刷新节流：避免撤单风暴/限频
        now = self._now()
        last_refresh = self._last_refresh_ts.get(symbol, 0.0)
        if now - last_refresh < self.config.min_refresh_interval_s:
            return

        # 检查是否需要刷新（价格变化超过阈值）
        should_refresh = symbol not in self.last_orders
        if not should_refresh:
            last_bid = self.last_orders[symbol]['bid']
            last_ask = self.last_orders[symbol]['ask']
            bid_change = abs(bid - last_bid) / last_bid if last_bid > 0 else 1.0
            ask_change = abs(ask - last_ask) / last_ask if last_ask > 0 else 1.0
            if bid_change > self.config.refresh_threshold or ask_change > self.config.refresh_threshold:
                should_refresh = True
        
        if not should_refresh:
            return  # 不需要刷新

        # 1. 计算订单数量（余额/精度校验后可能为0）
        mid_price = (bid + ask) / 2
        quantity = self.calculate_order_size(symbol, mid_price)
        if quantity <= 0:
            if symbol in self.last_orders:
                await self.executor.cancel_all_orders(symbol)
                self.last_orders.pop(symbol, None)
            return

        # 2. 撤销所有旧订单
        await self.executor.cancel_all_orders(symbol)

        # 3. 下新订单
        await self.executor.place_orders(symbol, bid, ask, quantity)

        # 4. 记录本次订单
        self.last_orders[symbol] = {'bid': bid, 'ask': ask}
        self._last_refresh_ts[symbol] = now
            
    async def start(self):
        """启动引擎"""
        self.running = True
        logger.info(f"🚀 Starting Market Maker Engine [LIVE={not self.dry_run}]")
        
        # 实盘初始化
        if not self.dry_run:
            logger.warning("⚠️ LIVE TRADING ENABLED! Initialization in 3s...")
            await asyncio.sleep(3)
            await self.executor.initialize()
            # 获取初始库存
            await self.inventory_manager.update_from_exchange()
            logger.info(f"💰 Initial inventory: {self.inventory_manager.get_statistics()}")
        
        # 启动数据源（MEXC WS + Oracle）
        logger.info("📡 Starting data sources...")
        data_tasks = [
            asyncio.create_task(self.mexc_ws.connect()),
            asyncio.create_task(self.oracle.start()),
            # 如果是实盘，启动库存WebSocket监控
            asyncio.create_task(self.inventory_manager.start_monitoring()) if not self.dry_run else asyncio.create_task(asyncio.sleep(0)),
        ]
        
        # 等待数据源初始化
        logger.info("⏳ Waiting for data sources to initialize...")
        await asyncio.sleep(3)
        
        # 等待Oracle有数据（最多10秒）
        max_wait = 10
        oracle_ready = False
        for i in range(max_wait):
            for symbol in self.safe_symbols:
                if self.oracle.get_price(symbol):
                    oracle_ready = True
                    break
            
            if oracle_ready:
                logger.info(f"✅ Oracle ready after {i+3}s")
                break
                
            await asyncio.sleep(1)
        
        if not oracle_ready:
            logger.warning("⚠️ Oracle not ready after 13s, starting anyway...")
        
        # 等待MEXC WebSocket数据就绪（最多10秒）
        mexc_ready = False
        for i in range(10):
            if self.mexc_ws.is_data_ready():
                mexc_ready = True
                logger.info(f"✅ MEXC data ready after {i}s")
                break
            await asyncio.sleep(1)
        
        if not mexc_ready:
            logger.warning("⚠️ MEXC data not ready after 10s, starting anyway...")
        
        # 现在启动策略循环
        logger.info("🚀 Starting strategy loop...")
        strategy_task = asyncio.create_task(self.strategy_loop())
        
        # 合并所有任务
        tasks = data_tasks + [strategy_task]
        
        # 实盘模式：启动订单监控
        if not self.dry_run and self.order_monitor:
            tasks.append(asyncio.create_task(self.order_monitor.start(use_websocket=False)))
            logger.info("📡 订单监控器已启动")
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("🛑 Engine stopping...")
        finally:
            self.running = False
            # Cancel all tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            
            # Wait briefly for tasks to clean up
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except:
                pass
                
            # 显式释放资源 (解决 Unclosed client session)
            if self.oracle:
                await self.oracle.close()
            if self.executor:
                await self.executor.close()
                
            logger.info("✅ Engine stopped.")

    async def strategy_loop(self):
        """主策略循环 (High Frequency Loop)"""
        while self.running:
            try:
                for symbol in self.safe_symbols:
                    if not self.running:
                        break
                    try:
                        await self.on_tick(symbol)
                    except Exception as tick_err:
                        logger.error(f"⚠️ Error in on_tick({symbol}): {tick_err}")
                
                # 极高频: 100ms 循环
                await asyncio.sleep(0.1)
            except (asyncio.CancelledError, KeyboardInterrupt):
                break
            except Exception as e:
                logger.error(f"❌ Critical Strategy Loop Error: {e}")
                await asyncio.sleep(1) # 防止快速循环报错

    async def on_tick(self, symbol: str):
        """处理由于时间流逝或数据更新触发的 Tick"""
        
        # DEBUG: 记录on_tick被调用
        if not hasattr(self, '_tick_count'):
            self._tick_count = {}
        self._tick_count[symbol] = self._tick_count.get(symbol, 0) + 1
        
        # 每10次tick输出一次日志
        if self._tick_count[symbol] % 10 == 1:
            logger.debug(f"🔄 on_tick called for {symbol} (count: {self._tick_count[symbol]})")
        
        # 1) 取数：订单簿必须新鲜
        local_ob = self.mexc_ws.get_orderbook(symbol)
        if not local_ob:
            self._warn_rate_limited(symbol, "mexc_ob", f"⚠️ {symbol} MEXC订单簿数据未就绪")
            return
        if not local_ob.get("bids") or not local_ob.get("asks"):
            return

        ob_age = self.mexc_ws.get_data_age(symbol)
        if ob_age > self.config.ob_stale_s:
            self._warn_rate_limited(symbol, "mexc_stale", f"⚠️ {symbol} MEXC 订单簿数据过旧: {ob_age:.1f}s")
            return

        mexc_mid = (float(local_ob["bids"][0][0]) + float(local_ob["asks"][0][0])) / 2

        # 2) 参考价：优先 Oracle，可按配置回退到 MEXC mid（默认只用于显示/不用于实盘）
        ref_source = "oracle"
        oracle_data = self.oracle.get_price(symbol)
        if oracle_data:
            oracle_age = self._now() - float(oracle_data.get("ts") or 0.0)
            if oracle_age <= self.config.oracle_stale_s:
                ref_price = float(oracle_data["mid"])
            else:
                oracle_data = None
        if not oracle_data:
            if self.config.ref_price_source in {"oracle_then_mexc", "mexc"}:
                ref_source = "mexc"
                ref_price = mexc_mid
            else:
                self._warn_rate_limited(symbol, "oracle", f"⚠️ {symbol} Oracle 数据未就绪/过旧")
                return
        
        # 1.5 获取波动率和订单簿深度
        mexc_symbol = symbol.replace('/', '')
        volatility = self.mexc_ws.calculate_volatility(mexc_symbol)
        
        # 计算订单簿深度指标（基于前5档深度）
        orderbook_depth = 1.0  # 默认值
        if 'bids' in local_ob and 'asks' in local_ob:
            bid_depth = sum([bid[1] for bid in local_ob['bids'][:5]]) if local_ob['bids'] else 0
            ask_depth = sum([ask[1] for ask in local_ob['asks'][:5]]) if local_ob['asks'] else 0
            total_depth = (bid_depth + ask_depth) / 2
            # 归一化：假设正常深度为100个币
            orderbook_depth = max(0.5, min(2.0, total_depth / 100.0))
            
        # 2. 计算 AS 报价（使用自适应价差）
        algo = self.algos[symbol]
        # 使用库存管理器获取库存偏离度
        curr_inventory = self.inventory_manager.get_inventory_skew(symbol)
        
        optimal_bid, optimal_ask = algo.calculate_quotes(
            mid_price=ref_price,
            inventory_q=curr_inventory,
            volatility=volatility,
            orderbook_depth=orderbook_depth
        )
        
        # 3. 安全熔断校验 + 精度处理
        # 确保我们的报价没有偏离 Oracle 太多
        safe_bid_max = ref_price * 1.0005 # +0.05%
        safe_ask_min = ref_price * 0.9995 # -0.05%
        
        final_bid = min(optimal_bid, safe_bid_max)
        final_ask = max(optimal_ask, safe_ask_min)
        
        # 精度处理：舍入到交易所允许的精度
        final_bid = self.precision.round_price(symbol, final_bid)
        final_ask = self.precision.round_price(symbol, final_ask)

        # 防止 bid >= ask（精度舍入/保护逻辑可能导致交叉）
        if final_bid >= final_ask:
            tick = self.precision.get_price_tick(symbol)
            final_bid = self.precision.round_price(symbol, ref_price - tick)
            final_ask = self.precision.round_price(symbol, ref_price + tick)
            if final_bid >= final_ask:
                return
        
        # 3) 风控：仅当数据源足够新鲜时才更新心跳
        self.circuit_breaker.update_heartbeat()
        
        # 检查网络连接
        if not self.circuit_breaker.check_network():
            logger.error(f"🛑 熔断触发: {self.circuit_breaker.last_trigger_reason}")
            return

        # 检查价格偏差
        if not self.circuit_breaker.check_price_deviation(local_ob['bids'][0][0], ref_price):
             logger.error(f"🛑 熔断触发: {self.circuit_breaker.last_trigger_reason}")
             return

        # 检查PnL (仅实盘)
        if not self.dry_run and self.order_monitor:
            current_pnl = self.order_monitor.get_session_pnl()
            if not self.circuit_breaker.check_pnl(current_pnl):
                logger.error(f"🛑 熔断触发: {self.circuit_breaker.last_trigger_reason}")
                self.stop()
                return

        # 4. 风险检查
        risk_check = self.inventory_manager.check_risk_limits(symbol, ref_price)
        if not (risk_check['can_buy'] and risk_check['can_sell']):
            # 关键：触发风险限制时，撤掉旧挂单，避免继续扩大风险暴露
            if symbol in self.last_orders and not self.dry_run:
                await self.executor.cancel_all_orders(symbol)
                self.last_orders.pop(symbol, None)
            logger.warning(f"⚠️ {symbol} 风险限制: {risk_check['reason']}")
            return
        
        # 5. 计算价差
        spread = (final_ask - final_bid) / ref_price * 100
        
        # 6. 获取MEXC本地订单簿数据（用于对比）
        mexc_bid = local_ob['bids'][0][0] if local_ob.get('bids') else 0
        mexc_ask = local_ob['asks'][0][0] if local_ob.get('asks') else 0
        mexc_spread = 0
        if mexc_bid > 0 and mexc_ask > 0:
            mexc_spread = (mexc_ask - mexc_bid) / ref_price * 100

        # 4) 可选刷量门控：市场价差不足直接不挂（避免无意义刷单/负期望）
        if self.config.volume_mode_enabled and mexc_spread < self.config.min_market_spread_pct:
            return
        
        # 7. 上报状态 (Observer Pattern)
        stats = {
            'symbol': symbol,
            'ref_price': ref_price,
            'ref_source': ref_source,
            'inventory': curr_inventory,
            'bid': final_bid,
            'ask': final_ask,
            'spread_pct': spread,
            'can_buy': risk_check['can_buy'],
            'can_sell': risk_check['can_sell'],
            # MEXC本地数据
            'mexc_bid': mexc_bid,
            'mexc_ask': mexc_ask,
            'mexc_spread': mexc_spread,
            'timestamp': self._now()
        }
        
        # 将数据推送到回调函数 (如果存在)
        if hasattr(self, 'on_tick_callback') and self.on_tick_callback:
            self.on_tick_callback(stats)
            
        # 仅在没有回调时才打印日志 (避免 Dashboard 显示冲突)
        elif not getattr(self, 'suppress_logs', False):
            import random
            if random.random() < 0.2:
                print(f"📊 {symbol:<8} | Ref: ${ref_price:.4f} | Inv: {curr_inventory:>4} | "
                      f"Qt: {final_bid:.4f}/{final_ask:.4f} | Spr: {spread:.3f}%")
        
        # 8. 执行订单（实盘模式）
        if not self.dry_run:
            # 默认不允许在没有 Oracle 的情况下实盘交易（除非显式开启）
            if ref_source != "oracle" and not self.config.allow_live_without_oracle:
                return
            # 可选：刷量模式抢队列（默认关闭，稳定优先）
            if self.config.volume_mode_enabled and self.config.step_in_ticks > 0 and mexc_bid > 0 and mexc_ask > 0:
                tick = self.precision.get_price_tick(symbol)
                stepped_bid = self.precision.round_price(symbol, mexc_bid + tick * self.config.step_in_ticks)
                stepped_ask = self.precision.round_price(symbol, mexc_ask - tick * self.config.step_in_ticks)
                if stepped_bid < stepped_ask:
                    final_bid, final_ask = stepped_bid, stepped_ask
            await self.refresh_orders(symbol, final_bid, final_ask)

    def _warn_rate_limited(self, symbol: str, key: str, msg: str):
        now = self._now()
        k = f"{symbol}:{key}"
        last = self._last_warn_ts.get(k, 0.0)
        if now - last >= self.config.warn_every_s:
            logger.warning(msg)
            self._last_warn_ts[k] = now

    async def on_order_filled(self, order: Dict):
        """订单成交回调处理"""
        symbol = order['symbol']
        side = order['side']
        filled = order['filled']
        price = order['price']
        
        logger.info(f"🎉 订单成交: {symbol} {side} {filled}@{price}")
        
        # 统计信息已由 OrderMonitor 处理，这里可以添加额外逻辑
        # 例如：Telegram通知、盈亏记录等

    def stop(self):
        self.running = False
        self.mexc_ws.running = False
        self.oracle.running = False
        # 停止订单监控
        if self.order_monitor:
            self.order_monitor.stop()


# ===== 运行入口 =====
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO, # 调整为 INFO 以便观察
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 目标币种
    target_symbols = ['ETH/USDT', 'SOL/USDT', 'PEPE/USDT']
    
    engine = MarketMakerEngine(target_symbols, dry_run=True)

    
    try:
        asyncio.run(engine.start())
    except KeyboardInterrupt:
        engine.stop()
        print("\n👋 Bye!")
