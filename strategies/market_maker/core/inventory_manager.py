import asyncio
import logging
from typing import Dict, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

class InventoryManager:
    """
    库存管理器 (Inventory Manager)
    
    职责：
    1. 从交易所获取实时余额
    2. 跟踪每个交易对的库存状态
    3. 计算库存偏离度（相对目标中性仓位）
    4. 提供库存风险评估
    """
    
    def __init__(self, executor, symbols: list, dry_run: bool = True):
        """
        Args:
            executor: HighFrequencyExecutor实例（用于API调用）
            symbols: 交易对列表（如 ['BTC/USDT', 'ETH/USDT']）
            dry_run: 是否为模拟模式
        """
        self.executor = executor
        self.symbols = symbols
        self.dry_run = dry_run
        
        # 库存状态
        self.inventory: Dict[str, float] = {}  # {symbol: quantity}
        self.target_inventory: Dict[str, float] = {}  # 目标库存（中性仓位）
        
        # USDT余额
        self.usdt_balance: float = 0.0
        
        # 风险限制配置
        self.max_inventory_ratio = 0.8  # 最大库存比例（相对总资金）
        self.max_position_value = 10000  # 单个交易对最大持仓价值（USDT）
        
        # 初始化所有交易对的库存为0
        for symbol in symbols:
            self.inventory[symbol] = 0.0
            self.target_inventory[symbol] = 0.0
    
    async def fetch_balances(self) -> Dict[str, float]:
        """
        从交易所获取实时余额
        
        Returns:
            {coin: balance} 字典
        """
        if self.dry_run:
            # 模拟模式：返回mock数据
            result = {'USDT': 1000.0}
            for symbol in self.symbols:
                coin = symbol.split('/')[0]
                result[coin] = 0.0
            return result
        
        try:
            # 实盘模式：调用交易所API（同步方法）
            loop = asyncio.get_event_loop()
            balance = await loop.run_in_executor(
                None,
                self.executor.exchange.fetch_balance
            )
            result: Dict[str, float] = {}

            free = balance.get("free") if isinstance(balance, dict) else None
            total = balance.get("total") if isinstance(balance, dict) else None

            if isinstance(free, dict):
                for currency, amount in free.items():
                    try:
                        amount_f = float(amount or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if amount_f > 0:
                        result[currency] = amount_f

            if not result:
                for currency, data in (balance or {}).items():
                    if currency in {"info", "free", "used", "total", "timestamp", "datetime"}:
                        continue
                    if isinstance(data, dict) and "free" in data:
                        try:
                            amount_f = float(data.get("free") or 0.0)
                        except (TypeError, ValueError):
                            continue
                        if amount_f > 0:
                            result[currency] = amount_f

            if "USDT" not in result:
                usdt_free = 0.0
                if isinstance(free, dict):
                    usdt_free = float(free.get("USDT") or 0.0)
                elif isinstance(balance, dict) and isinstance(balance.get("USDT"), dict):
                    usdt_free = float(balance["USDT"].get("free") or 0.0)
                result["USDT"] = usdt_free

            if isinstance(total, dict):
                for currency, amount in total.items():
                    if currency in result:
                        continue
                    try:
                        amount_f = float(amount or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if amount_f > 0:
                        result[currency] = amount_f

            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch balances: {e}")
            return {}
    
    async def update_from_exchange(self):
        """从交易所更新库存数据"""
        balances = await self.fetch_balances()
        
        if balances:
            self.usdt_balance = balances.get('USDT', 0.0)
            
            for symbol in self.symbols:
                coin = symbol.split('/')[0]
                self.inventory[symbol] = balances.get(coin, 0.0)
    
    def update_inventory(self, symbol: str, side: str, quantity: float):
        """
        手动更新库存（在订单成交后调用）
        
        Args:
            symbol: 交易对
            side: 'buy' 或 'sell'
            quantity: 成交数量（基础货币）
        """
        if symbol not in self.inventory:
            logger.warning(f"⚠️ Symbol {symbol} not in inventory tracking")
            return
        
        if side == 'buy':
            self.inventory[symbol] += quantity
        elif side == 'sell':
            self.inventory[symbol] -= quantity
        else:
            logger.error(f"❌ Invalid side: {side}")

    def apply_fill(self, symbol: str, side: str, quantity: float, price: float, fee_usdt: float = 0.0):
        """
        Apply a fill locally: update both base inventory and USDT balance.

        Note: in LIVE mode, balances will eventually be reconciled by exchange snapshots/WS,
        but applying fills locally improves responsiveness and offline simulation accuracy.
        """
        qty = float(quantity)
        px = float(price)
        fee = float(fee_usdt or 0.0)
        if qty <= 0 or px <= 0:
            return

        notional = qty * px
        if side == 'buy':
            self.usdt_balance -= (notional + fee)
            self.inventory[symbol] = self.inventory.get(symbol, 0.0) + qty
        elif side == 'sell':
            self.usdt_balance += (notional - fee)
            self.inventory[symbol] = self.inventory.get(symbol, 0.0) - qty
        else:
            logger.error(f"❌ Invalid side: {side}")
    
    def get_inventory_skew(self, symbol: str) -> float:
        """
        计算库存偏离度（相对目标中性仓位）
        
        Args:
            symbol: 交易对
            
        Returns:
            库存偏离量（以币为单位），正数表示多头，负数表示空头
        """
        current = self.inventory.get(symbol, 0.0)
        target = self.target_inventory.get(symbol, 0.0)
        return current - target
    
    def check_risk_limits(self, symbol: str, mid_price: float) -> dict:
        """
        检查是否超过风险限制
        
        Args:
            symbol: 交易对
            mid_price: 当前市场价格
            
        Returns:
            {
                'can_buy': bool,
                'can_sell': bool,
                'reason': str  # 如果被限制，说明原因
            }
        """
        result = {
            'can_buy': True,
            'can_sell': True,
            'reason': ''
        }
        
        current_qty = self.inventory.get(symbol, 0.0)
        position_value = abs(current_qty * mid_price)
        
        # 检查单个交易对持仓价值
        if position_value > self.max_position_value:
            if current_qty > 0:
                result['can_buy'] = False
                result['reason'] = f"持仓价值超限 ({position_value:.2f} > {self.max_position_value})"
            else:
                result['can_sell'] = False
                result['reason'] = f"空头持仓价值超限 ({position_value:.2f} > {self.max_position_value})"
        
        # 检查库存偏离度
        skew = self.get_inventory_skew(symbol)
        max_skew = 10.0  # 最大允许偏离10个币
        
        if skew > max_skew:
            result['can_buy'] = False
            result['reason'] = f"库存偏离过大 (skew={skew:.2f} > {max_skew})"
        elif skew < -max_skew:
            result['can_sell'] = False
            result['reason'] = f"库存偏离过大 (skew={skew:.2f} < -{max_skew})"
        
        return result
    
    def get_statistics(self) -> Dict:
        """
        获取库存统计信息
        
        Returns:
            包含统计数据的字典
        """
        stats = {
            'usdt_balance': self.usdt_balance,
            'positions': {}
        }
        
        for symbol in self.symbols:
            qty = self.inventory.get(symbol, 0.0)
            skew = self.get_inventory_skew(symbol)
            
            stats['positions'][symbol] = {
                'quantity': qty,
                'skew': skew,
                'target': self.target_inventory.get(symbol, 0.0)
            }
        
        return stats
    
    def set_target_inventory(self, symbol: str, target: float):
        """
        设置目标库存（中性仓位）
        
        Args:
            symbol: 交易对
            target: 目标库存量
        """
        self.target_inventory[symbol] = target
        logger.info(f"📌 Set target inventory for {symbol}: {target}")

    async def on_balance_update(self, data: Dict):
        """
        处理WebSocket余额更新
        
        Args:
            data: {
                'asset': 'SOL',
                'free': 12.34,
                'locked': 0.5,
                'timestamp': 1234567890
            }
        """
        asset = data.get('asset')
        free = data.get('free')
        
        if asset == 'USDT':
            # 更新USDT余额
            self.usdt_balance = float(free)
        else:
            # 查找对应的交易对
            # 目前简单假设 coin -> coin/USDT
            # TODO: 支持多交易对映射
            for symbol in self.symbols:
                if symbol.startswith(f"{asset}/"):
                    self.inventory[symbol] = float(free)
                    break
        
        # logger.debug(f"⚡ Balance update: {asset} = {free}")

    async def calibrate(self):
        """
        强制校准库存（REST API）
        用于定期纠正WebSocket可能的丢包或漂移
        """
        try:
            # logger.info("⚖️ Starting inventory calibration...")
            await self.update_from_exchange()
            # logger.info("✅ Inventory calibration complete")
        except Exception as e:
            logger.error(f"❌ Calibration failed: {e}")

    async def start_monitoring(self):
        """启动WebSocket余额监控"""
        logger.info("📡 Starting Inventory WebSocket monitoring...")
        while True:
            try:
                # 使用CCXT的watch_balance
                if hasattr(self.executor.exchange, 'watch_balance'):
                    balance = await self.executor.exchange.watch_balance()
                    await self.on_balance_update_ccxt(balance)
                else:
                    logger.warning("⚠️ Exchange does not support watch_balance, falling back to REST")
                    await asyncio.sleep(60)
                    await self.calibrate()
                    
            except Exception as e:
                logger.error(f"❌ Inventory WS error: {e}")
                await asyncio.sleep(5)

    async def on_balance_update_ccxt(self, balance: Dict):
        """处理CCXT返回的标准余额格式"""
        # CCXT returns: {'USDT': {'free': 100, ...}, 'SOL': ...}
        
        # update USDT
        if 'USDT' in balance:
            self.usdt_balance = balance['USDT']['free']
            
        # update symbols
        for symbol in self.symbols:
            coin = symbol.split('/')[0]
            if coin in balance:
                self.inventory[symbol] = balance[coin]['free']
                
        # logger.debug(f"⚡ Balance updated via WS")
