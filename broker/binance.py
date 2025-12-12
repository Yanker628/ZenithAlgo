"""Binance broker（dry-run / paper / live）。"""

import time
import hmac
import hashlib
import math
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone

from broker.base import Broker, BrokerMode
from market.models import OrderSignal, Position
from utils.logging import setup_logger
from utils.trade_logger import TradeLogger, TradeRecord

SymbolRule = dict[str, float]


class BinanceBroker(Broker):
    """对接 Binance 的 broker。

    Notes
    -----
    - `DRY_RUN`：完全模拟，不触网。
    - `PAPER`：使用真实行情、仅本地更新持仓。
    - `LIVE_*`：真实下单（受 allow_live/白名单/精度校验保护）。
    """

    def __init__(
        self,
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
        self.logger = setup_logger("binance-broker")
        self.positions: dict[str, Position] = {}  # 本地持仓视图（V1.1 可先简单）
        self.allow_live = allow_live
        self.symbols_allowlist = symbols_allowlist or []
        self.min_notional = min_notional
        self.min_qty = min_qty
        self.qty_step = qty_step
        self.price_step = price_step
        self.trade_logger = trade_logger
        self.max_price_deviation_pct = max_price_deviation_pct
        self.realized_pnl_all = 0.0
        self.realized_pnl_today = 0.0
        self.unrealized_pnl = 0.0
        self.symbol_rules: dict[str, SymbolRule] = {}
        if self.allow_live and self.symbols_allowlist:
            self._load_symbol_rules()

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

    def get_position(self, symbol: str) -> Position | None:
        """返回本地持仓视图中的仓位。"""
        return self.positions.get(symbol)

    def execute(self, signal: OrderSignal, **kwargs) -> dict:
        """执行信号（按 mode 选择 dry-run/paper/live）。

        Parameters
        ----------
        signal:
            订单信号，必须包含 symbol/side/qty，paper/live 需有 price。

        Returns
        -------
        dict
            执行结果（含状态、成交价、持仓快照等）。
        """
        self.logger.info(f"Execute signal: {signal.symbol} {signal.side} qty={signal.qty} reason={signal.reason}")

        if self.symbols_allowlist and signal.symbol not in self.symbols_allowlist:
            return {"status": "blocked", "reason": "symbol_not_allowed", "symbol": signal.symbol}

        if self.mode == BrokerMode.DRY_RUN:
            # 完全模拟：复用 MockBroker 的逻辑
            return self._mock_execute(signal)
        if self.mode == BrokerMode.PAPER:
            # 只在本地记录“虚拟持仓”，不发真实订单
            return self._paper_execute(signal)
        if self.mode in {BrokerMode.LIVE, BrokerMode.LIVE_TESTNET, BrokerMode.LIVE_MAINNET}:
            if not self.allow_live:
                return {"status": "blocked", "reason": "live_not_allowed"}
            # 真正下单
            return self._live_execute(signal)

        raise ValueError(f"Unknown broker mode: {self.mode}")

    def _mock_execute(self, signal: OrderSignal) -> dict:
        # 参考 MockBroker 的实现，立即成交
        self.logger.info(f"[MOCK ORDER] {signal.side.upper()} {signal.symbol} qty={signal.qty}")
        pos, realized_delta = self._update_position_local(signal, price=None)
        status = {
            "status": "filled",
            "symbol": signal.symbol,
            "side": signal.side,
            "qty": signal.qty,
            "price": None,
        }
        if pos:
            status["position_qty"] = pos.qty
            status["avg_price"] = pos.avg_price
        if realized_delta:
            self.realized_pnl_all += realized_delta
            self.realized_pnl_today += realized_delta
        self._maybe_log_trade(signal, None, pos)
        return status

    def _paper_execute(self, signal: OrderSignal) -> dict:
        # 纸上交易：只更新本地持仓，不触网。优先使用信号自带价格（若有）。
        price = getattr(signal, "price", None)
        if price is not None:
            price = round(float(price), 2)
        pos, realized_delta = self._update_position_local(signal, price=price)
        res = {
            "status": "paper_filled",
            "symbol": signal.symbol,
            "side": signal.side,
            "qty": signal.qty,
            "price": price,
        }
        if pos:
            res["position_qty"] = pos.qty
            res["avg_price"] = pos.avg_price
            self.logger.info(
                f"[PAPER POSITION] {pos.symbol} qty={pos.qty} avg_price={pos.avg_price}"
            )
        if realized_delta:
            self.realized_pnl_all += realized_delta
            self.realized_pnl_today += realized_delta
        self._maybe_log_trade(signal, price, pos)
        return res

    def _live_execute(self, signal: OrderSignal) -> dict:
        # 示例：现货市价单
        try:
            qty = self._validate_and_clip_qty(signal.symbol, signal.qty, price=signal.price)
            if self.max_price_deviation_pct and signal.price is not None:
                self._check_price_deviation(signal.symbol, signal.price)
        except ValueError as e:
            return {"status": "error", "error": str(e)}

        params = {
            "symbol": signal.symbol,
            "side": "BUY" if signal.side == "buy" else "SELL",
            "type": "MARKET",
            # qty 单位取决于交易所，V1.1 可以先写死或简单换算
            "quantity": qty,
        }
        try:
            res = self._request("POST", "/api/v3/order", params)
            self.logger.info(f"Order placed: {res}")
            # 使用成交均价（若返回 fills 列表则取第一条价格）
            price = self._extract_price(res)
            pos, realized_delta = self._update_position_local(signal, price=price)
            if realized_delta:
                self.realized_pnl_all += realized_delta
                self.realized_pnl_today += realized_delta
            self._maybe_log_trade(signal, price, pos)
            res["price_used"] = price
            return res
        except Exception as e:
            self.logger.error(f"Order failed: {e}")
            return {"status": "error", "error": str(e)}

    def _extract_price(self, order_res: dict) -> float | None:
        # 兼容 Binance 现货响应，优先 avgPrice 或 fills[0].price
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

    def sync_positions(self):
        """
        与交易所对账，刷新本地持仓（仅量，不含均价）。
        """
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
                positions[symbol] = Position(symbol=symbol, qty=qty, avg_price=self.positions.get(symbol, Position(symbol,0,0)).avg_price)
            self.positions = positions
            self.logger.info("Positions synced from exchange: %s", list(self.positions.keys()))
        except Exception as exc:
            self.logger.warning("sync_positions failed: %s", exc)

    def _update_position_local(self, signal: OrderSignal, price: float | None) -> tuple[Position | None, float]:
        """轻量更新本地持仓视图；返回 (持仓, 已实现盈亏变动)。"""
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
            # 现货/纸面默认不允许做空：只按可平仓数量减少持仓
            pos.qty = pos.qty - close_qty
            if pos.qty <= 0:
                pos.avg_price = 0.0
        elif signal.side == "flat":
            pos.qty = 0.0
            pos.avg_price = 0.0
        else:
            raise ValueError(f"Unsupported side: {signal.side}")

        if pos.qty <= 0:
            # 持仓清零则删除记录
            self.positions.pop(signal.symbol, None)
            return None, realized_delta

        self.positions[signal.symbol] = pos
        return pos, realized_delta

    def _maybe_log_trade(self, signal: OrderSignal, price: float | None, pos: Position | None):
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
        """
        根据配置或 exchangeInfo 的 min_notional/min_qty/qty_step 校验数量。
        若无法满足最小限制则报错。
        """
        if qty <= 0:
            raise ValueError("quantity must be positive")

        rule = self.symbol_rules.get(symbol, {})
        qty_step = rule.get("stepSize") or self.qty_step
        min_qty = rule.get("minQty") or self.min_qty
        min_notional = rule.get("minNotional") or self.min_notional

        adjusted_qty = qty
        if qty_step:
            adjusted_qty = math.floor(qty / qty_step) * qty_step
        if min_qty and adjusted_qty < min_qty:
            raise ValueError(f"quantity {adjusted_qty} < min_qty {min_qty}")
        if price is not None and min_notional and adjusted_qty * price < min_notional:
            raise ValueError(f"notional {adjusted_qty * price} < min_notional {min_notional}")
        return adjusted_qty

    def _check_price_deviation(self, symbol: str, price: float):
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

    def _load_symbol_rules(self):
        """
        拉取交易对规则，用于 minQty / stepSize / minNotional 校验。
        """
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
