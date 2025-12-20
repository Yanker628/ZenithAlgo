from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from zenith.analysis.metrics.metrics import compute_metrics
from zenith.execution.execution.simulator import BacktestFillSimulator
from zenith.execution.execution.slippage_models import BpsSlippageModel
from zenith.data.store import DatasetStore
from zenith.core.backtest_engine import BacktestEngine
from zenith.core.sources.event_source import PandasFrameEventSource
from zenith.common.config.config_loader import BacktestConfig
from zenith.common.models.models import OrderSignal, Position
from zenith.strategies.risk.manager import RiskManager
from zenith.common.config.schema import RiskConfig
from zenith.common.utils.logging import setup_logger
from zenith.common.utils.sizer import resolve_sizing_cfg, size_signals


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


import numpy as np
from zenith.extensions.rust_wrapper import RustSimulator

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
    """向量化回测：使用 Rust 核心进行高速模拟。
    
    signals 输入字段：
    - ts: 信号触发时间
    - side: buy/sell
    - qty: (忽略，统一按 1 unit 或满仓计算，目前 Rust 模拟器简化为固定手数或全仓逻辑)
    - price: (忽略，统一按收盘价 close 执行)
    """
    bt_cfg = getattr(cfg_obj, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")
    
    
    # 1. 提取策略参数
    strategy = getattr(bt_cfg, "strategy", None) or getattr(cfg_obj, "strategy", None)
    params = dict(getattr(strategy, "params", {}) or {})

    if price_df.empty:
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    # 2. 调用 Rust 核心 (通过 Wrapper)
    # Wrapper 负责处理数据对齐、信号准备、ATR 计算以及模拟执行
    sim = RustSimulator()
    try:
        equity_data, trades_data = sim.simulate(price_df, signals, params)
    except Exception as e:
        print(f"Rust simulation failed: {e}")
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    # 3. 结果还原
    # equity_data: List[(ts_sec, equity)]
    equity_curve = [
        (datetime.fromtimestamp(ts, tz=timezone.utc), eq) 
        for ts, eq in equity_data
    ]
    
    # trades_data: List[(entry_ts, exit_ts, entry_px, exit_px, pnl, reason)]
    trades = []
    symbol = bt_cfg.symbol
    for (entry_ts, exit_ts, entry_px, exit_px, pnl, reason) in trades_data:
        trades.append({
            "symbol": symbol,
            "entry_ts": datetime.fromtimestamp(entry_ts, tz=timezone.utc),
            "exit_ts": datetime.fromtimestamp(exit_ts, tz=timezone.utc),
            "entry_price": entry_px,
            "exit_price": exit_px,
            "pnl": pnl,
            "realized_delta": pnl,  # 兼容 metrics 计算以获取 realized pnl
            "ts": datetime.fromtimestamp(exit_ts, tz=timezone.utc), # 兼容 metrics 计算 (交易时间)
            "qty": 1.0, # 简化: 固定 1 unit
            "reason": reason,
            "side": "long" if entry_px < exit_px else "short" # 简化推断方向，或者由 Rust 明确返回 side
        })
        
    metrics = compute_metrics(equity_curve, trades)
    return VectorBacktestResult(equity_curve=equity_curve, metrics=metrics, trades=trades)

class _PositionAdapter:
    """(已弃用) 最小 broker 适配器。"""
    pass

def run_ma_crossover_vectorized(cfg_obj, price_df: pd.DataFrame | None = None) -> VectorBacktestResult:
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

    if price_df is None:
        df = _build_price_frame(cfg_obj)
    else:
        df = price_df

    if df.empty:
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    close = df["close"].astype(float)
    short_ma = close.rolling(short_w, min_periods=short_w).mean()
    long_ma = close.rolling(long_w, min_periods=long_w).mean()

    # 简单策略：MA 交叉
    # 1 = Long (做多), 0 = Flat (平仓/观望) (对于简单 MA 策略通常不做空，除非特别指定)
    # Rust simulate_trades 支持 1 (Buy/Long) 和 -1 (Sell/Short)。
    # 信号生成逻辑:
    # 金叉 (短周期 > 长周期) -> Buy (1)
    # 死叉 (短周期 < 长周期) -> Sell (-1) (如果要做空或平仓)
    # 原始逻辑是: position = (s > l).astype(int). diff() -> 1 (Buy), -1 (Sell/Close)。
    
    position = (short_ma > long_ma).fillna(False).astype(int)
    change = position.diff().fillna(0) # 0=Hold, 1=Buy, -1=Sell

    # 我们直接生成 dense signal array 传递给 run_signal_vectorized?
    # 不，run_signal_vectorized 接受 signals DataFrame 或者 list.
    # 为了复用逻辑：
    
    signals = []
    end_ts_list = [pd.Timestamp(ts).to_pydatetime() for ts in df["end_ts"]]
    change_list = change.values
    
    for idx, delta in enumerate(change_list):
        if delta == 1:
            signals.append({"ts": end_ts_list[idx], "side": "buy"})
        elif delta == -1:
            signals.append({"ts": end_ts_list[idx], "side": "sell"})

    return run_signal_vectorized(cfg_obj, price_df=df, signals=signals)


def run_trend_filtered_vectorized(cfg_obj) -> VectorBacktestResult:
    """向量化回测：复用策略逻辑生成信号（trend_filtered 试点）。"""
    bt_cfg = getattr(cfg_obj, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")

    candles_df, feature_cols, _ = BacktestEngine._load_candles_and_features(cfg_obj, bt_cfg)
    if candles_df.empty:
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    strategy = BacktestEngine._build_strategy(cfg_obj, bt_cfg)
    source = PandasFrameEventSource(candles_df, feature_cols=feature_cols)

    signals: list[dict[str, Any]] = []
    # 这一步仍是 Python loop，如果策略逻辑很简单，建议也 sink 到 vector/rust
    # 但为了兼容复杂策略，这里先保留 Python 生成信号，Rust 负责撮合
    for tick in source.events():
        for sig in strategy.on_tick(tick):
            signals.append(
                {
                    "ts": tick.ts,
                    "side": sig.side,
                    "qty": float(sig.qty or 0.0),
                    "price": sig.price,
                }
            )

    price_df = candles_df.rename(columns={"ts": "end_ts"}).copy()
    price_df["end_ts"] = pd.to_datetime(price_df["end_ts"], utc=True)
    return run_signal_vectorized(cfg_obj, price_df=price_df, signals=signals)


def run_volatility_vectorized(cfg_obj, price_df: pd.DataFrame | None = None) -> VectorBacktestResult:
    """向量化回测：波动率突破 (Bollinger Breakout)。"""
    bt_cfg = getattr(cfg_obj, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")
    strategy = getattr(bt_cfg, "strategy", None) or getattr(cfg_obj, "strategy", None)
    params = dict(getattr(strategy, "params", {}) or {})
    
    window = int(params.get("window") or 20)
    k = float(params.get("k") or 2.0)
    
    if window <= 0:
        raise ValueError("vectorized volatility requires window > 0")

    if price_df is None:
        df = _build_price_frame(cfg_obj)
    else:
        df = price_df

    if df.empty:
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    # 转换为列表供 Rust 调用
    closes = df["close"].astype(float).values.tolist()
    
    # Rust 计算指标
    sim = RustSimulator()
    try:
        ma_vals = sim.calculate_indicators(closes, "ma", window)
        std_vals = sim.calculate_indicators(closes, "stddev", window)
    except Exception as e:
        print(f"Rust indicator calc failed: {e}")
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    # 转换回 Series 以便进行向量化逻辑处理
    ma_series = pd.Series(ma_vals, index=df.index)
    std_series = pd.Series(std_vals, index=df.index)
    
    upper = ma_series + k * std_series
    lower = ma_series - k * std_series
    close_series = df["close"].astype(float)
    
    # 逻辑:
    # 收盘价 > 上轨 -> Long (1)
    # 收盘价 < 下轨 -> Short (-1) (如果在允许做空的情况下，否则为平仓或观望?)
    # 目前假设是对称的：跌破下轨 = 做空。
    # Rust 模拟器的 "allow_short" 标志控制实际是否执行做空。
    # 但此处的生成逻辑决定了意图。
    
    # 我们希望实现类似状态机的行为：
    # 空仓 -> 向上突破 -> 做多
    # 持多 -> 向下突破? 或者有特定的退出条件?
    # Python 事件驱动策略逻辑:
    #   入场: > 上轨 (做多), < 下轨 (做空)
    #   出场: < MA (多头离场), > MA (空头离场)
    
    # 在没有循环或自定义 Rust 模拟逻辑的情况下，开发向量化状态机比较复杂。
    # 简化版向量化逻辑:
    # 仅在突破发生时产生 "Signal"。
    # 我们将突破直接映射为信号。
    
    # 突破信号
    long_signal = (close_series > upper)
    short_signal = (close_series < lower)
    
    # 出场信号 (均值回归)
    # exit_long = (close_series < ma_series)
    # exit_short = (close_series > ma_series)
    
    # 是否构建稠密信号数组?
    # 或者只生成入场信号，让 Rust 处理 "反转"?
    # ZenithAlgo Rust 模拟器处理如下:
    # Sig=1: 若空仓 -> 做多。若持空 -> 反手做多。
    # Sig=-1: 若空仓 -> 做空。若持多 -> 反手做空。
    # 它原本并不原生支持 "仅出场" (Sig=0 表示无动作)。
    
    # 所以如果我们想在 MA 交叉时出场，我们需要传递特定的 "Close" 意图?
    # 目前 Rust 模拟器逻辑:
    # if sig == 1: Long
    # if sig == -1: Short
    # 
    # 为了支持 "Exit"，我们暗示:
    # Long -> 想要变 Flat? 
    # Rust 模拟器除了通过 SL/TP 外，并不显式支持 "Go Flat" 指令。
    # 这是当前 `simulate_trades_v2` 的一个限制。
    # 
    # 权宜之计:
    # 为了与 Event Engine (具有 MA 出场) 的策略对齐，最理想是后续升级 Rust Sim。
    # 目前，我们为向量化优化实现纯 "反转" 逻辑，或者简单的 Stop/TP 逻辑。
    # 或者，我们只发出入场信号，依赖 SL/TP 出场?
    # 
    # 让我们与我编写的 Python Event 策略对齐:
    # Python Event: 多头跌破下轨 (反转)? 不，多头在 MA 交叉时出场。
    # 
    # 决策:
    # 对于本次向量化优化的迭代，我们简化处理:
    # 仅传递入场信号。出场通过 SL/TP。
    # 仅在突破发生瞬间生成信号。
    
    signals = []
    end_ts_list = [pd.Timestamp(ts).to_pydatetime() for ts in df["end_ts"]]
    
    # 为了减少噪音，仅在交叉 (Crossover) 时发信号?
    # 上穿上轨
    long_entry = (close_series > upper) & (close_series.shift(1) <= upper.shift(1))
    short_entry = (close_series < lower) & (close_series.shift(1) >= lower.shift(1))
    
    # 迭代并构建高效列表
    # 使用 numpy 加速
    long_idxs = np.where(long_entry)[0]
    short_idxs = np.where(short_entry)[0]
    
    for idx in long_idxs:
        signals.append({"ts": end_ts_list[idx], "side": "buy"})
    
    for idx in short_idxs:
        signals.append({"ts": end_ts_list[idx], "side": "sell"})
        
    return run_signal_vectorized(cfg_obj, price_df=df, signals=signals)
