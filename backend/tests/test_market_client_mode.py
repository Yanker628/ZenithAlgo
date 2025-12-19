from zenith.data.client import get_market_client, BinanceMarketClient, FakeMarketClient


def test_get_market_client_respects_mode():
    live_client = get_market_client("paper", "binance", ws_url="wss://x")
    assert isinstance(live_client, BinanceMarketClient)

    fake_client = get_market_client("dry-run", "binance")
    assert isinstance(fake_client, FakeMarketClient)
