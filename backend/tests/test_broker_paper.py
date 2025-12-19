from zenith.execution.abstract_broker import BrokerMode
from zenith.execution.paper_broker import PaperBroker
from zenith.common.models.models import OrderSignal


def test_binance_broker_paper_rounds_price_and_avg():
    broker = PaperBroker(mode=BrokerMode.PAPER)
    sig = OrderSignal(symbol="BTCUSDT", side="buy", qty=0.1, reason="test")
    setattr(sig, "price", 123.4567)
    res = broker.execute(sig)
    pos = broker.get_position("BTCUSDT")
    assert res["price"] == 123.4567
    assert pos is not None
    assert pos.avg_price == 123.4567
