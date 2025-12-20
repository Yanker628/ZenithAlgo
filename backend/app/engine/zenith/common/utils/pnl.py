"""PnL 估算工具。"""

from zenith.common.models.models import Position


def estimate_pnl(positions: dict[str, Position], last_prices: dict[str, float]) -> float:
    """估算未实现 PnL。"""
    pnl = 0.0
    for symbol, pos in positions.items():
        last = last_prices.get(symbol)
        if last is None:
            continue
        pnl += pos.qty * (last - pos.avg_price)
    return pnl


def realized_delta(
    prev_positions: dict[str, Position], current_positions: dict[str, Position], last_prices: dict[str, float]
) -> float:
    """估算从 prev_positions 到 current_positions 的已实现 PnL 变动。"""
    delta = 0.0
    for symbol, prev in prev_positions.items():
        if prev.qty == 0:
            continue
        curr = current_positions.get(symbol)
        curr_qty = curr.qty if curr else 0.0
        if curr_qty == 0:
            last = last_prices.get(symbol)
            if last is None:
                continue
            delta += prev.qty * (last - prev.avg_price)
    return delta


def compute_unrealized_pnl(positions: dict[str, Position], last_prices: dict[str, float]) -> float:
    """计算未实现 PnL：sum(qty * (last_price - avg_price))。"""
    pnl = 0.0
    for symbol, pos in positions.items():
        price = last_prices.get(symbol)
        if price is None or pos.qty == 0:
            continue
        pnl += (price - pos.avg_price) * pos.qty
    return pnl
