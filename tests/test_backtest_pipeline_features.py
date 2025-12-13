from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from algo.factors.registry import apply_factors, build_factors
from shared.models.models import Tick
from algo.strategy.simple_ma import SimpleMAStrategy


def test_backtest_pipeline_injects_feature_cols_into_tick_features():
    ts0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    df = pd.DataFrame(
        [
            {"ts": ts0 + timedelta(hours=i), "symbol": "BTCUSDT", "open": p, "high": p, "low": p, "close": p, "volume": 1.0}
            for i, p in enumerate([1, 2, 3, 4, 5, 6])
        ]
    )
    factors = build_factors(
        [
            {"type": "ma", "window": 3, "price_col": "close", "out_col": "ma_short"},
            {"type": "ma", "window": 5, "price_col": "close", "out_col": "ma_long"},
        ]
    )
    df = apply_factors(df, factors)
    base_cols = {"ts", "symbol", "open", "high", "low", "close", "volume"}
    feature_cols = [c for c in df.columns if c not in base_cols]
    assert set(feature_cols) == {"ma_short", "ma_long"}

    row = df.iloc[-1]
    features = {c: float(row[c]) for c in feature_cols if pd.notna(row[c])}
    tick = Tick(symbol=str(row["symbol"]), price=float(row["close"]), ts=row["ts"], features=features or None)
    assert tick.features is not None
    assert "ma_short" in tick.features and "ma_long" in tick.features


def test_strategy_require_features_reads_tick_features():
    strat = SimpleMAStrategy(short_window=2, long_window=3, min_ma_diff=0.0, cooldown_secs=0, require_features=True)
    ts = datetime.now(timezone.utc)
    # 第一个 tick：short == long，不应产生信号
    t1 = Tick(symbol="BTCUSDT", price=101.0, ts=ts, features={"ma_short": 100.0, "ma_long": 100.0})
    assert strat.on_tick(t1) == []
    # 第二个 tick：短均线上穿长均线
    t2 = Tick(symbol="BTCUSDT", price=103.0, ts=ts, features={"ma_short": 102.0, "ma_long": 101.0})
    sigs = strat.on_tick(t2)
    assert len(sigs) == 1
    assert sigs[0].side == "buy"
