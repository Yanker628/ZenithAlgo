import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from strategies.market_maker.core.algo import AvellanedaStoikovModel, ASParams
from strategies.market_maker.core.inventory_manager import InventoryManager


class TestAvellanedaStoikovAlgorithm:
    """测试AS算法的价差计算"""
    
    def test_calculate_adaptive_spread_basic(self):
        """测试基础自适应价差计算"""
        params = ASParams(gamma=0.1, sigma=0.0004, k=0.5)
        model = AvellanedaStoikovModel(params)
        
        mid_price = 100.0
        inventory_q = 0.0  # 中性库存
        volatility = 0.01  # 1%波动率
        orderbook_depth = 1.0  # 正常深度
        
        half_spread = model.calculate_adaptive_spread(
            mid_price=mid_price,
            inventory_q=inventory_q,
            volatility=volatility,
            orderbook_depth=orderbook_depth
        )
        
        # 半价差应该在合理范围内
        assert half_spread > 0
        assert half_spread < mid_price * 0.01  # 小于1%
    
    def test_calculate_adaptive_spread_with_inventory(self):
        """测试库存偏离时的价差调整"""
        params = ASParams(gamma=0.1, sigma=0.0004, k=0.5)
        model = AvellanedaStoikovModel(params)
        
        mid_price = 100.0
        volatility = 0.002  # 使用更低的波动率避免触及上限
        orderbook_depth = 1.0
        
        # 无库存偏离
        spread_neutral = model.calculate_adaptive_spread(
            mid_price, 0.0, volatility, orderbook_depth
        )
        
        # 有库存偏离（使用较小的值避免触及上限）
        spread_with_inventory = model.calculate_adaptive_spread(
            mid_price, 3.0, volatility, orderbook_depth
        )
        
        # 库存偏离时价差应该更宽
        assert spread_with_inventory > spread_neutral
        # 验证调整幅度合理（约15%增加）
        assert spread_with_inventory / spread_neutral > 1.1
    
    def test_calculate_adaptive_spread_with_volatility(self):
        """测试波动率对价差的影响"""
        params = ASParams(gamma=0.1, sigma=0.0004, k=0.5)
        model = AvellanedaStoikovModel(params)
        
        mid_price = 100.0
        inventory_q = 0.0
        orderbook_depth = 1.0
        
        # 低波动率
        spread_low_vol = model.calculate_adaptive_spread(
            mid_price, inventory_q, 0.001, orderbook_depth
        )
        
        # 中等波动率
        spread_high_vol = model.calculate_adaptive_spread(
            mid_price, inventory_q, 0.003, orderbook_depth
        )
        
        # 高波动率时价差应该更宽
        assert spread_high_vol > spread_low_vol
    
    def test_calculate_quotes_integration(self):
        """测试完整的报价计算"""
        params = ASParams(gamma=0.1, sigma=0.0004, k=0.5)
        model = AvellanedaStoikovModel(params)
        
        mid_price = 100.0
        inventory_q = 2.0  # 轻微多头
        volatility = 0.01
        orderbook_depth = 1.0
        
        bid, ask = model.calculate_quotes(
            mid_price=mid_price,
            inventory_q=inventory_q,
            volatility=volatility,
            orderbook_depth=orderbook_depth
        )
        
        # 基本检查
        assert bid < mid_price < ask
        assert bid > 0
        assert ask > 0
        
        # 库存偏离应该导致报价下移（促进卖出）
        reservation_price = (bid + ask) / 2
        assert reservation_price < mid_price


class TestInventoryManager:
    """测试库存管理器"""
    
    @pytest.fixture
    def mock_executor(self):
        """创建mock executor"""
        executor = Mock()
        executor.exchange = Mock()
        return executor
    
    @pytest.fixture
    def inventory_manager(self, mock_executor):
        """创建inventory manager实例"""
        symbols = ['BTC/USDT', 'ETH/USDT']
        return InventoryManager(executor=mock_executor, symbols=symbols, dry_run=True)
    
    @pytest.mark.asyncio
    async def test_fetch_balances_dry_run(self, inventory_manager):
        """测试dry run模式下的余额获取"""
        balances = await inventory_manager.fetch_balances()
        
        assert 'USDT' in balances
        assert balances['USDT'] == 1000.0
        assert 'BTC' in balances
        assert 'ETH' in balances
    
    def test_update_inventory_buy(self, inventory_manager):
        """测试买入后的库存更新"""
        symbol = 'BTC/USDT'
        initial = inventory_manager.inventory[symbol]
        
        inventory_manager.update_inventory(symbol, 'buy', 0.5)
        
        assert inventory_manager.inventory[symbol] == initial + 0.5
    
    def test_update_inventory_sell(self, inventory_manager):
        """测试卖出后的库存更新"""
        symbol = 'BTC/USDT'
        inventory_manager.inventory[symbol] = 1.0
        
        inventory_manager.update_inventory(symbol, 'sell', 0.3)
        
        assert inventory_manager.inventory[symbol] == 0.7
    
    def test_get_inventory_skew(self, inventory_manager):
        """测试库存偏离度计算"""
        symbol = 'BTC/USDT'
        inventory_manager.inventory[symbol] = 5.0
        inventory_manager.target_inventory[symbol] = 2.0
        
        skew = inventory_manager.get_inventory_skew(symbol)
        
        assert skew == 3.0
    
    def test_check_risk_limits_normal(self, inventory_manager):
        """测试正常情况下的风险检查"""
        symbol = 'BTC/USDT'
        mid_price = 50000.0
        inventory_manager.inventory[symbol] = 0.05  # $2500价值
        
        risk_check = inventory_manager.check_risk_limits(symbol, mid_price)
        
        assert risk_check['can_buy'] == True
        assert risk_check['can_sell'] == True
    
    def test_check_risk_limits_exceed_position_value(self, inventory_manager):
        """测试超过持仓价值限制"""
        symbol = 'BTC/USDT'
        mid_price = 50000.0
        inventory_manager.inventory[symbol] = 0.3  # $15000价值，超过默认$10000限制
        
        risk_check = inventory_manager.check_risk_limits(symbol, mid_price)
        
        assert risk_check['can_buy'] == False
        assert 'reason' in risk_check
    
    def test_check_risk_limits_exceed_skew(self, inventory_manager):
        """测试超过库存偏离限制"""
        symbol = 'BTC/USDT'
        mid_price = 50000.0
        inventory_manager.inventory[symbol] = 15.0  # 偏离度15，超过默认10的限制
        inventory_manager.target_inventory[symbol] = 0.0
        
        risk_check = inventory_manager.check_risk_limits(symbol, mid_price)
        
        assert risk_check['can_buy'] == False


class TestOrderExecutionLogic:
    """测试订单执行逻辑（集成测试）"""
    
    @pytest.mark.asyncio
    async def test_calculate_order_size(self):
        """测试订单数量计算"""
        from strategies.market_maker.main import MarketMakerEngine
        
        engine = MarketMakerEngine(['BTC/USDT'], dry_run=True)
        engine.inventory_manager.usdt_balance = 1000.0
        
        mid_price = 50000.0
        quantity = engine.calculate_order_size('BTC/USDT', mid_price)
        
        # 5%余额 = $50，约0.001 BTC
        assert quantity > 0
        # 最小$10等值 = 0.0002 BTC
        assert quantity >= 10 / mid_price


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
