from __future__ import annotations

from broker.abstract_broker import BrokerMode
from broker.live_broker import LiveBroker
from shared.models.models import OrderSignal
from shared.state.sqlite_ledger import SqliteEventLedger


def _make_live_broker(*, ledger_path: str, recovery_mode: str) -> LiveBroker:
    return LiveBroker(
        base_url="https://example.invalid",
        api_key="k",
        api_secret="s",
        mode=BrokerMode.LIVE_TESTNET,
        allow_live=False,
        symbols_allowlist=["BTCUSDT"],
        trade_logger=None,
        ledger_path=ledger_path,
        recovery_enabled=True,
        recovery_mode=recovery_mode,
    )


def test_startup_reconcile_success_allows_trade_mode_after_ready(tmp_path):
    broker = _make_live_broker(ledger_path=str(tmp_path / "ledger.sqlite3"), recovery_mode="trade")

    def fake_request(method: str, path: str, params: dict):
        if path == "/api/v3/account":
            return {"balances": []}
        if path == "/api/v3/openOrders":
            return []
        if path == "/api/v3/myTrades":
            return []
        raise AssertionError(f"unexpected request: {method} {path} {params}")

    broker._request = fake_request  # type: ignore[method-assign]

    summary = broker.startup_reconcile(symbols=["BTCUSDT"])
    assert summary["ok"] is True
    assert broker.reconciled is True
    assert broker.safe_to_trade is True
    assert broker.recovery_mode == "trade"

    res = broker.execute(OrderSignal(symbol="BTCUSDT", side="buy", qty=0.01, price=100.0, client_order_id="cid1"))
    assert res["status"] == "blocked"
    assert res["reason"] == "live_not_allowed"


def test_startup_reconcile_marks_local_submitted_as_lost_and_fuses_to_observe_only(tmp_path):
    ledger_path = str(tmp_path / "ledger.sqlite3")
    ledger = SqliteEventLedger(ledger_path)
    ok = ledger.insert_order_new(
        client_order_id="cid_lost",
        symbol="BTCUSDT",
        side="buy",
        qty=0.01,
        price=100.0,
        raw_signal={"note": "test"},
    )
    assert ok is True
    ledger.set_order_status("cid_lost", "SUBMITTED")
    ledger.close()

    broker = _make_live_broker(ledger_path=ledger_path, recovery_mode="trade")

    def fake_request(method: str, path: str, params: dict):
        if path == "/api/v3/account":
            return {"balances": []}
        if path == "/api/v3/openOrders":
            return []
        if path == "/api/v3/myTrades":
            return []
        raise AssertionError(f"unexpected request: {method} {path} {params}")

    broker._request = fake_request  # type: ignore[method-assign]

    summary = broker.startup_reconcile(symbols=["BTCUSDT"])
    assert summary["ok"] is True
    assert summary["local_marked_lost"] == 1
    assert broker.safe_to_trade is False
    assert broker.recovery_mode == "observe_only"
    assert broker._ledger is not None
    assert broker._ledger.load_order_status_map()["cid_lost"] == "LOST"

    res = broker.execute(OrderSignal(symbol="BTCUSDT", side="buy", qty=0.01, price=100.0, client_order_id="cid2"))
    assert res["status"] == "blocked"
    assert res["reason"] == "observe_only"


def test_startup_reconcile_failure_downgrades_to_observe_only(tmp_path):
    broker = _make_live_broker(ledger_path=str(tmp_path / "ledger.sqlite3"), recovery_mode="trade")

    def fake_request(method: str, path: str, params: dict):
        raise RuntimeError("api down")

    broker._request = fake_request  # type: ignore[method-assign]

    summary = broker.startup_reconcile(symbols=["BTCUSDT"])
    assert summary["ok"] is False
    assert summary["errors"]
    assert broker.reconciled is False
    assert broker.safe_to_trade is False
    assert broker.recovery_mode == "observe_only"

    res = broker.execute(OrderSignal(symbol="BTCUSDT", side="buy", qty=0.01, price=100.0, client_order_id="cid3"))
    assert res["status"] == "blocked"
    assert res["reason"] == "observe_only"

