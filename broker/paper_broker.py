"""模拟 broker（dry-run / paper）。

- dry-run：不触网，纯本地记账
- paper：使用真实行情（由 engine 提供 tick），仍只做本地记账
"""

from __future__ import annotations

from datetime import datetime, timezone

from broker.abstract_broker import Broker, BrokerMode
from shared.models.models import OrderSignal, Position
from shared.utils.logging import setup_logger
from shared.utils.trade_logger import TradeLogger, TradeRecord


class PaperBroker(Broker):
    """纸面交易 broker：按给定 price 更新本地持仓。"""

    def __init__(self, *, mode: BrokerMode = BrokerMode.PAPER, trade_logger: TradeLogger | None = None):
        self.mode = mode
        self.logger = setup_logger("paper-broker")
        self.positions: dict[str, Position] = {}
        self.trade_logger = trade_logger
        self.realized_pnl_all = 0.0
        self.realized_pnl_today = 0.0
        self.unrealized_pnl = 0.0

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def execute(self, signal: OrderSignal, price: float | None = None, **kwargs) -> dict:
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

    def __init__(self, trade_logger: TradeLogger | None = None):
        super().__init__(mode=BrokerMode.DRY_RUN, trade_logger=trade_logger)

