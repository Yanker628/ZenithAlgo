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
from typing import Any
from urllib.parse import urlencode

import requests

from broker.abstract_broker import Broker, BrokerMode
from shared.models.models import OrderSignal, Position
from shared.state.sqlite_ledger import SqliteEventLedger
from shared.utils.logging import setup_logger
from shared.utils.precision import decimals_from_step, floor_to_step, snap_to_decimals
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
        ledger_path: str | None = None,
        recovery_enabled: bool = True,
        recovery_mode: str = "observe_only",
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
        self._ledger = SqliteEventLedger(ledger_path) if ledger_path else None
        if self._ledger:
            self._seen_client_order_ids = self._ledger.load_all_client_order_ids()

        self.recovery_enabled = bool(recovery_enabled)
        self.recovery_mode = str(recovery_mode).strip().lower()
        self.reconciled = False
        self.safe_to_trade = False
        self.reconcile_error: str | None = None

        if self.allow_live and self.symbols_allowlist:
            self._load_symbol_rules()

    def get_position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)

    def execute(self, signal: OrderSignal, **kwargs) -> dict:
        self.logger.info("Execute signal: %s %s qty=%s reason=%s", signal.symbol, signal.side, signal.qty, signal.reason)

        if self.recovery_enabled:
            if self.recovery_mode == "observe_only":
                return {"status": "blocked", "reason": "observe_only"}
            if self.recovery_mode == "trade" and (not self.reconciled or not self.safe_to_trade):
                return {"status": "blocked", "reason": "recovery_not_ready"}

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
            exec_qty = qty
            try:
                exec_qty = float(res.get("executedQty") or qty)
            except Exception:
                exec_qty = qty
            pos, realized_delta = self._update_position_local(signal, price=price, exec_qty=exec_qty)
            if realized_delta:
                self.realized_pnl_all += realized_delta
                self.realized_pnl_today += realized_delta
            self._maybe_log_trade(signal, price, pos)
            res["price_used"] = price
            if cid:
                res["client_order_id"] = cid
                if self._ledger:
                    status = str(res.get("status") or "SUBMITTED").upper()
                    self._ledger.set_order_status(cid, status)
                    fills = res.get("fills") or []
                    if isinstance(fills, list) and fills:
                        for i, f in enumerate(fills):
                            try:
                                fee = float(f.get("commission") or 0.0)
                            except Exception:
                                fee = 0.0
                            try:
                                exec_price = float(f.get("price") or price or 0.0)
                            except Exception:
                                exec_price = float(price or 0.0)
                            try:
                                exec_qty = float(f.get("qty") or signal.qty)
                            except Exception:
                                exec_qty = float(signal.qty)
                            self._ledger.append_fill(
                                client_order_id=cid,
                                symbol=signal.symbol,
                                qty=exec_qty,
                                price=exec_price,
                                fee=fee,
                                dedup_key=f"binance:order_resp:{cid}:{i}",
                                ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                raw=f,
                            )
            return res
        except Exception as exc:
            self.logger.error("Order failed: %s", exc)
            if cid and self._ledger:
                self._ledger.set_order_status(cid, "ERROR")
            return {"status": "error", "error": str(exc)}

    def startup_reconcile(self, *, symbols: list[str] | None = None, trades_limit: int = 50) -> dict[str, Any]:
        """启动对账（最小可用版）。

        - 交易所为最终真相源（positions/open orders）。
        - ledger 为可恢复缓存：补齐缺失订单/成交，标记本地“悬空订单”。
        - 对账失败或存在无法自动修正的不一致时，自动进入 observe_only。
        """
        symbols = symbols or (list(self.symbols_allowlist) if self.symbols_allowlist else [])
        if not symbols:
            symbols = []

        self.reconcile_error = None
        self.reconciled = False
        self.safe_to_trade = False
        if not self.recovery_enabled:
            self.reconciled = True
            self.safe_to_trade = True
            return {"ok": True, "skipped": True}
        if self._ledger is None:
            self.recovery_mode = "observe_only"
            self.reconcile_error = "ledger_not_configured"
            return {"ok": False, "error": self.reconcile_error}

        summary: dict[str, Any] = {
            "ok": False,
            "symbols": symbols,
            "open_orders_seen": 0,
            "open_orders_upserted": 0,
            "fills_appended": 0,
            "local_marked_lost": 0,
            "errors": [],
        }

        try:
            self.sync_positions(strict=True)

            open_cids: set[str] = set()
            for sym in symbols:
                res = self._request("GET", "/api/v3/openOrders", {"symbol": sym})
                orders = res if isinstance(res, list) else (res.get("orders") if isinstance(res, dict) else [])
                if not isinstance(orders, list):
                    continue
                for o in orders:
                    if not isinstance(o, dict):
                        continue
                    cid = str(o.get("clientOrderId") or o.get("newClientOrderId") or "")
                    if not cid:
                        cid = f"binance:{sym}:order:{o.get('orderId') or 'UNKNOWN'}"
                    open_cids.add(cid)
                    summary["open_orders_seen"] += 1
                    self._ledger.upsert_order(
                        client_order_id=cid,
                        symbol=str(o.get("symbol") or sym),
                        side=str(o.get("side") or "").lower(),
                        qty=float(o.get("origQty") or 0.0),
                        price=float(o.get("price") or 0.0) if o.get("price") is not None else None,
                        status=str(o.get("status") or "OPEN").upper(),
                        created_at=None,
                        raw=o,
                    )
                    summary["open_orders_upserted"] += 1

            # 本地存在但交易所不存在的“悬空订单”：先标记为 LOST，并触发安全保险丝
            status_map = self._ledger.load_order_status_map()
            for cid, st in status_map.items():
                if cid in open_cids:
                    continue
                if str(st).upper() in {"NEW", "SUBMITTED", "OPEN"}:
                    self._ledger.set_order_status(cid, "LOST")
                    summary["local_marked_lost"] += 1

            # 最近成交：尽量补齐到 ledger（以 trade id 做幂等去重）
            for sym in symbols:
                res = self._request("GET", "/api/v3/myTrades", {"symbol": sym, "limit": int(trades_limit)})
                trades = res if isinstance(res, list) else (res.get("trades") if isinstance(res, dict) else [])
                if not isinstance(trades, list):
                    continue
                for t in trades:
                    if not isinstance(t, dict):
                        continue
                    trade_id = t.get("id")
                    dedup_key = f"binance:trade:{sym}:{trade_id}"
                    order_id = t.get("orderId")
                    cid = None
                    side = "buy" if bool(t.get("isBuyer")) else "sell"
                    if order_id is not None:
                        try:
                            od = self._request("GET", "/api/v3/order", {"symbol": sym, "orderId": int(order_id)})
                            if isinstance(od, dict):
                                cid = od.get("clientOrderId") or od.get("origClientOrderId")
                                side = str(od.get("side") or side).lower()
                                self._ledger.upsert_order(
                                    client_order_id=str(cid) if cid else f"binance:{sym}:order:{order_id}",
                                    symbol=str(od.get("symbol") or sym),
                                    side=str(side),
                                    qty=float(od.get("origQty") or 0.0),
                                    price=float(od.get("price") or 0.0) if od.get("price") is not None else None,
                                    status=str(od.get("status") or "UNKNOWN").upper(),
                                    created_at=None,
                                    raw=od,
                                )
                        except Exception as exc:
                            summary["errors"].append(f"order_lookup_failed:{exc}")
                    if not cid:
                        cid = f"binance:{sym}:order:{order_id or 'UNKNOWN'}"
                        self._ledger.upsert_order(
                            client_order_id=str(cid),
                            symbol=sym,
                            side=side,
                            qty=float(t.get("qty") or 0.0),
                            price=float(t.get("price") or 0.0),
                            status="FILLED",
                            created_at=None,
                            raw={"trade": t},
                        )

                    fee = None
                    if "commission" in t:
                        try:
                            fee = float(t.get("commission") or 0.0)
                        except Exception:
                            fee = None
                    ts_iso = None
                    if "time" in t:
                        try:
                            ts_iso = datetime.fromtimestamp(int(t["time"]) / 1000, tz=timezone.utc).isoformat().replace(
                                "+00:00", "Z"
                            )
                        except Exception:
                            ts_iso = None
                    self._ledger.append_fill(
                        client_order_id=str(cid),
                        symbol=sym,
                        qty=float(t.get("qty") or 0.0),
                        price=float(t.get("price") or 0.0),
                        fee=fee,
                        dedup_key=dedup_key,
                        ts=ts_iso,
                        raw=t,
                    )
                    summary["fills_appended"] += 1

            summary["ok"] = True
            self.reconciled = True
            # 对账过程中可能补齐了“交易所存在但本地缺失”的订单，刷新幂等集合。
            self._seen_client_order_ids = self._ledger.load_all_client_order_ids()
            # 安全保险丝：存在悬空订单时默认降级 observe_only
            if summary["local_marked_lost"] > 0:
                self.safe_to_trade = False
                if self.recovery_mode == "trade":
                    self.recovery_mode = "observe_only"
                return summary

            self.safe_to_trade = True
            return summary
        except Exception as exc:
            self.reconcile_error = str(exc)
            summary["errors"].append(self.reconcile_error)
            self.recovery_mode = "observe_only"
            self.reconciled = False
            self.safe_to_trade = False
            return summary

    def sync_positions(self, *, strict: bool = False) -> None:
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
            if strict:
                raise

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
            adjusted_qty = floor_to_step(adjusted_qty, float(qty_step))
            adjusted_qty = snap_to_decimals(adjusted_qty, decimals_from_step(float(qty_step)))
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

    def _update_position_local(
        self,
        signal: OrderSignal,
        *,
        price: float | None,
        exec_qty: float | None = None,
    ) -> tuple[Position | None, float]:
        pos = self.positions.get(signal.symbol) or Position(signal.symbol, 0.0, 0.0)
        realized_delta = 0.0
        qty = float(exec_qty) if exec_qty is not None else float(signal.qty)
        rule = self.symbol_rules.get(signal.symbol, {})
        qty_step = rule.get("stepSize") or self.qty_step
        tick = rule.get("tickSize") or self.price_step
        qty_decimals = decimals_from_step(float(qty_step)) if qty_step else None
        price_decimals = decimals_from_step(float(tick)) if tick else None

        if signal.side == "buy":
            new_qty = pos.qty + qty
            if price is not None and new_qty > 0:
                pos.avg_price = (pos.avg_price * pos.qty + price * qty) / new_qty
            pos.qty = new_qty
        elif signal.side == "sell":
            close_qty = min(pos.qty, qty)
            if price is not None and close_qty > 0 and pos.qty > 0:
                realized_delta = (price - pos.avg_price) * close_qty
            pos.qty = pos.qty - close_qty
            if pos.qty <= 0:
                pos.avg_price = 0.0
        else:
            raise ValueError(f"Unsupported side: {signal.side}")

        if qty_decimals is not None:
            pos.qty = snap_to_decimals(pos.qty, int(qty_decimals))
        # avg_price 只做展示级 round（本地视图），不影响交易所真实成交
        if price_decimals is not None and pos.avg_price:
            pos.avg_price = snap_to_decimals(pos.avg_price, int(price_decimals))

        if abs(pos.qty) < 1e-12:
            pos.qty = 0.0
            pos.avg_price = 0.0

        if pos.qty <= 0:
            self.positions.pop(signal.symbol, None)
            return None, realized_delta
        self.positions[signal.symbol] = pos
        return pos, realized_delta
