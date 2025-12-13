"""模拟 broker（dry-run / paper）。

- dry-run：不触网，纯本地记账
- paper：使用真实行情（由 engine 提供 tick），仍只做本地记账
"""

from __future__ import annotations

from datetime import datetime, timezone

from broker.abstract_broker import Broker, BrokerMode
from shared.models.models import OrderSignal, Position
from shared.state.sqlite_ledger import SqliteEventLedger
from shared.utils.logging import setup_logger
from shared.utils.trade_logger import TradeLogger, TradeRecord


class PaperBroker(Broker):
    """纸面交易 broker：按给定 price 更新本地持仓。"""

    def __init__(
        self,
        *,
        mode: BrokerMode = BrokerMode.PAPER,
        trade_logger: TradeLogger | None = None,
        ledger_path: str | None = None,
    ):
        self.mode = mode
        self.logger = setup_logger("paper-broker")
        self.positions: dict[str, Position] = {}
        self.trade_logger = trade_logger
        self.realized_pnl_all = 0.0
        self.realized_pnl_today = 0.0
        self.unrealized_pnl = 0.0
        self._seen_client_order_ids: set[str] = set()
        self._ledger = SqliteEventLedger(ledger_path) if ledger_path else None
        if self._ledger:
            self._seen_client_order_ids = self._ledger.load_all_client_order_ids()
            self._restore_from_ledger()

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def _restore_from_ledger(self) -> None:
        assert self._ledger is not None
        for row in self._ledger.iter_fills_with_order_side():
            side = str(row.get("side") or "")
            symbol = str(row.get("symbol") or "")
            qty = float(row.get("qty") or 0.0)
            price = float(row.get("price") or 0.0)
            fee = float(row.get("fee") or 0.0) if row.get("fee") is not None else 0.0
            if not symbol or qty <= 0 or price <= 0 or side not in {"buy", "sell"}:
                continue

            pos = self.positions.get(symbol) or Position(symbol, 0.0, 0.0)
            realized_delta = 0.0
            if side == "buy":
                new_qty = pos.qty + qty
                if new_qty > 0:
                    pos.avg_price = (pos.avg_price * pos.qty + price * qty + fee) / new_qty
                pos.qty = new_qty
            else:
                close_qty = min(pos.qty, qty)
                if close_qty > 0 and pos.qty > 0:
                    realized_delta = (price - pos.avg_price) * close_qty - fee
                pos.qty -= close_qty
                if pos.qty <= 0:
                    pos.avg_price = 0.0

            if pos.qty <= 0:
                self.positions.pop(symbol, None)
            else:
                self.positions[symbol] = pos
            self.realized_pnl_all += realized_delta

        self.realized_pnl_today = self.realized_pnl_all

    def execute(self, signal: OrderSignal, price: float | None = None, **kwargs) -> dict:
        cid = getattr(signal, "client_order_id", None)
        if cid:
            if cid in self._seen_client_order_ids:
                return {"status": "duplicate", "client_order_id": cid}
            if self._ledger:
                ok = self._ledger.insert_order_new(
                    client_order_id=cid,
                    symbol=signal.symbol,
                    side=signal.side,
                    qty=signal.qty,
                    price=getattr(signal, "price", None),
                    raw_signal=signal,
                )
                if not ok:
                    self._seen_client_order_ids.add(cid)
                    return {"status": "duplicate", "client_order_id": cid}
            self._seen_client_order_ids.add(cid)

        signal_price = getattr(signal, "price", None)
        fill_price_raw = price if price is not None else signal_price
        if fill_price_raw is None:
            return {"status": "error", "error": "missing price"}
        fill_price = round(float(fill_price_raw), 2)

        self.logger.info(
            "[%s ORDER] %s %s qty=%s reason=%s",
            self.mode.value,
            signal.side.upper(),
            signal.symbol,
            signal.qty,
            signal.reason,
        )

        pos = self.positions.get(signal.symbol) or Position(signal.symbol, 0.0, 0.0)
        realized_delta = 0.0

        if signal.side == "buy":
            new_qty = pos.qty + signal.qty
            if new_qty > 0:
                pos.avg_price = (pos.avg_price * pos.qty + fill_price * signal.qty) / new_qty
            pos.qty = new_qty
        elif signal.side == "sell":
            close_qty = min(pos.qty, signal.qty)
            if close_qty <= 0 or pos.qty <= 0:
                return {"status": "blocked", "reason": "no_position"}
            realized_delta = (fill_price - pos.avg_price) * close_qty
            pos.qty -= close_qty
            if pos.qty <= 0:
                pos.avg_price = 0.0
        else:
            return {"status": "error", "error": f"unsupported side {signal.side}"}

        if pos.qty <= 0:
            self.positions.pop(signal.symbol, None)
        else:
            self.positions[signal.symbol] = pos

        self.realized_pnl_all += realized_delta
        self.realized_pnl_today += realized_delta

        if self.trade_logger:
            self.trade_logger.log(
                TradeRecord(
                    ts=datetime.now(timezone.utc),
                    symbol=signal.symbol,
                    side=signal.side,
                    qty=signal.qty,
                    price=fill_price,
                    mode=self.mode.value,
                    realized_pnl_after_trade=self.realized_pnl_today,
                    position_qty_after_trade=pos.qty,
                    position_avg_price_after_trade=pos.avg_price,
                )
            )

        if cid and self._ledger:
            self._ledger.set_order_status(cid, "FILLED" if pos.qty >= 0 else "FILLED")
            self._ledger.append_fill(
                client_order_id=cid,
                symbol=signal.symbol,
                qty=float(signal.qty),
                price=float(fill_price),
                fee=0.0,
                ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                raw={"fill_price": fill_price, "realized_delta": realized_delta},
            )

        return {
            "status": "filled",
            "symbol": signal.symbol,
            "side": signal.side,
            "qty": signal.qty,
            "price": fill_price,
            "position_qty": pos.qty,
            "avg_price": pos.avg_price,
            "realized_delta": realized_delta,
        }


class DryRunBroker(PaperBroker):
    """干跑 broker：等价 paper，但默认 mode=DRY_RUN。"""

    def __init__(self, trade_logger: TradeLogger | None = None, ledger_path: str | None = None):
        super().__init__(mode=BrokerMode.DRY_RUN, trade_logger=trade_logger, ledger_path=ledger_path)
