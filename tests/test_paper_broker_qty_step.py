from broker.abstract_broker import BrokerMode
from broker.paper_broker import PaperBroker
from shared.models.models import OrderSignal


def test_paper_broker_clips_qty_by_step():
    broker = PaperBroker(mode=BrokerMode.PAPER, qty_step=1.0, min_qty=1.0)
    sig = OrderSignal(symbol="GUNUSDT", side="buy", qty=3.7, reason="test")
    res = broker.execute(sig, price=0.1)
    assert res["status"] == "filled"
    assert res["qty"] == 3.0
    pos = broker.get_position("GUNUSDT")
    assert pos is not None
    assert pos.qty == 3.0


def test_paper_broker_blocks_when_qty_clips_to_zero():
    broker = PaperBroker(mode=BrokerMode.PAPER, qty_step=10.0, min_qty=1.0)
    sig = OrderSignal(symbol="GUNUSDT", side="buy", qty=3.0, reason="test")
    res = broker.execute(sig, price=0.1)
    assert res["status"] == "blocked"
    assert "clipped" in str(res.get("reason") or "").lower()

