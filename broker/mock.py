from market.models import OrderSignal, Position
from .base import Broker, BrokerMode
from utils.logging import setup_logger
from utils.trade_logger import TradeLogger, TradeRecord

class MockBroker(Broker):
    def __init__(self, trade_logger: TradeLogger | None = None):
        self.logger = setup_logger("mock-broker")
        self.positions: dict[str, Position] = {}
        self.trade_logger = trade_logger
        self.realized_pnl_all = 0.0
        self.realized_pnl_today = 0.0
        self.unrealized_pnl = 0.0

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def execute(self, signal: OrderSignal, price: float | None = None) -> dict:
        self.logger.info(
            f"[MOCK ORDER] {signal.side.upper()} {signal.symbol} qty={signal.qty} reason={signal.reason}"
        )
        # 简单更新持仓，按均价摊薄
        pos = self.positions.get(signal.symbol) or Position(signal.symbol, 0.0, 0.0)
        fill_price = round(price, 2) if price is not None else pos.avg_price
        realized_delta = 0.0
        if signal.side == "buy":
            new_qty = pos.qty + signal.qty
            if new_qty > 0:
                # 加权更新均价
                pos.avg_price = (
                    (pos.avg_price * pos.qty + fill_price * signal.qty)
                    / new_qty
                    if fill_price
                    else pos.avg_price
                )
            pos.qty = new_qty
        elif signal.side == "sell":
            close_qty = min(pos.qty, signal.qty)
            if fill_price and pos.qty > 0:
                realized_delta = (fill_price - pos.avg_price) * close_qty
            pos.qty -= signal.qty
            if pos.qty <= 0:
                pos.avg_price = 0.0

        self.positions[signal.symbol] = pos
        self.realized_pnl_all += realized_delta
        self.realized_pnl_today += realized_delta

        res = {
            "status": "filled",
            "symbol": signal.symbol,
            "side": signal.side,
            "qty": signal.qty,
            "price": fill_price,
            "position_qty": pos.qty,
            "avg_price": pos.avg_price,
            "realized_delta": realized_delta,
        }

        if self.trade_logger:
            self.trade_logger.log(
                TradeRecord(
                    ts=None,
                    symbol=signal.symbol,
                    side=signal.side,
                    qty=signal.qty,
                    price=fill_price,
                    mode=BrokerMode.DRY_RUN.value,
                    realized_pnl_after_trade=self.realized_pnl_today,
                    position_qty_after_trade=pos.qty,
                    position_avg_price_after_trade=pos.avg_price,
                )
            )

        return res
