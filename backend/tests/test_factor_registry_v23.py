from __future__ import annotations

import pandas as pd
import pytest

from zenith.strategies.factors.registry import apply_factors, build_factors


def test_build_factors_accepts_flat_params():
    spec = [{"type": "ma", "window": 5, "price_col": "close"}]
    factors = build_factors(spec)
    df = pd.DataFrame({"close": [1, 2, 3, 4, 5]})
    out = apply_factors(df, factors)
    assert "ma_5" in out.columns


def test_build_factors_accepts_params_dict():
    spec = [{"name": "ma", "params": {"window": 3, "price_col": "close", "out_col": "ma3"}}]
    factors = build_factors(spec)
    df = pd.DataFrame({"close": [1, 2, 3, 4, 5]})
    out = apply_factors(df, factors)
    assert "ma3" in out.columns


def test_build_factors_missing_required_param_raises_value_error():
    spec = [{"type": "ma", "price_col": "close"}]
    with pytest.raises(ValueError):
        build_factors(spec)

