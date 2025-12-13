"""统一下单规模（sizing）逻辑。

策略输出的 `OrderSignal` 只表达方向/理由，真实下单数量在这里统一计算。
实时/纸面/回测共用同一套 sizing 规则。
"""

from __future__ import annotations

from typing import Any

from broker.abstract_broker import Broker
from shared.models.models import OrderSignal
from algo.sizing.base import build_sizer


def resolve_sizing_cfg(cfg) -> dict[str, Any]:
    """解析 sizing 配置来源。

    Parameters
    ----------
    cfg:
        `AppConfig` 或等价对象。

    Returns
    -------
    dict[str, Any]
        sizing 配置字典。优先读取顶层 `cfg.sizing`，
        若缺省则回退到 `cfg.backtest.sizing`。
    """
    sizing = getattr(cfg, "sizing", None)
    if isinstance(sizing, dict):
        return sizing
    bt = getattr(cfg, "backtest", None)
    if isinstance(bt, dict):
        bt_sizing = bt.get("sizing")
        if isinstance(bt_sizing, dict):
            return bt_sizing
    return {}


def _max_qty_by_position_pct(
    position_pct: float,
    equity_base: float,
    price: float,
    current_qty: float,
) -> float:
    if position_pct <= 0 or equity_base <= 0 or price <= 0:
        return 0.0
    max_notional = equity_base * position_pct
    current_notional = abs(current_qty * price)
    remaining_notional = max(0.0, max_notional - current_notional)
    return remaining_notional / price if price > 0 else 0.0


def _max_qty_by_trade_notional(trade_notional: float, price: float) -> float:
    if trade_notional <= 0 or price <= 0:
        return 0.0
    return trade_notional / price


def size_signals(
    signals: list[OrderSignal],
    broker: Broker,
    sizing_cfg: dict[str, Any] | None,
    equity_base: float,
    logger=None,
) -> list[OrderSignal]:
    """对策略信号做统一下单规模计算。

    Parameters
    ----------
    signals:
        策略原始信号列表。允许 `qty<=0` 表示“只给方向”。
    broker:
        当前 broker，用于查询已有持仓。
    sizing_cfg:
        sizing 配置（position_pct/trade_notional）。
    equity_base:
        基准权益，用于计算持仓比例上限。
    logger:
        可选 logger，用于 debug 输出。

    Returns
    -------
    list[OrderSignal]
        已计算真实数量后的信号列表。

    Notes
    -----
    本函数会原地修改信号对象的 `qty` 字段。
    """
    if not signals:
        return []
    cfg = sizing_cfg or {}
    mode = str(cfg.get("type") or cfg.get("mode") or "").strip().lower()
    position_pct = cfg.get("position_pct")
    trade_notional = cfg.get("trade_notional")
    try:
        position_pct_f = float(position_pct) if position_pct is not None else None
    except Exception:
        position_pct_f = None
    try:
        trade_notional_f = float(trade_notional) if trade_notional is not None else None
    except Exception:
        trade_notional_f = None

    sized: list[OrderSignal] = []
    typed_sizer = None
    if mode:
        typed_sizer = build_sizer(cfg)

    for sig in signals:
        price = sig.price
        if price is None or price <= 0:
            if logger:
                logger.debug("Skip sizing: missing price for %s %s", sig.symbol, sig.side)
            continue

        pos = broker.get_position(sig.symbol)
        current_qty = pos.qty if pos else 0.0

        base_qty = sig.qty if sig.qty and sig.qty > 0 else None

        if sig.side == "buy":
            if typed_sizer is not None and mode:
                max_qty = typed_sizer.max_buy_qty(price=price, current_qty=current_qty, equity_base=equity_base)
                if max_qty <= 0:
                    continue
                if base_qty is None:
                    base_qty = max_qty
                target_qty = min(base_qty, max_qty)
                if target_qty <= 0:
                    continue
                sig.qty = target_qty
                sized.append(sig)
                continue

            max_qty_pos = None
            if position_pct_f is not None:
                max_qty_pos = _max_qty_by_position_pct(position_pct_f, equity_base, price, current_qty)
            max_qty_trade = (
                _max_qty_by_trade_notional(trade_notional_f, price)
                if trade_notional_f is not None
                else None
            )

            if base_qty is None:
                if max_qty_trade is not None and max_qty_trade > 0:
                    base_qty = max_qty_trade
                elif max_qty_pos is not None and max_qty_pos > 0:
                    base_qty = max_qty_pos
                else:
                    continue

            target_qty = base_qty
            if max_qty_pos is not None:
                target_qty = min(target_qty, max_qty_pos)
            if max_qty_trade is not None:
                target_qty = min(target_qty, max_qty_trade)

            if target_qty <= 0:
                continue
            sig.qty = target_qty
            sized.append(sig)
            continue

        if sig.side == "sell":
            # 现货/纸面默认不做空：无持仓则忽略
            if current_qty <= 0:
                continue
            if typed_sizer is not None and mode:
                max_qty = typed_sizer.max_sell_qty(price=price, current_qty=current_qty, equity_base=equity_base)
                if base_qty is None:
                    base_qty = current_qty
                target_qty = min(base_qty, current_qty)
                if max_qty > 0:
                    target_qty = min(target_qty, max_qty)
                if target_qty <= 0:
                    continue
                sig.qty = target_qty
                sized.append(sig)
                continue

            max_qty_trade = (
                _max_qty_by_trade_notional(trade_notional_f, price)
                if trade_notional_f is not None
                else None
            )
            if base_qty is None:
                base_qty = current_qty
            target_qty = min(base_qty, current_qty)
            if max_qty_trade is not None:
                target_qty = min(target_qty, max_qty_trade)
            if target_qty <= 0:
                continue
            sig.qty = target_qty
            sized.append(sig)
            continue

        # flat/其它 side：保持原 qty（若无 qty 则跳过）
        if base_qty is None or base_qty <= 0:
            continue
        sized.append(sig)

    return sized
