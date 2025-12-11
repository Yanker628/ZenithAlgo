from market.models import Position
from utils.pnl import estimate_pnl


def test_estimate_pnl_basic():
    positions = {
        "BTCUSDT": Position(symbol="BTCUSDT", qty=1.5, avg_price=100.0),
        "ETHUSDT": Position(symbol="ETHUSDT", qty=-2.0, avg_price=50.0),
    }
    last_prices = {"BTCUSDT": 110.0, "ETHUSDT": 40.0}
    pnl = estimate_pnl(positions, last_prices)
    # BTC: +15, ETH: +20 (空头价格下跌盈利)
    assert abs(pnl - 35.0) < 1e-9
