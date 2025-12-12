from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from factors.atr import ATRFactor
from factors.ma import MAFactor
from factors.rsi import RSIFactor


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

