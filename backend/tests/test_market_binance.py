import os

import pytest

from zenith.data.client import BinanceMarketClient


@pytest.mark.live
def test_binance_rest_price_live():
    if os.environ.get("LIVE_TESTS") != "1":
        pytest.skip("Set LIVE_TESTS=1 to enable live API calls")
    client = BinanceMarketClient()
    price = client.rest_price("BTCUSDT")
    assert price > 0
