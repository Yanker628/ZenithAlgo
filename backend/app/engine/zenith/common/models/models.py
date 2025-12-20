"""核心数据结构：Tick/Candle/OrderSignal/Position。"""

from dataclasses import dataclass
from datetime import datetime

@dataclass
class Tick:
    """市场 Tick（逐笔/简化成交）。"""
    symbol: str
    price: float
    ts: datetime
    features: dict[str, float] | None = None

@dataclass
class Candle:
    """K 线数据。"""
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
    """策略输出的订单信号。"""
    symbol: str
    side: str        # "buy" / "sell" / "flat"
    qty: float       # 数量或比例
    reason: str | None = None
    price: float | None = None  # 可选价格，供执行/日志使用
    client_order_id: str | None = None  # 幂等/去重：同一意图可预测且可重建

@dataclass
class Position:
    """持仓快照。"""
    symbol: str
    qty: float
    avg_price: float
