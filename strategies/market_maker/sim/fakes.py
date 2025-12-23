from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


class FakeClock:
    def __init__(self, start_ts: Optional[float] = None):
        self._ts = float(time.time() if start_ts is None else start_ts)

    def now(self) -> float:
        return self._ts

    def advance(self, seconds: float) -> float:
        self._ts += float(seconds)
        return self._ts


class FakePrecisionHelper:
    """
    Minimal PrecisionHelper replacement with no network access.
    """

    def __init__(
        self,
        *,
        price_decimals: int = 2,
        amount_decimals: int = 4,
        min_amount: float = 0.0001,
        min_cost: float = 5.0,
        price_tick: Optional[float] = None,
    ):
        self.price_decimals = int(price_decimals)
        self.amount_decimals = int(amount_decimals)
        self._min_amount = float(min_amount)
        self._min_cost = float(min_cost)
        self._price_tick = float(price_tick) if price_tick is not None else 10 ** (-self.price_decimals)

    def load_markets(self):
        return None

    def round_price(self, symbol: str, price: float) -> float:
        return round(float(price), self.price_decimals)

    def round_amount(self, symbol: str, amount: float) -> float:
        return round(float(amount), self.amount_decimals)

    def get_min_order_size(self, symbol: str) -> float:
        return self._min_amount

    def get_min_cost(self, symbol: str) -> float:
        return self._min_cost

    def get_price_tick(self, symbol: str) -> float:
        return self._price_tick

    def validate_order(self, symbol: str, price: float, amount: float) -> Tuple[bool, str]:
        price_f = float(price)
        amount_f = float(amount)
        if amount_f < self._min_amount:
            return False, f"数量太小: {amount_f} < {self._min_amount}"
        cost = price_f * amount_f
        if cost < self._min_cost:
            return False, f"订单价值太小: {cost} < {self._min_cost}"
        return True, "OK"


class FakeOracle:
    def __init__(self, symbols: List[str], clock: FakeClock):
        self.symbols = list(symbols)
        self.clock = clock
        self.running = False
        self.prices: Dict[str, Dict] = {}

    async def start(self):
        self.running = True

    def set_price(self, symbol: str, mid: float, *, bid: Optional[float] = None, ask: Optional[float] = None, ts: Optional[float] = None):
        mid_f = float(mid)
        if bid is None:
            bid = mid_f * 0.9999
        if ask is None:
            ask = mid_f * 1.0001
        self.prices[symbol] = {"mid": mid_f, "bid": float(bid), "ask": float(ask), "ts": float(ts if ts is not None else self.clock.now())}

    def get_price(self, symbol: str) -> Optional[Dict]:
        return self.prices.get(symbol)

    async def close(self):
        self.running = False


class FakeMexcMarketData:
    def __init__(self, symbols: List[str], clock: FakeClock):
        self.symbols = [s.replace("/", "") for s in symbols]
        self.clock = clock
        self.running = False
        self.orderbooks: Dict[str, Dict] = {}
        self._volatility: Dict[str, float] = {sym: 0.01 for sym in self.symbols}

    async def connect(self):
        self.running = True

    def set_orderbook(
        self,
        symbol: str,
        bid: float,
        ask: float,
        *,
        bid_qty: float = 1.0,
        ask_qty: float = 1.0,
        ts: Optional[float] = None,
    ):
        self.set_orderbook_levels(
            symbol,
            bids=[(float(bid), float(bid_qty))],
            asks=[(float(ask), float(ask_qty))],
            ts=ts,
        )

    def set_orderbook_levels(
        self,
        symbol: str,
        *,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        ts: Optional[float] = None,
    ):
        clean = symbol.replace("/", "")
        bids_sorted = sorted([(float(p), float(q)) for p, q in bids], key=lambda x: x[0], reverse=True)
        asks_sorted = sorted([(float(p), float(q)) for p, q in asks], key=lambda x: x[0])
        self.orderbooks[clean] = {
            "bids": [[p, q] for p, q in bids_sorted],
            "asks": [[p, q] for p, q in asks_sorted],
            "ts": float(ts if ts is not None else self.clock.now()),
        }

    def set_volatility(self, symbol: str, vol_pct: float):
        clean = symbol.replace("/", "")
        self._volatility[clean] = float(vol_pct)

    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        return self.orderbooks.get(symbol.replace("/", ""))

    def is_data_ready(self) -> bool:
        return bool(self.orderbooks)

    def get_data_age(self, symbol: str) -> float:
        ob = self.get_orderbook(symbol)
        if not ob:
            return float("inf")
        return self.clock.now() - float(ob.get("ts") or 0.0)

    def calculate_volatility(self, symbol: str) -> float:
        return float(self._volatility.get(symbol, 0.01))


@dataclass(frozen=True)
class FakeOrder:
    id: str
    symbol: str
    side: str  # "buy"|"sell"
    price: float
    amount: float
    ts: float
    filled: float = 0.0
    status: str = "open"


class FakeExecutor:
    """
    Simulates exchange order placement/cancel and basic maker fills.
    """

    def __init__(
        self,
        *,
        clock: FakeClock,
        inventory_manager=None,
        reject_rate_limit_every: int = 0,
        max_create_per_sec: int = 0,
        max_cancel_per_sec: int = 0,
        place_latency_s: float = 0.0,
        cancel_latency_s: float = 0.0,
    ):
        self.clock = clock
        self.inventory_manager = inventory_manager
        self.reject_rate_limit_every = int(reject_rate_limit_every)
        self.max_create_per_sec = int(max_create_per_sec)
        self.max_cancel_per_sec = int(max_cancel_per_sec)
        self.place_latency_s = float(place_latency_s)
        self.cancel_latency_s = float(cancel_latency_s)

        self.dry_run = False
        self.markets_loaded = True
        self.error_count = 0
        self.total_orders = 0
        self.total_filled = 0
        self.cancel_count = 0
        self.active_orders: Dict[str, List[str]] = {}
        self._orders: Dict[str, FakeOrder] = {}
        self._pending_orders: List[Tuple[float, FakeOrder]] = []
        self._pending_cancels: List[Tuple[float, str]] = []
        self._next_id = 1
        self.order_history: List[Dict] = []

        self.order_monitor = None
        self.exchange = self  # enough for OrderMonitor-style access if needed

        self._req_ts: Dict[str, List[float]] = {"create": [], "cancel": []}

    def _rate_limited(self, kind: str) -> bool:
        limit = self.max_create_per_sec if kind == "create" else self.max_cancel_per_sec
        if limit <= 0:
            return False
        now = self.clock.now()
        window = now - 1.0
        ts_list = [t for t in self._req_ts.get(kind, []) if t >= window]
        if len(ts_list) >= limit:
            self._req_ts[kind] = ts_list
            return True
        ts_list.append(now)
        self._req_ts[kind] = ts_list
        return False

    def _apply_pending(self):
        now = self.clock.now()

        if self._pending_cancels:
            due = [oid for ts, oid in self._pending_cancels if ts <= now]
            if due:
                for oid in due:
                    o = self._orders.get(oid)
                    if o and o.status == "open":
                        self._orders[oid] = FakeOrder(**{**o.__dict__, "status": "canceled"})  # type: ignore[attr-defined]
                        self.active_orders[o.symbol] = [x for x in self.active_orders.get(o.symbol, []) if x != oid]
                self._pending_cancels = [(ts, oid) for ts, oid in self._pending_cancels if ts > now]

        if self._pending_orders:
            ready = [o for ts, o in self._pending_orders if ts <= now]
            if ready:
                for order in ready:
                    self._orders[order.id] = order
                    self.active_orders.setdefault(order.symbol, []).append(order.id)
                self._pending_orders = [(ts, o) for ts, o in self._pending_orders if ts > now]

    async def initialize(self):
        return None

    async def close(self):
        return None

    async def cancel_all_orders(self, symbol: str):
        self.cancel_count += 1
        self._apply_pending()
        if self._rate_limited("cancel"):
            self.error_count += 1
            return
        ids = list(self.active_orders.get(symbol, []))
        cancel_at = self.clock.now() + self.cancel_latency_s
        for oid in ids:
            self._pending_cancels.append((cancel_at, oid))

    async def place_orders(self, symbol: str, bid_price: float, ask_price: float, quantity: float):
        self._apply_pending()
        try:
            bid = float(bid_price)
            ask = float(ask_price)
            qty = float(quantity)
            if not (qty > 0):
                return
            if bid >= ask:
                self.error_count += 1
                return
            self.total_orders += 2

            place_at = self.clock.now() + self.place_latency_s
            for side, price in (("buy", bid), ("sell", ask)):
                if self._rate_limited("create"):
                    self.error_count += 1
                    continue
                if self.reject_rate_limit_every and (self.total_orders % self.reject_rate_limit_every == 0):
                    self.error_count += 1
                    continue

                oid = f"FAKE-{self._next_id}"
                self._next_id += 1
                order = FakeOrder(id=oid, symbol=symbol, side=side, price=price, amount=qty, ts=self.clock.now())
                self._pending_orders.append((place_at, order))
                self.order_history.append({"time": self.clock.now(), "symbol": symbol, "side": side, "price": price, "bid": bid, "ask": ask})
        except Exception:
            self.error_count += 1

    def open_orders(self, symbol: str) -> List[FakeOrder]:
        self._apply_pending()
        return [self._orders[oid] for oid in self.active_orders.get(symbol, []) if oid in self._orders and self._orders[oid].status == "open"]

    def match_and_fill(
        self,
        symbol: str,
        *,
        market_bids: List[Tuple[float, float]],
        market_asks: List[Tuple[float, float]],
        fill_fraction: float = 1.0,
    ):
        """
        Very simple fill model:
        - buy fills if market_ask <= our buy price (price moved down)
        - sell fills if market_bid >= our sell price (price moved up)
        """
        self._apply_pending()
        fill_fraction = max(0.0, min(1.0, float(fill_fraction)))
        if not market_bids or not market_asks:
            return
        market_bid = float(market_bids[0][0])
        market_ask = float(market_asks[0][0])

        for order in list(self.open_orders(symbol)):
            should_fill = (order.side == "buy" and float(market_ask) <= order.price) or (
                order.side == "sell" and float(market_bid) >= order.price
            )
            if not should_fill:
                continue
            # Depth-limited partial fill: only a fraction of touch liquidity available.
            if order.side == "buy":
                touch_qty = sum(q for p, q in market_asks if float(p) <= order.price)
            else:
                touch_qty = sum(q for p, q in market_bids if float(p) >= order.price)
            filled_qty = min(order.amount, float(touch_qty) * fill_fraction)
            if filled_qty <= 0:
                continue

            self.total_filled += 1
            new_status = "closed" if math.isclose(filled_qty, order.amount) or filled_qty >= order.amount else "open"
            self._orders[order.id] = FakeOrder(**{**order.__dict__, "filled": filled_qty, "status": new_status})  # type: ignore[attr-defined]

            if self.inventory_manager and hasattr(self.inventory_manager, "apply_fill"):
                self.inventory_manager.apply_fill(symbol, order.side, filled_qty, order.price)

            if new_status != "open":
                self.active_orders[symbol] = [oid for oid in self.active_orders.get(symbol, []) if oid != order.id]


@dataclass(frozen=True)
class ScenarioStep:
    dt: float
    oracle_mid: float
    mexc_bid: float
    mexc_ask: float
    mexc_bids: Optional[List[Tuple[float, float]]] = None
    mexc_asks: Optional[List[Tuple[float, float]]] = None
    oracle_age: float = 0.0
    orderbook_age: float = 0.0
    volatility_pct: float = 0.01
    fill_fraction: float = 0.0
