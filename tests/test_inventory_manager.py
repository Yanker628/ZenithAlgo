import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from strategies.market_maker.core.inventory_manager import InventoryManager

@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.exchange = MagicMock()
    # Mock fetch_balance
    executor.exchange.fetch_balance = MagicMock(return_value={
        'USDT': {'free': 1000.0, 'used': 0.0, 'total': 1000.0},
        'SOL': {'free': 10.0, 'used': 0.0, 'total': 10.0}
    })
    return executor

@pytest.fixture
def inventory_manager(mock_executor):
    # Initialize with dry_run=False to test real logic paths (mocked exchange)
    im = InventoryManager(mock_executor, ['SOL/USDT'], dry_run=False)
    return im

@pytest.mark.asyncio
async def test_initial_sync(inventory_manager, mock_executor):
    """Test initial balance sync via REST"""
    await inventory_manager.update_from_exchange()
    
    assert inventory_manager.usdt_balance == 1000.0
    assert inventory_manager.inventory['SOL/USDT'] == 10.0
    assert mock_executor.exchange.fetch_balance.called

@pytest.mark.asyncio
async def test_websocket_update(inventory_manager):
    """Test handling of WebSocket balance updates"""
    # Simulate a WS update
    ws_data = {
        'asset': 'SOL',
        'free': 15.0,
        'locked': 0.0,
        'timestamp': 1234567890
    }
    
    # Manually trigger the handler (which we will implement)
    await inventory_manager.on_balance_update(ws_data)
    
    # Inventory should reflect the update
    assert inventory_manager.inventory['SOL/USDT'] == 15.0

@pytest.mark.asyncio
async def test_websocket_usdt_update(inventory_manager):
    """Test handling of WebSocket USDT balance updates"""
    ws_data = {
        'asset': 'USDT',
        'free': 2000.0,
        'locked': 0.0,
        'timestamp': 1234567890
    }
    
    await inventory_manager.on_balance_update(ws_data)
    
    assert inventory_manager.usdt_balance == 2000.0

@pytest.mark.asyncio
async def test_auto_calibration(inventory_manager, mock_executor):
    """Test automatic calibration via REST"""
    # Setup initial state
    inventory_manager.inventory['SOL/USDT'] = 10.0
    
    # Mock a different balance on exchange (drift)
    mock_executor.exchange.fetch_balance = MagicMock(return_value={
        'USDT': {'free': 1000.0},
        'SOL': {'free': 12.0} # Real balance is 12, but local is 10
    })
    
    # Trigger calibration
    await inventory_manager.calibrate()
    
    # Should be updated to 12
    assert inventory_manager.inventory['SOL/USDT'] == 12.0
