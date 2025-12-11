from broker.base import BrokerMode
from broker.binance import BinanceBroker
from market.models import OrderSignal


def test_binance_broker_paper_rounds_price_and_avg():
    broker = BinanceBroker(base_url="https://api.binance.com", api_key="k", api_secret="s", mode=BrokerMode.PAPER)
    sig = OrderSignal(symbol="BTCUSDT", side="buy", qty=0.1, reason="test")
    setattr(sig, "price", 123.4567)
    res = broker.execute(sig)
    pos = broker.get_position("BTCUSDT")
    assert res["price"] == 123.46
    assert pos is not None
    assert pos.avg_price == 123.46
