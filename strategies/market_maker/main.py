
import asyncio
import logging
import signal
import time
from typing import Dict, List

from strategies.market_maker.gateways.mexc_ws import MexcWebsocketClient
from strategies.market_maker.core.oracle import MultiSourceOracle
from strategies.market_maker.core.algo import AvellanedaStoikovModel, ASParams
from strategies.market_maker.core.scanner import MarketScanner
from strategies.market_maker.core.executor import HighFrequencyExecutor

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
    
    def __init__(self, symbols: List[str], dry_run: bool = True):
        self.symbols = symbols
        self.dry_run = dry_run
        self.running = False
        
        # 1. 组件初始化
        self.scanner = MarketScanner()
        
        # 过滤不安全的币种
        # ⚠️ 在受限网络下，Scanner 可能会失败。为了稳定性，我们优先尝试 Scan，失败则Fallback
        try:
            self.safe_symbols = self.scanner.scan_opportunities(symbols)
        except Exception as e:
            logger.warning(f"⚠️ Scanner failed ({e}), using default symbols.")
            self.safe_symbols = []
            
        if not self.safe_symbols:
            logger.warning("⚠️ No safe symbols found or Scanner failed! Using fallback list.")
            # Fallback 默认列表，防止系统崩溃
            self.safe_symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
            
        print(f"✅ Safe Symbols to MM: {self.safe_symbols}")
        
        # 通信层 (必须在 __init__ 中全部初始化)
        self.mexc_ws = MexcWebsocketClient(self.safe_symbols)
        # 使用多源 Oracle (Binance -> OKX -> Bybit -> Gate)
        self.oracle = MultiSourceOracle(self.safe_symbols)
        
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
            
        # 库存状态 (Mock)
        self.inventory: Dict[str, float] = {sym: 0.0 for sym in self.safe_symbols}
        
        # 4. 执行器 (Executor)
        self.executor = HighFrequencyExecutor(dry_run=dry_run)
        
        # 5. 日志与回调
        self.suppress_logs = False
        self.on_tick_callback = None
        
    async def fetch_account_balances(self):
        """获取账户余额（仅实盘模式）"""
        if self.dry_run:
            return {'USDT': 100.0}
        
        try:
            balance = await self.executor.exchange.fetch_balance()
            result = {'USDT': balance.get('USDT', {}).get('free', 0.0)}
            for sym in self.safe_symbols:
                coin = sym.split('/')[0]
                result[coin] = balance.get(coin, {}).get('free', 0.0)
            return result
        except:
            return {'USDT': 0.0}
            
    async def start(self):
        """启动引擎"""
        self.running = True
        logger.info(f"🚀 Starting Market Maker Engine [LIVE={not self.dry_run}]")
        
        # 实盘初始化
        if not self.dry_run:
            logger.warning("⚠️ LIVE TRADING ENABLED! Initialization in 3s...")
            await asyncio.sleep(3)
            await self.executor.initialize()
        
        # 启动后台任务
        tasks = [
            asyncio.create_task(self.mexc_ws.connect()),
            asyncio.create_task(self.oracle.connect()),
            asyncio.create_task(self.strategy_loop())
        ]
        
        # 等待初始化数据
        logger.info("⏳ Waiting for data streams warmup (5s)...")
        await asyncio.sleep(5)
        
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
                    await self.on_tick(symbol)
                    
                # 极高频: 100ms 循环
                await asyncio.sleep(0.1)
            except (asyncio.CancelledError, KeyboardInterrupt):
                break

    async def on_tick(self, symbol: str):
        """处理由于时间流逝或数据更新触发的 Tick"""
        
        # 1. 获取数据
        # Oracle Price (Multi-Source)
        oracle_data = self.oracle.get_price(symbol)
        if not oracle_data:
            return  # 数据未就绪（Engine刚启动时）
            
        ref_price = oracle_data['mid']
        
        # Mexc Local Orderbook
        local_ob = self.mexc_ws.get_orderbook(symbol)
        if not local_ob:
            return
        
        # 1.5 动态价差调整
        mexc_symbol = symbol.replace('/', '')
        volatility = self.mexc_ws.calculate_volatility(mexc_symbol)
        if volatility < 0.005:
            dynamic_sigma = 0.0002
        elif volatility < 0.02:
            dynamic_sigma = 0.0004
        else:
            dynamic_sigma = 0.001
        self.algos[symbol].params.sigma = dynamic_sigma
            
        # 2. 计算 AS 报价
        algo = self.algos[symbol]
        curr_inventory = self.inventory.get(symbol, 0)
        
        optimal_bid, optimal_ask = algo.calculate_quotes(ref_price, curr_inventory)
        
        # 3. 安全熔断校验 (Safety Check)
        # 确保我们的报价没有偏离 Oracle 太多
        safe_bid_max = ref_price * 1.0005 # +0.05%
        safe_ask_min = ref_price * 0.9995 # -0.05%
        
        final_bid = min(optimal_bid, safe_bid_max)
        final_ask = max(optimal_ask, safe_ask_min)
        
        # 4. 计算价差
        spread = (final_ask - final_bid) / ref_price * 100
        
        # 5. 上报状态 (Observer Pattern)
        stats = {
            'symbol': symbol,
            'ref_price': ref_price,
            'inventory': curr_inventory,
            'bid': final_bid,
            'ask': final_ask,
            'spread_pct': spread,
            'timestamp': time.time()
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
            
            if not self.dry_run:
                # TODO: Call OrderExecutor
                pass

    def stop(self):
        self.running = False
        self.mexc_ws.running = False
        self.oracle.running = False


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
