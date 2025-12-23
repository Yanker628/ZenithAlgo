import pytest
import time
from strategies.market_maker.core.circuit_breaker import CircuitBreaker

@pytest.fixture
def circuit_breaker():
    # Initialize with 1000 USDT capital
    return CircuitBreaker(initial_capital=1000.0)

def test_pnl_circuit_breaker(circuit_breaker):
    """Test detailed PnL circuit breaker logic"""
    # Simulate small loss, should be safe
    assert circuit_breaker.check_pnl(current_pnl=-10.0) == True # -1%
    
    # Simulate > 2% loss
    assert circuit_breaker.check_pnl(current_pnl=-21.0) == False # -2.1%
    assert "PnL Loss > 2.0%" in circuit_breaker.last_trigger_reason

def test_price_deviation(circuit_breaker):
    """Test price deviation check"""
    # 1% deviation allowed
    # Base: 100, Oracle: 100.5 -> 0.5% diff -> OK
    assert circuit_breaker.check_price_deviation(market_price=100, oracle_price=100.5) == True
    
    # Base: 100, Oracle: 102.0 -> 2.0% diff -> Fail
    assert circuit_breaker.check_price_deviation(market_price=100, oracle_price=102.0) == False
    assert "Price Deviation > 1.0%" in circuit_breaker.last_trigger_reason

def test_network_monitor(circuit_breaker):
    """Test network heartbeat monitor"""
    circuit_breaker.update_heartbeat()
    assert circuit_breaker.check_network() == True
    
    # Simulate time jump > 10s
    circuit_breaker.last_heartbeat = time.time() - 11
    assert circuit_breaker.check_network() == False
    assert "Network Timeout" in circuit_breaker.last_trigger_reason
