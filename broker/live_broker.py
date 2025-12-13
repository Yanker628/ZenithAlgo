"""实盘 broker（Binance 现货）。

说明：
- 仅在 allow_live=True 且 mode 为 LIVE_* 时才会真实下单；
- PAPER/DRY_RUN 请使用 `PaperBroker/DryRunBroker`。
"""

from __future__ import annotations

import hashlib
import hmac
import math
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from broker.abstract_broker import Broker, BrokerMode
from shared.models.models import OrderSignal, Position
from shared.utils.logging import setup_logger
from shared.utils.trade_logger import TradeLogger, TradeRecord

SymbolRule = dict[str, float]


class LiveBroker(Broker):
    """对接 Binance 的实盘 broker（含 testnet/mainnet）。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        mode: BrokerMode,
        allow_live: bool = False,
        symbols_allowlist: list[str] | None = None,
        min_notional: float | None = None,
        min_qty: float | None = None,
        qty_step: float | None = None,
        price_step: float | None = None,
        trade_logger: TradeLogger | None = None,
        max_price_deviation_pct: float | None = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.mode = mode
        self.allow_live = allow_live
        self.symbols_allowlist = symbols_allowlist or []
        self.min_notional = min_notional
        self.min_qty = min_qty
        self.qty_step = qty_step
        self.price_step = price_step
        self.trade_logger = trade_logger
        self.max_price_deviation_pct = max_price_deviation_pct

        self.logger = setup_logger("live-broker")
        self.positions: dict[str, Position] = {}
        self.realized_pnl_all = 0.0
        self.realized_pnl_today = 0.0
        self.unrealized_pnl = 0.0
        self.symbol_rules: dict[str, SymbolRule] = {}
        self._seen_client_order_ids: set[str] = set()

        if self.allow_live and self.symbols_allowlist:
            self._load_symbol_rules()

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def execute(self, signal: OrderSignal, **kwargs) -> dict:
        self.logger.info("Execute signal: %s %s qty=%s reason=%s", signal.symbol, signal.side, signal.qty, signal.reason)

        cid = getattr(signal, "client_order_id", None)
        if cid:
            if cid in self._seen_client_order_ids:
                return {"status": "duplicate", "client_order_id": cid}
            self._seen_client_order_ids.add(cid)

        if self.symbols_allowlist and signal.symbol not in self.symbols_allowlist:
            return {"status": "blocked", "reason": "symbol_not_allowed", "symbol": signal.symbol}

        if not self.allow_live:
            return {"status": "blocked", "reason": "live_not_allowed"}
        if self.mode not in {BrokerMode.LIVE, BrokerMode.LIVE_TESTNET, BrokerMode.LIVE_MAINNET}:
            return {"status": "error", "error": f"invalid mode for LiveBroker: {self.mode.value}"}

        try:
            qty = self._validate_and_clip_qty(signal.symbol, signal.qty, price=signal.price)
            if self.max_price_deviation_pct and signal.price is not None:
                self._check_price_deviation(signal.symbol, signal.price)
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}

        params = {
            "symbol": signal.symbol,
            "side": "BUY" if signal.side == "buy" else "SELL",
            "type": "MARKET",
            "quantity": qty,
        }
        if cid:
            params["newClientOrderId"] = cid
        try:
            res = self._request("POST", "/api/v3/order", params)
            self.logger.info("Order placed: %s", res)
            price = self._extract_price(res)
            pos, realized_delta = self._update_position_local(signal, price=price)
            if realized_delta:
                self.realized_pnl_all += realized_delta
                self.realized_pnl_today += realized_delta
            self._maybe_log_trade(signal, price, pos)
            res["price_used"] = price
            if cid:
                res["client_order_id"] = cid
            return res
        except Exception as exc:
            self.logger.error("Order failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def sync_positions(self) -> None:
        """与交易所对账，刷新本地持仓（仅量，不含均价）。"""
        try:
            res = self._request("GET", "/api/v3/account", {})
            balances = res.get("balances", [])
            positions: dict[str, Position] = {}
            allow = set(self.symbols_allowlist) if self.symbols_allowlist else None
            for bal in balances:
                asset = bal.get("asset")
                free = float(bal.get("free") or 0)
                locked = float(bal.get("locked") or 0)
                qty = free + locked
                if qty <= 0:
                    continue
                symbol = f"{asset}USDT"
                if allow and symbol not in allow:
                    continue
                positions[symbol] = Position(
                    symbol=symbol,
                    qty=qty,
                    avg_price=self.positions.get(symbol, Position(symbol, 0, 0)).avg_price,
                )
            self.positions = positions
            self.logger.info("Positions synced from exchange: %s", list(self.positions.keys()))
        except Exception as exc:
            self.logger.warning("sync_positions failed: %s", exc)

    def _sign(self, params: dict) -> str:
        qs = urlencode(params)
        return hmac.new(self.api_secret, qs.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict) -> dict:
        ts = int(time.time() * 1000)
        params["timestamp"] = ts
        params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{self.base_url}{path}"
        resp = requests.request(method, url, params=params, headers=headers, timeout=5)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract_price(order_res: dict) -> float | None:
        price = order_res.get("avgPrice") or order_res.get("price")
        if price:
            try:
                return float(price)
            except (TypeError, ValueError):
                return None
        fills = order_res.get("fills") or []
        if fills:
            try:
                return float(fills[0].get("price"))
            except (TypeError, ValueError, IndexError):
                return None
        return None

    def _maybe_log_trade(self, signal: OrderSignal, price: float | None, pos: Position | None) -> None:
        if not self.trade_logger:
            return
        now = datetime.now(timezone.utc)
        pos_qty = pos.qty if pos else 0.0
        pos_avg = pos.avg_price if pos else 0.0
        self.trade_logger.log(
            TradeRecord(
                ts=now,
                symbol=signal.symbol,
                side=signal.side,
                qty=signal.qty,
                price=price,
                mode=self.mode.value,
                realized_pnl_after_trade=self.realized_pnl_today,
                position_qty_after_trade=pos_qty,
                position_avg_price_after_trade=pos_avg,
            )
        )

    def _validate_and_clip_qty(self, symbol: str, qty: float, price: float | None = None) -> float:
        if qty <= 0:
            raise ValueError("quantity must be positive")

        rule = self.symbol_rules.get(symbol, {})
        qty_step = rule.get("stepSize") or self.qty_step
        min_qty = rule.get("minQty") or self.min_qty
        min_notional = rule.get("minNotional") or self.min_notional

        adjusted_qty = float(qty)
        if qty_step:
            adjusted_qty = math.floor(adjusted_qty / qty_step) * qty_step
        if min_qty and adjusted_qty < min_qty:
            raise ValueError(f"quantity {adjusted_qty} < min_qty {min_qty}")
        if price is not None and min_notional and adjusted_qty * price < min_notional:
            raise ValueError(f"notional {adjusted_qty * price} < min_notional {min_notional}")
        return adjusted_qty

    def _check_price_deviation(self, symbol: str, price: float) -> None:
        if not self.max_price_deviation_pct:
            return
        try:
            res = requests.get(f"{self.base_url}/api/v3/ticker/price", params={"symbol": symbol}, timeout=5)
            res.raise_for_status()
            ticker_price = float(res.json()["price"])
        except Exception as exc:
            raise ValueError(f"failed to fetch ticker price for deviation check: {exc}") from exc
        diff_pct = abs(price - ticker_price) / ticker_price * 100
        if diff_pct > self.max_price_deviation_pct:
            raise ValueError(f"price deviation {diff_pct:.2f}% exceeds limit {self.max_price_deviation_pct}%")

    def _load_symbol_rules(self) -> None:
        if not self.symbols_allowlist:
            return
        try:
            symbols_param = "[" + ",".join(f'"{s}"' for s in self.symbols_allowlist) + "]"
            res = requests.get(f"{self.base_url}/api/v3/exchangeInfo", params={"symbols": symbols_param}, timeout=5)
            res.raise_for_status()
            data = res.json()
            rules = {}
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
                    rules[sym] = rule
            self.symbol_rules = rules
            self.logger.info("Loaded symbol rules for %s", list(rules.keys()))
        except Exception as exc:
            self.logger.warning("Failed to load symbol rules: %s", exc)

    def _update_position_local(self, signal: OrderSignal, price: float | None) -> tuple[Position | None, float]:
        pos = self.positions.get(signal.symbol) or Position(signal.symbol, 0.0, 0.0)
        realized_delta = 0.0
        if signal.side == "buy":
            new_qty = pos.qty + signal.qty
            if price is not None and new_qty > 0:
                pos.avg_price = round((pos.avg_price * pos.qty + price * signal.qty) / new_qty, 2)
            pos.qty = new_qty
        elif signal.side == "sell":
            close_qty = min(pos.qty, signal.qty)
            if price is not None and close_qty > 0 and pos.qty > 0:
                realized_delta = (price - pos.avg_price) * close_qty
            pos.qty = pos.qty - close_qty
            if pos.qty <= 0:
                pos.avg_price = 0.0
        else:
            raise ValueError(f"Unsupported side: {signal.side}")

        if pos.qty <= 0:
            self.positions.pop(signal.symbol, None)
            return None, realized_delta
        self.positions[signal.symbol] = pos
        return pos, realized_delta
