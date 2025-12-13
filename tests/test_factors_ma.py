from __future__ import annotations

import pandas as pd

from algo.factors.ma import MAFactor


def test_ma_factor_window_and_nan_convention():
    df = pd.DataFrame({"close": [100, 101, 102, 103, 104]})
    out = MAFactor(window=5).compute(df)
    assert "ma_5" in out.columns
    assert out["ma_5"].isna().sum() == 4
    assert abs(out["ma_5"].iloc[-1] - (100 + 101 + 102 + 103 + 104) / 5) < 1e-9

