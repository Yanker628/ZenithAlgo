"""回测撮合模拟器。

职责：在给定 (signal, raw_price, fee_rate, slippage_model, cash, position) 的情况下，
返回成交结果与更新后的 cash/position。
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.models.models import OrderSignal, Position

from broker.execution.slippage_models import BpsSlippageModel, SlippageModel


@dataclass(frozen=True)
class FillResult:
    status: str
    reason: str | None
    raw_price: float
    exec_price: float
    exec_qty: float
    fee_paid: float
    realized_delta: float
    cash: float
    position: Position


class BacktestFillSimulator:
    """现货语义撮合：不做空；sell 仅平已有仓位。"""

    def __init__(self, *, fee_rate: float, slippage: SlippageModel | None = None):
        self.fee_rate = float(fee_rate)
        self.slippage = slippage or BpsSlippageModel(0.0)

    def fill(self, *, signal: OrderSignal, raw_price: float, cash: float, position: Position | None) -> FillResult:
        pos = position or Position(symbol=signal.symbol, qty=0.0, avg_price=0.0)
        exec_price = self.slippage.apply(price=float(raw_price), side=str(signal.side))

        if signal.side == "buy":
            return self._fill_buy(signal=signal, exec_price=exec_price, cash=cash, pos=pos, raw_price=raw_price)
        if signal.side == "sell":
            return self._fill_sell(signal=signal, exec_price=exec_price, cash=cash, pos=pos, raw_price=raw_price)
        return FillResult(
            status="error",
            reason=f"unsupported side {signal.side}",
            raw_price=float(raw_price),
            exec_price=float(exec_price),
            exec_qty=0.0,
            fee_paid=0.0,
            realized_delta=0.0,
            cash=float(cash),
            position=pos,
        )

    def _fill_buy(self, *, signal: OrderSignal, exec_price: float, cash: float, pos: Position, raw_price: float) -> FillResult:
        denom = exec_price * (1.0 + self.fee_rate)
        max_affordable_qty = (cash / denom) if denom > 0 else 0.0
        if max_affordable_qty <= 0:
            return FillResult(
                status="blocked",
                reason="insufficient_cash",
                raw_price=float(raw_price),
                exec_price=float(exec_price),
                exec_qty=0.0,
                fee_paid=0.0,
                realized_delta=0.0,
                cash=float(cash),
                position=pos,
            )

        exec_qty = min(float(signal.qty), max_affordable_qty)
        notional = exec_price * exec_qty
        fee_paid = notional * self.fee_rate

        new_qty = pos.qty + exec_qty
        if new_qty > 0:
            total_cost = pos.avg_price * pos.qty + notional + fee_paid
            pos.avg_price = total_cost / new_qty
        pos.qty = new_qty

        cash = cash - notional - fee_paid
        return FillResult(
            status="filled",
            reason=None,
            raw_price=float(raw_price),
            exec_price=float(exec_price),
            exec_qty=float(exec_qty),
            fee_paid=float(fee_paid),
            realized_delta=0.0,
            cash=float(cash),
            position=pos,
        )

    def _fill_sell(self, *, signal: OrderSignal, exec_price: float, cash: float, pos: Position, raw_price: float) -> FillResult:
        close_qty = min(pos.qty, float(signal.qty))
        if close_qty <= 0:
            return FillResult(
                status="blocked",
                reason="no_position",
                raw_price=float(raw_price),
                exec_price=float(exec_price),
                exec_qty=0.0,
                fee_paid=0.0,
                realized_delta=0.0,
                cash=float(cash),
                position=pos,
            )

        notional = exec_price * close_qty
        fee_paid = notional * self.fee_rate
        realized_delta = (exec_price - pos.avg_price) * close_qty - fee_paid

        pos.qty -= close_qty
        if pos.qty <= 0:
            pos.avg_price = 0.0
        cash = cash + notional - fee_paid

        return FillResult(
            status="filled",
            reason=None,
            raw_price=float(raw_price),
            exec_price=float(exec_price),
            exec_qty=float(close_qty),
            fee_paid=float(fee_paid),
            realized_delta=float(realized_delta),
            cash=float(cash),
            position=pos,
        )

