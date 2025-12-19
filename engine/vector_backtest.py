from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from analysis.metrics.metrics import compute_metrics
from broker.execution.simulator import BacktestFillSimulator
from broker.execution.slippage_models import BpsSlippageModel
from database.dataset_store import DatasetStore
from engine.backtest_engine import BacktestEngine
from engine.sources.event_source import PandasFrameEventSource
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


import numpy as np
from engine.simulation.rust_wrapper import RustSimulator

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
    - ts: 信号时间
    - side: buy/sell
    - qty: (忽略，统一按 1 unit 或满仓计算，目前 Rust 模拟器简化为固定手数或全仓逻辑)
    - price: (忽略，统一按 close)
    """
    bt_cfg = getattr(cfg_obj, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")
    
    
    # 提取策略参数
    strategy = getattr(bt_cfg, "strategy", None) or getattr(cfg_obj, "strategy", None)
    params = dict(getattr(strategy, "params", {}) or {})

    if price_df.empty:
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    # 2. 调用 Rust 核心 (Via Wrapper)
    # Wrapper handles data alignment, signal prep, ATR calc, and simulation.
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
            "realized_delta": pnl,  # 兼容 metrics 计算
            "ts": datetime.fromtimestamp(exit_ts, tz=timezone.utc), # 兼容 metrics 计算
            "qty": 1.0, # 简化: 固定 1 unit
            "reason": reason,
            "side": "long" if entry_px < exit_px else "short" # 简化推断，或 Rust 返回 side
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

    # 简单策略：MA Cross
    # 1 = Long, 0 = Flat (no short for simple ma unless specified)
    # Rust simulate_trades supports 1 (Buy) and -1 (Sell/Short).
    # Generation logic:
    # Cross Over (Short > Long) -> Buy (1)
    # Cross Under (Short < Long) -> Sell (-1) if we want to reverse or flat?
    # Original logic was: position = (s > l).astype(int). diff() -> 1 (Buy), -1 (Sell/Close).
    
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

    # Convert to list for Rust
    closes = df["close"].astype(float).values.tolist()
    
    # Rust Calculation
    sim = RustSimulator()
    try:
        ma_vals = sim.calculate_indicators(closes, "ma", window)
        std_vals = sim.calculate_indicators(closes, "stddev", window)
    except Exception as e:
        print(f"Rust indicator calc failed: {e}")
        return VectorBacktestResult(equity_curve=[], metrics={}, trades=[])

    # Convert back to Series for vectorized logic
    ma_series = pd.Series(ma_vals, index=df.index)
    std_series = pd.Series(std_vals, index=df.index)
    
    upper = ma_series + k * std_series
    lower = ma_series - k * std_series
    close_series = df["close"].astype(float)
    
    # Logic:
    # Close > Upper -> Long (1)
    # Close < Lower -> Short (-1) if allow_short, else Flat (0) or Short (-1)?
    # For now, let's assume symmetry: Break Down = Short.
    # Rust simulator "allow_short" flag controls if Short is actually taken.
    # But generation logic here determines intent.
    
    # We want a state machine behavior:
    # Flat -> Break Up -> Long
    # Long -> Break Down? Or specific exit?
    # Python Event strategy logic:
    #   Entry: > Upper (Long), < Lower (Short)
    #   Exit: < MA (Exit Long), > MA (Exit Short)
    
    # Developing vectorized state machine is complex without a loop or custom Rust sim.
    # Simplified Vector Logic:
    # Use "Signal" only on breakout.
    # Let's map breakout directly to signals.
    
    # Breakout signals
    long_signal = (close_series > upper)
    short_signal = (close_series < lower)
    
    # Exit signals (Mean Reversion)
    # exit_long = (close_series < ma_series)
    # exit_short = (close_series > ma_series)
    
    # Construct a dense signal array?
    # Or just generate entry signals and let Rust handle "Flip"?
    # ZenithAlgo Rust Sim handles:
    # Sig=1: if Flat -> Long. If Short -> Flip to Long.
    # Sig=-1: if Flat -> Short. If Long -> Flip to Short.
    # It doesn't natively handle "Exit Only" (Sig=0 is No Action).
    
    # So if we want to Exit on MA Cross, we need to pass specific "Close" intent?
    # Currently Rust sim logic:
    # if sig == 1: Long
    # if sig == -1: Short
    # 
    # To support "Exit", we imply:
    # Long -> wants to become Flat? 
    # Rust sim doesn't explicitly support "Go Flat" command (except via SL/TP).
    # This is a limitation of current `simulate_trades_v2`.
    # 
    # Workaround:
    # For Strategy Parity with Event Engine (which has MA Exit), we should ideally upgrade Rust Sim later.
    # For now, let's implement pure "Reversal" logic for Vector or simpler Stop/TP logic.
    # Or, we only emit entry signals and rely on SL/TP for exit?
    # 
    # Let's align with the Python Event Strategy I wrote:
    # Python Event: Long breaks Lower (Reversal)? No, Long exits on MA Cross.
    # 
    # Decision:
    # For this iteration of Vector optimization, we can simplify:
    # Only Entry Signals are passed. Exit is via SL/TP.
    # Signals are generated only when breakout happens.
    
    signals = []
    end_ts_list = [pd.Timestamp(ts).to_pydatetime() for ts in df["end_ts"]]
    
    # To reduce noise, only signal on crossover?
    # Cross Over Upper
    long_entry = (close_series > upper) & (close_series.shift(1) <= upper.shift(1))
    short_entry = (close_series < lower) & (close_series.shift(1) >= lower.shift(1))
    
    # Iterate and build efficient list
    # Use numpy for speed
    long_idxs = np.where(long_entry)[0]
    short_idxs = np.where(short_entry)[0]
    
    for idx in long_idxs:
        signals.append({"ts": end_ts_list[idx], "side": "buy"})
    
    for idx in short_idxs:
        signals.append({"ts": end_ts_list[idx], "side": "sell"})
        
    return run_signal_vectorized(cfg_obj, price_df=df, signals=signals)
