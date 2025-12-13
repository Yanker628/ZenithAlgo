"""模拟 broker（dry-run / paper）。

- dry-run：不触网，纯本地记账
- paper：使用真实行情（由 engine 提供 tick），仍只做本地记账
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import requests

from broker.abstract_broker import Broker, BrokerMode
from shared.models.models import OrderSignal, Position
from shared.state.sqlite_ledger import SqliteEventLedger
from shared.utils.logging import setup_logger
from shared.utils.precision import decimals_from_step, floor_to_step, snap_to_decimals
from shared.utils.trade_logger import TradeLogger, TradeRecord

SymbolRule = dict[str, float]


class PaperBroker(Broker):
    """纸面交易 broker：按给定 price 更新本地持仓。"""

    def __init__(
        self,
        *,
        mode: BrokerMode = BrokerMode.PAPER,
        trade_logger: TradeLogger | None = None,
        ledger_path: str | None = None,
        base_url: str | None = None,
        symbols_allowlist: list[str] | None = None,
        min_notional: float | None = None,
        min_qty: float | None = None,
        qty_step: float | None = None,
        price_step: float | None = None,
    ):
        self.mode = mode
        self.logger = setup_logger("paper-broker")
        self.positions: dict[str, Position] = {}
        self.trade_logger = trade_logger
        self.realized_pnl_all = 0.0
        self.realized_pnl_today = 0.0
        self.unrealized_pnl = 0.0
        self.base_url = base_url
        self.symbols_allowlist = symbols_allowlist or []
        self.min_notional = min_notional
        self.min_qty = min_qty
        self.qty_step = qty_step
        self.price_step = price_step
        self.symbol_rules: dict[str, SymbolRule] = {}
        self._seen_client_order_ids: set[str] = set()
        self._ledger = SqliteEventLedger(ledger_path) if ledger_path else None
        if self._ledger:
            self._seen_client_order_ids = self._ledger.load_all_client_order_ids()
            self._restore_from_ledger()

        self._maybe_load_symbol_rules(self.symbols_allowlist)

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def _maybe_load_symbol_rules(self, symbols: list[str]) -> None:
        if not self.base_url or not symbols:
            return
        self._load_symbol_rules(symbols)

    def _load_symbol_rules(self, symbols: list[str]) -> None:
        if not self.base_url or not symbols:
            return
        try:
            symbols_param = "[" + ",".join(f'"{s}"' for s in symbols) + "]"
            res = requests.get(f"{self.base_url}/api/v3/exchangeInfo", params={"symbols": symbols_param}, timeout=5)
            res.raise_for_status()
            data = res.json()
            loaded: dict[str, SymbolRule] = {}
            for symbol_info in data.get("symbols", []):
                sym = symbol_info.get("symbol")
                filters = symbol_info.get("filters", [])
                rule: dict[str, float] = {}
                for f in filters:
                    ftype = f.get("filterType")
                    if ftype == "LOT_SIZE":
                        rule["minQty"] = float(f.get("minQty"))
                        rule["stepSize"] = float(f.get("stepSize"))
                    elif ftype == "NOTIONAL":
                        rule["minNotional"] = float(f.get("minNotional"))
                    elif ftype == "PRICE_FILTER":
                        rule["tickSize"] = float(f.get("tickSize"))
                if sym:
                    loaded[sym] = rule
            if loaded:
                self.symbol_rules.update(loaded)
                self.logger.info("Loaded symbol rules for %s", list(loaded.keys()))
        except Exception as exc:
            self.logger.warning("Failed to load symbol rules (paper): %s", exc)

    def _ensure_symbol_rule(self, symbol: str) -> None:
        if symbol in self.symbol_rules:
            return
        # 纸面模式：允许用户临时切换 symbol，不强依赖 symbols_allowlist 配置。
        # 若 base_url 可用，则按需补齐该 symbol 的交易规则（stepSize/minQty/tickSize）。
        self._load_symbol_rules([symbol])

    def _validate_and_clip_qty(self, symbol: str, qty: float, *, price: float) -> float:
        if qty <= 0:
            raise ValueError("quantity must be positive")

        self._ensure_symbol_rule(symbol)
        rule = self.symbol_rules.get(symbol, {})
        qty_step = rule.get("stepSize") or self.qty_step
        min_qty = rule.get("minQty") or self.min_qty
        min_notional = rule.get("minNotional") or self.min_notional

        adjusted_qty = float(qty)
        if qty_step:
            adjusted_qty = floor_to_step(adjusted_qty, float(qty_step))
            adjusted_qty = snap_to_decimals(adjusted_qty, decimals_from_step(float(qty_step)))
        if adjusted_qty <= 0:
            raise ValueError("quantity clipped to 0 by stepSize")
        if min_qty and adjusted_qty < min_qty:
            raise ValueError(f"quantity {adjusted_qty} < min_qty {min_qty}")
        if min_notional and adjusted_qty * price < min_notional:
            raise ValueError(f"notional {adjusted_qty * price} < min_notional {min_notional}")
        return adjusted_qty

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

            self._ensure_symbol_rule(symbol)
            rule = self.symbol_rules.get(symbol, {})
            qty_step = rule.get("stepSize") or self.qty_step
            qty_decimals = decimals_from_step(float(qty_step)) if qty_step else None
            tick = rule.get("tickSize") or self.price_step
            price_decimals = decimals_from_step(float(tick)) if tick else None

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

            if qty_decimals is not None:
                pos.qty = snap_to_decimals(pos.qty, int(qty_decimals))
            if price_decimals is not None and pos.avg_price:
                pos.avg_price = snap_to_decimals(pos.avg_price, int(price_decimals))

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
        # 纸面/干跑：保持行情精度，不要强行 round(2)。
        # 否则像 DOGE(0.13xx) 这类低价品种会被“吃掉波动”，PnL/avg_price 全失真。
        fill_price = float(fill_price_raw)

        try:
            exec_qty = self._validate_and_clip_qty(signal.symbol, float(signal.qty), price=float(fill_price))
        except ValueError as exc:
            return {"status": "blocked", "reason": str(exc)}

        self.logger.info(
            "[%s ORDER] %s %s qty=%s reason=%s",
            self.mode.value,
            signal.side.upper(),
            signal.symbol,
            exec_qty,
            signal.reason,
        )

        pos = self.positions.get(signal.symbol) or Position(signal.symbol, 0.0, 0.0)
        realized_delta = 0.0
        rule = self.symbol_rules.get(signal.symbol, {})
        qty_step = rule.get("stepSize") or self.qty_step
        qty_decimals = decimals_from_step(float(qty_step)) if qty_step else None
        tick = rule.get("tickSize") or self.price_step
        price_decimals = decimals_from_step(float(tick)) if tick else None
        if qty_decimals is not None:
            exec_qty = snap_to_decimals(exec_qty, int(qty_decimals))
        if price_decimals is not None:
            fill_price = snap_to_decimals(fill_price, int(price_decimals))

        if signal.side == "buy":
            new_qty = pos.qty + exec_qty
            if new_qty > 0:
                pos.avg_price = (pos.avg_price * pos.qty + fill_price * exec_qty) / new_qty
            pos.qty = new_qty
        elif signal.side == "sell":
            close_qty = min(pos.qty, exec_qty)
            if close_qty <= 0 or pos.qty <= 0:
                return {"status": "blocked", "reason": "no_position"}
            realized_delta = (fill_price - pos.avg_price) * close_qty
            pos.qty -= close_qty
            if pos.qty <= 0:
                pos.avg_price = 0.0
        else:
            return {"status": "error", "error": f"unsupported side {signal.side}"}

        if qty_decimals is not None:
            pos.qty = snap_to_decimals(pos.qty, int(qty_decimals))
        if price_decimals is not None and pos.avg_price:
            pos.avg_price = snap_to_decimals(pos.avg_price, int(price_decimals))

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
                    qty=exec_qty,
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
                qty=float(exec_qty),
                price=float(fill_price),
                fee=0.0,
                ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                raw={"fill_price": fill_price, "realized_delta": realized_delta, "qty_requested": float(signal.qty)},
            )

        return {
            "status": "filled",
            "symbol": signal.symbol,
            "side": signal.side,
            "qty": exec_qty,
            "price": fill_price,
            "position_qty": pos.qty,
            "avg_price": pos.avg_price,
            "realized_delta": realized_delta,
        }


class DryRunBroker(PaperBroker):
    """干跑 broker：等价 paper，但默认 mode=DRY_RUN。"""

    def __init__(
        self,
        trade_logger: TradeLogger | None = None,
        ledger_path: str | None = None,
        **kwargs,
    ):
        super().__init__(mode=BrokerMode.DRY_RUN, trade_logger=trade_logger, ledger_path=ledger_path, **kwargs)
