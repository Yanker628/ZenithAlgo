from datetime import datetime, timezone

from zenith.execution.abstract_broker import BrokerMode
from zenith.execution.paper_broker import PaperBroker
from zenith.common.models.models import OrderSignal


def test_paper_broker_dedup_by_client_order_id() -> None:
    broker = PaperBroker(mode=BrokerMode.PAPER)
    ts = datetime.now(timezone.utc)
    sig = OrderSignal(
        symbol="BTCUSDT",
        side="buy",
        qty=1.0,
        reason="t",
        price=100.0,
        client_order_id=f"cid:{ts.isoformat()}:0",
    )
    res1 = broker.execute(sig)
    pos1 = broker.get_position("BTCUSDT")
    assert res1["status"] == "filled"
    assert pos1 is not None and abs(pos1.qty - 1.0) < 1e-9

    res2 = broker.execute(sig)
    pos2 = broker.get_position("BTCUSDT")
    assert res2["status"] == "duplicate"
    assert pos2 is not None and abs(pos2.qty - 1.0) < 1e-9

