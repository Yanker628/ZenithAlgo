from dataclasses import dataclass
from datetime import datetime

@dataclass
class Tick:
    symbol: str
    price: float
    ts: datetime

@dataclass
class Candle:
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    start_ts: datetime
    end_ts: datetime

@dataclass
class OrderSignal:
    symbol: str
    side: str        # "buy" / "sell" / "flat"
    qty: float       # 数量或比例
    reason: str | None = None
    price: float | None = None  # 可选价格，供执行/日志使用

@dataclass
class Position:
    symbol: str
    qty: float
    avg_price: float
