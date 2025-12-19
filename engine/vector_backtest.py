from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from analysis.metrics.metrics import compute_metrics
from broker.execution.simulator import BacktestFillSimulator
from broker.execution.slippage_models import BpsSlippageModel
from database.dataset_store import DatasetStore
from shared.config.config_loader import BacktestConfig
from shared.models.models import OrderSignal, Position
from algo.risk.manager import RiskManager
from shared.config.schema import RiskConfig
from shared.utils.logging import setup_logger
from utils.sizer import resolve_sizing_cfg, size_signals


def _parse_iso(val: str) -> datetime:
    dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts(val: Any) -> datetime:
    if isinstance(val, datetime):
        dt = val
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return _parse_iso(str(val))


def _build_price_frame(cfg_obj) -> pd.DataFrame:
    bt_cfg = getattr(cfg_obj, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")
    store = DatasetStore(bt_cfg.data_dir)
    df = store.load_frame(bt_cfg.symbol, bt_cfg.interval)
    if df.empty:
        return df
    df = df.sort_values("end_ts").reset_index(drop=True)
    start_ts = _parse_iso(bt_cfg.start)
    end_ts = _parse_iso(bt_cfg.end)
    df = df[(df["end_ts"] >= start_ts) & (df["end_ts"] <= end_ts)]
    if "end_ts" in df.columns:
        df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)
    return df


@dataclass
class VectorBacktestResult:
    equity_curve: list[tuple[datetime, float]]
    metrics: dict[str, Any]
    trades: list[dict]


def run_signal_vectorized(
    cfg_obj,
    *,
    price_df: pd.DataFrame,
    signals: Iterable[dict[str, Any]] | pd.DataFrame,
) -> VectorBacktestResult:
    """向量化回测：使用外部 signals 进行撮合模拟。

    signals 输入字段：
    - ts: 信号时间
    - side: buy/sell
    - qty: 下单数量（可选；为 0 时由 sizing 决定）
    - price: 可选价格（为空则用当前 bar 收盘价）
    """
    bt_cfg = getattr(cfg_obj, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")

    logger = setup_logger("vector-backtest")
    equity_base = float(bt_cfg.initial_equity or 10000.0)
    cash = float(equity_base)
    position: Position | None = None
    trades: list[dict] = []
    equity_curve: list[tuple[datetime, float]] = []

    fee_rate = float(getattr(bt_cfg.fees, "taker", 0.0))
    slippage_bp = float(getattr(bt_cfg.fees, "slippage_bp", 0.0))
    simulator = BacktestFillSimulator(fee_rate=fee_rate, slippage=BpsSlippageModel(slippage_bp))

    sizing_cfg = resolve_sizing_cfg(cfg_obj)
    risk_cfg = getattr(cfg_obj, "risk", None)
    if risk_cfg is None:
        risk_cfg = RiskConfig()
    risk = RiskManager(risk_cfg, suppress_warnings=True, equity_base=equity_base)
    current_day = None
    day_start_equity = equity_base

    if isinstance(signals, pd.DataFrame):
        signals_iter = signals.to_dict(orient="records")
    else:
        signals_iter = list(signals)

    # 预处理信号：按时间排序
    normalized: list[dict[str, Any]] = []
    for s in signals_iter:
        ts = _parse_ts(s.get("ts"))
        side = str(s.get("side") or "").lower()
        if side not in {"buy", "sell"}:
            continue
        qty = float(s.get("qty") or 0.0)
        price = s.get("price")
        normalized.append({"ts": ts, "side": side, "qty": qty, "price": price})
    normalized.sort(key=lambda x: x["ts"])

    # 信号按 ts 分组，方便在 bar 内执行
    signals_by_ts: dict[datetime, list[dict[str, Any]]] = {}
    for s in normalized:
        signals_by_ts.setdefault(s["ts"], []).append(s)

    if price_df.empty:
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    price_df = price_df.sort_values("end_ts").reset_index(drop=True)
    price_df["end_ts"] = pd.to_datetime(price_df["end_ts"], utc=True)

    for _, row in price_df.iterrows():
        ts = _parse_ts(row["end_ts"])
        price = float(row["close"])

        # 日切换处理
        if current_day is None:
            current_day = ts.date()
        elif ts.date() != current_day:
            current_day = ts.date()
            day_start_equity = cash + (position.qty * price if position else 0.0)
            risk.reset_daily_state(log=False)

        # 执行该时间点的所有信号
        for sig in signals_by_ts.get(ts, []):
            signal_price = float(sig.get("price") or price)
            signal = OrderSignal(
                symbol=bt_cfg.symbol,
                side=sig["side"],
                qty=float(sig.get("qty") or 0.0),
                price=signal_price,
            )
            sized = size_signals([signal], _PositionAdapter(position), sizing_cfg, equity_base, logger=logger) # type: ignore
            if not sized:
                continue
            filtered = risk.filter_signals(sized)
            if not filtered:
                continue
            for order in filtered:
                fill = simulator.fill(
                    signal=order,
                    raw_price=signal_price,
                    cash=cash,
                    position=position,
                )
                if fill.status != "filled":
                    continue
                cash = fill.cash
                position = fill.position
                trades.append(
                    {
                        "ts": ts,
                        "symbol": bt_cfg.symbol,
                        "side": order.side,
                        "qty": fill.exec_qty,
                        "price": fill.raw_price,
                        "slippage_price": fill.exec_price,
                        "fee": fill.fee_paid,
                        "realized_delta": fill.realized_delta,
                    }
                )

        equity = cash + (position.qty * price if position else 0.0)
        equity_curve.append((ts, equity))
        daily_pnl = (equity - day_start_equity) / equity_base if equity_base else 0.0
        risk.set_daily_pnl(daily_pnl)

    metrics = compute_metrics(equity_curve, trades)
    return VectorBacktestResult(equity_curve=equity_curve, metrics=metrics, trades=trades)


class _PositionAdapter:
    """最小 broker 适配器：仅提供 get_position 供 sizing 使用。"""

    def __init__(self, position: Position | None):
        self._position = position

    def get_position(self, symbol: str) -> Position | None:
        if self._position and self._position.symbol == symbol:
            return self._position
        return None


def run_ma_crossover_vectorized(cfg_obj) -> VectorBacktestResult:
    """向量化回测：基于 MA 金叉/死叉的 long-only 模型。"""
    bt_cfg = getattr(cfg_obj, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")
    strategy = getattr(bt_cfg, "strategy", None) or getattr(cfg_obj, "strategy", None)
    params = dict(getattr(strategy, "params", {}) or {})
    short_w = int(params.get("short_window") or 0)
    long_w = int(params.get("long_window") or 0)
    if short_w <= 0 or long_w <= 0:
        raise ValueError("vectorized backtest requires short_window/long_window > 0")

    df = _build_price_frame(cfg_obj)
    if df.empty:
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    close = df["close"].astype(float)
    short_ma = close.rolling(short_w, min_periods=short_w).mean()
    long_ma = close.rolling(long_w, min_periods=long_w).mean()

    position = (short_ma > long_ma).fillna(False).astype(int)
    change = position.diff().fillna(position) # type: ignore

    signals = []
    for idx, delta in enumerate(change.to_list()):
        ts = df["end_ts"].iloc[idx].to_pydatetime()
        if delta == 1:
            signals.append({"ts": ts, "side": "buy", "qty": 0.0})
        elif delta == -1:
            signals.append({"ts": ts, "side": "sell", "qty": 0.0})

    return run_signal_vectorized(cfg_obj, price_df=df, signals=signals)
