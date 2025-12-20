from pathlib import Path

from zenith.execution.abstract_broker import BrokerMode
from zenith.execution.paper_broker import PaperBroker
from zenith.common.models.models import OrderSignal


def test_sqlite_ledger_cross_process_idempotency(tmp_path: Path) -> None:
    ledger_path = tmp_path / "state.sqlite3"

    sig = OrderSignal(
        symbol="BTCUSDT",
        side="buy",
        qty=1.0,
        reason="t",
        price=100.0,
        client_order_id="cid:btc:buy:0",
    )

    broker1 = PaperBroker(mode=BrokerMode.PAPER, ledger_path=str(ledger_path))
    res1 = broker1.execute(sig)
    assert res1["status"] == "filled"
    pos1 = broker1.get_position("BTCUSDT")
    assert pos1 is not None and abs(pos1.qty - 1.0) < 1e-9

    # 模拟“进程退出→重启”：新 broker 使用同一个 SQLite
    broker2 = PaperBroker(mode=BrokerMode.PAPER, ledger_path=str(ledger_path))
    pos2_before = broker2.get_position("BTCUSDT")
    assert pos2_before is not None and abs(pos2_before.qty - 1.0) < 1e-9

    res2 = broker2.execute(sig)
    assert res2["status"] == "duplicate"
    pos2_after = broker2.get_position("BTCUSDT")
    assert pos2_after is not None and abs(pos2_after.qty - 1.0) < 1e-9

