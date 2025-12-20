from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest


def _assert_series_close(rust_vals: list[float], pandas_vals: list[float], *, tol: float = 1e-10) -> None:
    assert len(rust_vals) == len(pandas_vals)
    for rust_val, panda_val in zip(rust_vals, pandas_vals):
        if pd.isna(panda_val):
            assert math.isnan(rust_val)
        else:
            assert abs(rust_val - panda_val) <= tol


def _df(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": prices,
            "high": [p + 1 for p in prices],
            "low": [p - 1 for p in prices],
        }
    )


def test_rust_ma_parity():
    rust = pytest.importorskip("zenithalgo_rust")
    series = pd.Series([1, 2, 3, 4, 5, 6, 7], dtype=float)
    window = 3
    rust_vals = rust.ma(series.to_list(), window)
    pandas_vals = series.rolling(window, min_periods=window).mean().to_list()
    _assert_series_close(rust_vals, pandas_vals)


def test_rust_rsi_parity():
    rust = pytest.importorskip("zenithalgo_rust")
    series = pd.Series([1, 2, 3, 2, 1, 2, 3, 4, 3, 2, 3, 4, 5, 6, 7], dtype=float)
    period = 5
    rust_vals = rust.rsi(series.to_list(), period)

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    pandas_vals = (100.0 - (100.0 / (1.0 + rs))).to_list()
    _assert_series_close(rust_vals, pandas_vals)


def test_rust_atr_parity():
    rust = pytest.importorskip("zenithalgo_rust")
    df = _df([10, 11, 12, 11, 9, 10, 11, 12])
    period = 3
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    rust_vals = rust.atr(high.to_list(), low.to_list(), close.to_list(), period)

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    pandas_vals = tr.rolling(period, min_periods=period).mean().to_list()
    _assert_series_close(rust_vals, pandas_vals)


def test_rust_ema_parity():
    rust = pytest.importorskip("zenithalgo_rust")
    series = pd.Series([1, 2, 3, 4, 5, 6, 7], dtype=float)
    period = 3
    rust_vals = rust.ema(series.to_list(), period)
    pandas_vals = series.ewm(span=period, adjust=False, min_periods=period).mean().to_list()
    _assert_series_close(rust_vals, pandas_vals)
