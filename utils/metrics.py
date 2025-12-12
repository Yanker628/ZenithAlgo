"""回测绩效指标计算。"""

from __future__ import annotations

import math
from datetime import datetime
from statistics import mean, median, pstdev
from typing import Iterable


def _annualization_factor(equity_curve: list[tuple[datetime, float]]) -> float:
    """根据 equity_curve 的时间间隔估计 Sharpe 年化因子。"""
    if len(equity_curve) < 2:
        return math.sqrt(365)
    equity_curve = sorted(equity_curve, key=lambda x: x[0])
    deltas = []
    for i in range(1, len(equity_curve)):
        dt = (equity_curve[i][0] - equity_curve[i - 1][0]).total_seconds()
        if dt > 0:
            deltas.append(dt)
    if not deltas:
        return math.sqrt(365)
    med = median(deltas)
    periods_per_day = 86400 / med if med > 0 else 1
    return math.sqrt(365 * periods_per_day)


def compute_equity_metrics(equity_curve: list[tuple[datetime, float]]) -> dict:
    """计算权益曲线指标（总收益、最大回撤、Sharpe）。"""
    if not equity_curve:
        return {"total_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}

    equity_curve = sorted(equity_curve, key=lambda x: x[0])
    initial_equity = equity_curve[0][1]
    final_equity = equity_curve[-1][1]
    total_return = (final_equity / initial_equity - 1) if initial_equity else 0.0

    # 最大回撤
    peak = equity_curve[0][1]
    max_dd = 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        dd = (eq - peak) / peak if peak else 0.0
        max_dd = min(max_dd, dd)

    # 简单 Sharpe：按日收益率（或相邻点收益率）均值/标准差，年化因子默认按 365 天 （加密货币7*24）
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1][1]
        curr = equity_curve[i][1]
        if prev > 0:
            returns.append((curr / prev) - 1)
    sharpe = 0.0
    if returns:
        mu = mean(returns)
        sigma = pstdev(returns) if len(returns) > 1 else 0.0
        factor = _annualization_factor(equity_curve)
        sharpe = (mu / sigma) * factor if sigma else 0.0

    return {"total_return": total_return, "max_drawdown": abs(max_dd), "sharpe": sharpe}


def compute_trade_metrics(trades: Iterable[dict]) -> dict:
    """计算交易维度指标（胜率、均值盈亏、交易数）。"""
    wins = []
    losses = []
    pnls = []
    trade_returns = []
    notionals = []
    trade_times: list[datetime] = []
    signed_qtys: list[float] = []
    for t in trades:
        pnl = t.get("realized_delta") or 0.0
        qty = t.get("qty") or 0.0
        price = t.get("slippage_price") or t.get("price") or 0.0
        side = str(t.get("side") or "").lower()
        ts = t.get("ts")
        if isinstance(ts, datetime):
            trade_times.append(ts)
        if side == "buy":
            signed_qtys.append(float(qty))
        elif side == "sell":
            signed_qtys.append(-float(qty))
        else:
            signed_qtys.append(0.0)

        notional = abs(float(qty) * float(price)) if qty and price else 0.0
        notionals.append(notional)
        if notional > 0:
            trade_returns.append(float(pnl) / notional)
        pnls.append(float(pnl))
        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(pnl)
    win_count = len(wins)
    loss_count = len(losses)
    total_trades = win_count + loss_count
    win_rate = win_count / total_trades if total_trades else 0.0
    avg_win = mean(wins) if wins else 0.0
    avg_loss = -mean(losses) if losses else 0.0
    total_profit = sum(wins) if wins else 0.0
    total_loss_abs = abs(sum(losses)) if losses else 0.0
    profit_factor = (
        (total_profit / total_loss_abs)
        if total_loss_abs > 0
        else (float("inf") if total_profit > 0 else 0.0)
    )
    expectancy = mean(pnls) if pnls and total_trades else 0.0
    avg_trade_return = mean(trade_returns) if trade_returns else 0.0
    std_trade_return = pstdev(trade_returns) if len(trade_returns) > 1 else 0.0
    return {
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_trades": total_trades,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "avg_trade_return": avg_trade_return,
        "std_trade_return": std_trade_return,
    }


def compute_metrics(
    equity_curve: list[tuple[datetime, float]],
    trades: list[dict] | None = None,
) -> dict:
    """合并权益与交易指标。"""
    eq_metrics = compute_equity_metrics(equity_curve)
    trade_metrics = compute_trade_metrics(trades or [])

    # exposure / turnover（基于成交时点粗略估计）
    exposure = 0.0
    turnover = 0.0
    if trades:
        trade_points = []
        for t in trades:
            ts = t.get("ts")
            if isinstance(ts, datetime):
                trade_points.append(t)
        trade_points.sort(key=lambda x: x["ts"])
        if trade_points:
            start_ts = trade_points[0]["ts"]
            end_ts = equity_curve[-1][0] if equity_curve else trade_points[-1]["ts"]
            if isinstance(start_ts, datetime) and isinstance(end_ts, datetime) and end_ts > start_ts:
                held = 0.0
                pos_qty = 0.0
                prev_ts = start_ts
                for t in trade_points:
                    ts = t["ts"]
                    if not isinstance(ts, datetime):
                        continue
                    dt = (ts - prev_ts).total_seconds()
                    if pos_qty != 0:
                        held += max(0.0, dt)
                    side = str(t.get("side") or "").lower()
                    qty = float(t.get("qty") or 0.0)
                    if side == "buy":
                        pos_qty += qty
                    elif side == "sell":
                        pos_qty -= qty
                    prev_ts = ts
                dt_end = (end_ts - prev_ts).total_seconds()
                if pos_qty != 0:
                    held += max(0.0, dt_end)
                total = (end_ts - start_ts).total_seconds()
                exposure = held / total if total > 0 else 0.0

        total_notional = 0.0
        for t in trades:
            qty = float(t.get("qty") or 0.0)
            px = float(t.get("slippage_price") or t.get("price") or 0.0)
            total_notional += abs(qty * px)
        if equity_curve:
            equities = [eq for _, eq in equity_curve if eq and eq > 0]
            denom = mean(equities) if equities else 0.0
        else:
            denom = 0.0
        turnover = (total_notional / denom) if denom > 0 else 0.0

    return {**eq_metrics, **trade_metrics, "exposure": exposure, "turnover": turnover}
