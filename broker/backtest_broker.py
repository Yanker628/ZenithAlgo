"""回测专用 Broker。

在离线回测中模拟撮合、手续费、滑点与现金约束。
"""

from __future__ import annotations

from datetime import datetime

from broker.abstract_broker import Broker
from broker.execution.simulator import BacktestFillSimulator
from broker.execution.slippage_models import BpsSlippageModel
from shared.models.models import OrderSignal, Position
from shared.state.sqlite_ledger import SqliteEventLedger


class BacktestBroker(Broker):
    """离线回测撮合器。"""

    def __init__(
        self,
        initial_equity: float,
        maker_fee: float = 0.0,
        taker_fee: float = 0.0004,
        slippage_bp: float = 0.0,
        ledger_path: str | None = None,
    ):
        self.initial_equity = float(initial_equity)
        self.maker_fee = float(maker_fee)
        self.taker_fee = float(taker_fee)
        self.slippage_bp = float(slippage_bp)

        self.cash = float(initial_equity)
        self.positions: dict[str, Position] = {}
        self.equity_curve: list[tuple[datetime, float]] = []
        self.realized_pnl_all = 0.0
        self.realized_pnl_today = 0.0
        self.unrealized_pnl = 0.0
        self.last_prices: dict[str, float] = {}
        self.trades: list[dict] = []
        self._seen_client_order_ids: set[str] = set()
        self._ledger = SqliteEventLedger(ledger_path) if ledger_path else None
        if self._ledger:
            self._seen_client_order_ids = self._ledger.load_all_client_order_ids()

        self._sim = BacktestFillSimulator(
            fee_rate=self.taker_fee,  # 简化：回测统一按吃单计费
            slippage=BpsSlippageModel(self.slippage_bp),
        )

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def execute(
        self,
        signal: OrderSignal,
        tick_price: float | None = None,
        ts: datetime | None = None,
        record_equity: bool = True,
        **kwargs,
    ) -> dict:
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

        raw_price = tick_price
        if raw_price is None:
            return {"status": "error", "error": "missing price"}

        fill = self._sim.fill(
            signal=signal,
            raw_price=float(raw_price),
            cash=float(self.cash),
            position=self.positions.get(signal.symbol),
        )

        if fill.status != "filled":
            payload: dict = {"status": fill.status}
            if fill.reason:
                payload["reason"] = fill.reason
            if cid and self._ledger:
                self._ledger.set_order_status(cid, fill.status.upper())
            return payload

        self.cash = fill.cash
        pos = fill.position
        if pos.qty <= 0:
            self.positions.pop(signal.symbol, None)
        else:
            self.positions[signal.symbol] = pos

        self.realized_pnl_all += fill.realized_delta
        self.realized_pnl_today += fill.realized_delta
        self.last_prices[signal.symbol] = fill.exec_price

        self.unrealized_pnl = self._compute_unrealized_pnl()
        equity = self.cash + sum(
            p.qty * self.last_prices.get(sym, p.avg_price) for sym, p in self.positions.items()
        )
        if ts and record_equity:
            self.equity_curve.append((ts, equity))

        self.trades.append(
            {
                "ts": ts,
                "client_order_id": getattr(signal, "client_order_id", None),
                "symbol": signal.symbol,
                "side": signal.side,
                "qty": fill.exec_qty,
                "price": float(raw_price),
                "slippage_price": fill.exec_price,
                "fee": fill.fee_paid,
                "realized_delta": fill.realized_delta,
            }
        )
        if cid and self._ledger:
            self._ledger.set_order_status(cid, "FILLED")
            self._ledger.append_fill(
                client_order_id=cid,
                symbol=signal.symbol,
                qty=float(fill.exec_qty),
                price=float(fill.exec_price),
                fee=float(fill.fee_paid),
                ts=(ts.isoformat() if ts else None),
                raw={"raw_price": float(raw_price), "exec_price": float(fill.exec_price)},
            )

        return {
            "status": "filled",
            "client_order_id": getattr(signal, "client_order_id", None),
            "symbol": signal.symbol,
            "side": signal.side,
            "qty": fill.exec_qty,
            "price": float(raw_price),
            "slippage_price": fill.exec_price,
            "realized_delta": fill.realized_delta,
            "fee": fill.fee_paid,
            "position_qty": pos.qty,
            "position_avg": pos.avg_price,
            "equity": equity,
            "cash": self.cash,
        }

    def _compute_unrealized_pnl(self) -> float:
        pnl = 0.0
        for sym, pos in self.positions.items():
            price = self.last_prices.get(sym)
            if price is None or pos.qty == 0:
                continue
            pnl += pos.qty * (price - pos.avg_price)
        return pnl
