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
    for t in trades:
        pnl = t.get("realized_delta") or 0.0
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
    return {
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_trades": total_trades,
    }


def compute_metrics(
    equity_curve: list[tuple[datetime, float]],
    trades: list[dict] | None = None,
) -> dict:
    """合并权益与交易指标。"""
    eq_metrics = compute_equity_metrics(equity_curve)
    trade_metrics = compute_trade_metrics(trades or [])
    return {**eq_metrics, **trade_metrics}
