from __future__ import annotations

import numpy as np
import pandas as pd

from algo.factors.ma import MAFactor


def test_ma_factor_window_and_nan_convention():
    df = pd.DataFrame({"close": [100, 101, 102, 103, 104]})
    out = MAFactor(window=5).compute(df)
    assert "ma_5" in out.columns
    assert out["ma_5"].isna().sum() == 4
    assert abs(out["ma_5"].iloc[-1] - (100 + 101 + 102 + 103 + 104) / 5) < 1e-9


def test_ma_rust_matches_pandas():
    try:
        import zenithalgo_rust
    except Exception:
        zenithalgo_rust = None
    if zenithalgo_rust is None:
        return

    series = pd.Series([1, 2, 3, 4, 5, 6, 7])
    window = 3
    rust_vals = zenithalgo_rust.ma(series.astype(float).to_list(), window)
    pandas_vals = series.rolling(window, min_periods=window).mean().to_list()

    assert len(rust_vals) == len(pandas_vals)
    for rust_val, panda_val in zip(rust_vals, pandas_vals):
        if pd.isna(panda_val):
            assert np.isnan(rust_val)
        else:
            assert rust_val == panda_val
