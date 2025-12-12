"""回测专用 Broker。

在离线回测中模拟撮合、手续费、滑点与现金约束。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict

from broker.base import Broker
from market.models import OrderSignal, Position


class BacktestBroker(Broker):
    """离线回测撮合器。

    Parameters
    ----------
    initial_equity:
        初始资金。
    maker_fee:
        Maker 手续费率（0.0002 表示 0.02%）。
    taker_fee:
        Taker 手续费率。
    slippage_bp:
        滑点（bp=万分比），买单抬高、卖单压低。
    """

    def __init__(
        self,
        initial_equity: float,
        maker_fee: float = 0.0,
        taker_fee: float = 0.0004,
        slippage_bp: float = 0.0,
    ):
        self.initial_equity = initial_equity
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.slippage_bp = slippage_bp
        self.cash = initial_equity
        self.positions: Dict[str, Position] = {}
        self.equity_curve: list[tuple[datetime, float]] = []
        self.realized_pnl_all = 0.0
        self.realized_pnl_today = 0.0
        self.unrealized_pnl = 0.0
        self.last_prices: Dict[str, float] = {}
        self.trades: list[dict] = []

    def get_position(self, symbol: str) -> Position | None:
        """返回当前持仓（仅本地视图）。"""
        return self.positions.get(symbol)

    def _apply_slippage(self, price: float, side: str) -> float:
        """按方向应用滑点。

        Parameters
        ----------
        price:
            原始市场价格。
        side:
            "buy" 或 "sell"。

        Returns
        -------
        float
            应用滑点后的成交价。
        """
        if self.slippage_bp == 0:
            return price
        delta = price * (self.slippage_bp / 10000)
        return price + delta if side == "buy" else price - delta

    def execute(
        self,
        signal: OrderSignal,
        tick_price: float | None = None,
        ts: datetime | None = None,
        record_equity: bool = True,
        **kwargs,
    ) -> dict:
        """模拟执行一个订单信号。

        Parameters
        ----------
        signal:
            订单信号，qty 为目标数量。
        tick_price:
            当前 tick 价格（必填）。
        ts:
            tick 时间，用于记录权益曲线。
        record_equity:
            是否把权益点写入 `equity_curve`。默认 True（保持历史行为）。

        Returns
        -------
        dict
            执行结果（含成交价、手续费、PnL、现金/持仓）。
        """
        raw_price = tick_price
        if raw_price is None:
            return {"status": "error", "error": "missing price"}

        exec_price = self._apply_slippage(raw_price, signal.side)
        fee_rate = self.taker_fee  # 简化：回测统一按吃单计费
        pos = self.positions.get(signal.symbol) or Position(symbol=signal.symbol, qty=0.0, avg_price=0.0)
        realized_delta = 0.0
        fee_paid = 0.0
        exec_qty = 0.0

        if signal.side == "buy":
            # 资金约束：现金不足则按剩余现金缩减数量，最低到 0 则拒单
            max_affordable_qty = 0.0
            denom = exec_price * (1 + fee_rate)
            if denom > 0:
                max_affordable_qty = self.cash / denom
            if max_affordable_qty <= 0:
                return {"status": "blocked", "reason": "insufficient_cash"}
            qty_to_buy = min(signal.qty, max_affordable_qty)
            exec_qty = qty_to_buy

            new_qty = pos.qty + qty_to_buy
            notional = exec_price * qty_to_buy
            fee_paid = notional * fee_rate
            if new_qty > 0:
                # 将手续费计入成本
                total_cost = pos.avg_price * pos.qty + notional + fee_paid
                pos.avg_price = total_cost / new_qty
            pos.qty = new_qty
            self.cash -= notional + fee_paid
        elif signal.side == "sell":
            close_qty = min(pos.qty, signal.qty)
            if close_qty > 0:
                exec_qty = close_qty
                notional = exec_price * close_qty
                fee_paid = notional * fee_rate
                realized_delta = (exec_price - pos.avg_price) * close_qty - fee_paid
                pos.qty -= close_qty
                if pos.qty <= 0:
                    pos.avg_price = 0.0
                self.cash += notional - fee_paid
            else:
                # 无持仓可卖
                return {"status": "blocked", "reason": "no_position"}
        else:
            return {"status": "error", "error": f"unsupported side {signal.side}"}

        self.positions[signal.symbol] = pos
        self.realized_pnl_all += realized_delta
        self.realized_pnl_today += realized_delta
        self.last_prices[signal.symbol] = exec_price

        # 更新未实现 PnL 与权益
        self.unrealized_pnl = self._compute_unrealized_pnl()
        equity = self.cash + sum(
            p.qty * self.last_prices.get(sym, p.avg_price) for sym, p in self.positions.items()
        )
        if ts and record_equity:
            self.equity_curve.append((ts, equity))

        self.trades.append(
            {
                "ts": ts,
                "symbol": signal.symbol,
                "side": signal.side,
                "qty": exec_qty,
                "price": raw_price,
                "slippage_price": exec_price,
                "fee": fee_paid,
                "realized_delta": realized_delta,
            }
        )

        return {
            "status": "filled",
            "symbol": signal.symbol,
            "side": signal.side,
            "qty": exec_qty,
            "price": raw_price,
            "slippage_price": exec_price,
            "realized_delta": realized_delta,
            "fee": fee_paid,
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
