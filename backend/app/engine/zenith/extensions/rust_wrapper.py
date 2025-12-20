"""Rust 模拟器封装层。

该模块负责处理 Python 数据结构到 Rust FFI 的转换，以及封装对 zenithalgo_rust 的调用。
"""

import numpy as np
import pandas as pd
import zenithalgo_rust
from typing import Any, Tuple, List, Dict, Iterable

class RustSimulator:
    """Rust 交易模拟器封装。"""

    def __init__(self):
        pass

    def calculate_indicators(self, closes: List[float], name: str, period: int) -> List[float]:
        """调用 Rust 计算通用指标。"""
        try:
            if name == "ma":
                return zenithalgo_rust.ma(closes, period)
            elif name == "stddev":
                return zenithalgo_rust.stddev(closes, period)
            elif name == "ema":
                return zenithalgo_rust.ema(closes, period)
            elif name == "rsi":
                return zenithalgo_rust.rsi(closes, period)
            else:
                raise ValueError(f"Unknown indicator: {name}")
        except Exception as e:
            # Re-raise with context
            raise RuntimeError(f"Rust indicator calculation failed for {name}: {e}") from e

    def calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int) -> List[float]:
        """可能直接调用 Rust ATR。"""
        try:
            return zenithalgo_rust.atr(highs, lows, closes, period)
        except Exception as e:
            raise RuntimeError(f"Rust ATR calculation failed: {e}") from e

    def simulate(
        self,
        price_df: pd.DataFrame,
        signals: Iterable[Dict[str, Any]] | pd.DataFrame,
        strategy_params: Dict[str, Any],
    ) -> Tuple[List[Tuple[int, float]], List[Tuple[int, int, float, float, float, str]]]:
        """执行 Rust 核心模拟。

        Args:
            price_df: 包含 open, high, low, close, end_ts 的数据框。
            signals: 信号列表或 DataFrame。
            strategy_params: 策略参数字典 (包含 stop_loss, atr_stop_multiplier 等)。

        Returns:
            equity_data: list of (timestamp, equity)
            trades_data: list of trade tuples
        """
        if price_df.empty:
            return [], []

        # 1. 数据对齐与准备
        df = price_df.sort_values("end_ts").reset_index(drop=True)
        if "end_ts" in df.columns:
            # Ensure proper datetime format if not already
            if not pd.api.types.is_datetime64_any_dtype(df["end_ts"]):
                 df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)
        
        # 2. 信号转换 (Signal to Dense Array)
        signal_array = self._prepare_signals(df, signals)

        # 3. 准备基础数据数组
        data_len = len(df)
        timestamps = df["end_ts"].astype("int64") // 10**9  # seconds
        opens = df["open"].astype(float).values
        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values

        # 4. 解析参数 / ATR预计算
        sl_val, tp_val, use_atr, atr_values = self._prepare_risk_params(
            highs, lows, closes, strategy_params, data_len
        )
        
        # 5. 调用 Rust 核心
        try:
            return zenithalgo_rust.simulate_trades(
                timestamps.tolist(),
                opens.tolist(),
                highs.tolist(),
                lows.tolist(),
                closes.tolist(),
                signal_array.tolist(),
                sl_val,
                tp_val,
                False, # allow_short (Default False for now, or extract from config if passed)
                use_atr,
                atr_values
            )
        except Exception as e:
            raise RuntimeError(f"Rust simulation failed: {e}") from e

    def _prepare_signals(self, price_df: pd.DataFrame, signals: Iterable[Dict[str, Any]] | pd.DataFrame) -> np.ndarray:
        """将稀疏信号转换为对齐的稠密数组。"""
        if isinstance(signals, pd.DataFrame):
            sig_df = signals.copy()
        else:
            sig_df = pd.DataFrame(list(signals))
        
        if sig_df.empty:
            return np.zeros(len(price_df), dtype=np.int32)
        
        if "ts" in sig_df.columns:
            if not pd.api.types.is_datetime64_any_dtype(sig_df["ts"]):
                sig_df["ts"] = pd.to_datetime(sig_df["ts"], utc=True)
        
        # Map side to int
        val_map = {"buy": 1, "sell": -1}
        sig_df["val"] = sig_df["side"].map(val_map).fillna(0).astype(int)
        
        # Merge to align with price index
        merged = price_df[["end_ts"]].merge(
            sig_df[["ts", "val"]], 
            left_on="end_ts", 
            right_on="ts", 
            how="left"
        )
        return merged["val"].fillna(0).astype(np.int32).values

    def _prepare_risk_params(
        self, 
        highs: np.ndarray, 
        lows: np.ndarray, 
        closes: np.ndarray, 
        params: Dict[str, Any],
        data_len: int
    ) -> Tuple[float, float, bool, List[float]]:
        """根据参数决定风控模式并计算 ATR。"""
        
        fixed_sl = float(params.get("stop_loss", 0.0))
        fixed_tp = float(params.get("take_profit", 0.0))
        
        atr_sl_mult = float(params.get("atr_stop_multiplier", 0.0))
        # atr_tp_mult = float(params.get("atr_tp_multiplier", 0.0)) # Reserved
        
        use_atr = False
        sl_val = fixed_sl
        tp_val = fixed_tp
        atr_values = [] # Empty if not used

        if atr_sl_mult > 0:
            use_atr = True
            sl_val = atr_sl_mult
            # In ATR mode, if fixed_tp is set, we currently have a mismatch as Rust expects ONE mode.
            # Assuming mixed mode is not supported yet, prioritizing ATR SL.
            
            atr_period = int(params.get("atr_period", 14))
            try:
                raw_atr = zenithalgo_rust.atr(
                    highs.tolist(), 
                    lows.tolist(), 
                    closes.tolist(), 
                    atr_period
                )
                # Handle NaNs: Rust returns NaN for warming up periods.
                # Replace NaNs with 0.0
                atr_values = [0.0 if np.isnan(x) else x for x in raw_atr]
            except Exception as e:
                # Log or re-raise? Ideally re-raise to detect config errors
                raise RuntimeError(f"Rust ATR calculation failed: {e}") from e
        
        if not use_atr:
            # Rust requires matching length vec even if unused? 
            # The signature is `atr: Vec<f64>`. 
            # Ideally passing empty vec is fine if use_atr is false, 
            # but let's check Rust implementation or safe side pass zeros.
            # Looking at previous code, we passed [0.0] * len.
             atr_values = [0.0] * data_len

        return sl_val, tp_val, use_atr, atr_values
