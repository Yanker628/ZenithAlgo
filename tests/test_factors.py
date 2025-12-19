from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from algo.factors.atr import ATRFactor
from algo.factors.ma import MAFactor
from algo.factors.rsi import RSIFactor
from algo.factors.ema import EMAFactor


def _df(prices: list[float]) -> pd.DataFrame:
    ts0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i, p in enumerate(prices):
        rows.append(
            {
                "ts": ts0 + timedelta(hours=i),
                "symbol": "BTCUSDT",
                "open": p,
                "high": p + 1,
                "low": p - 1,
                "close": p,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(rows)


def test_ma_factor_adds_column_and_nans_are_limited():
    df = _df([1, 2, 3, 4, 5])
    out = MAFactor(window=3, price_col="close", out_col="ma3").compute(df)
    assert "ma3" in out.columns
    assert out["ma3"].isna().sum() == 2
    assert abs(out["ma3"].iloc[-1] - 4.0) < 1e-9


def test_rsi_factor_outputs_in_0_100_after_warmup():
    df = _df([1, 2, 3, 2, 1, 2, 3, 4, 3, 2, 3, 4, 5, 6, 7])
    out = RSIFactor(period=5, price_col="close", out_col="rsi5").compute(df)
    s = out["rsi5"].dropna()
    assert not s.empty
    assert (s >= 0).all()
    assert (s <= 100).all()


def test_atr_factor_adds_column():
    df = _df([10, 11, 12, 11, 9, 10, 11])
    out = ATRFactor(period=3, out_col="atr3").compute(df)
    assert "atr3" in out.columns
    assert out["atr3"].isna().sum() == 2


def test_ema_factor_adds_column():
    df = _df([1, 2, 3, 4, 5])
    out = EMAFactor(period=3, out_col="ema3").compute(df)
    assert "ema3" in out.columns
    assert out["ema3"].isna().sum() == 2


def test_rsi_rust_matches_pandas():
    try:
        import zenithalgo_rust
    except Exception:
        zenithalgo_rust = None
    if zenithalgo_rust is None:
        return

    df = _df([1, 2, 3, 2, 1, 2, 3, 4, 3, 2, 3, 4, 5, 6, 7])
    series = df["close"].astype(float)
    period = 5
    rust_vals = zenithalgo_rust.rsi(series.to_list(), period)

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    pandas_vals = (100.0 - (100.0 / (1.0 + rs))).to_list()

    for rust_val, panda_val in zip(rust_vals, pandas_vals):
        if pd.isna(panda_val):
            assert np.isnan(rust_val)
        else:
            assert rust_val == panda_val


def test_atr_rust_matches_pandas():
    try:
        import zenithalgo_rust
    except Exception:
        zenithalgo_rust = None
    if zenithalgo_rust is None:
        return

    df = _df([10, 11, 12, 11, 9, 10, 11, 12])
    period = 3
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    rust_vals = zenithalgo_rust.atr(high.to_list(), low.to_list(), close.to_list(), period)

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    pandas_vals = tr.rolling(period, min_periods=period).mean().to_list()

    for rust_val, panda_val in zip(rust_vals, pandas_vals):
        if pd.isna(panda_val):
            assert np.isnan(rust_val)
        else:
            assert rust_val == panda_val
