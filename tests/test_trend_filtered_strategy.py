from __future__ import annotations

from datetime import datetime, timezone

from market.models import Tick
from strategy.trend_filter import TrendFilteredStrategy


def _tick(price: float, *, short_ma: float | None, long_ma: float | None, atr: float | None = None) -> Tick:
    features: dict[str, float] = {}
    if short_ma is not None:
        features["ma_short"] = short_ma
    if long_ma is not None:
        features["ma_long"] = long_ma
    if atr is not None:
        features["atr_14"] = atr
    return Tick(symbol="BTCUSDT", price=price, ts=datetime.now(timezone.utc), features=features or None)


def test_trend_filtered_entry_on_gold_cross_with_regime_and_slope():
    strat = TrendFilteredStrategy(slope_lookback=1, slope_threshold=0.1, require_features=True)
    assert strat.on_tick(_tick(101, short_ma=99, long_ma=100)) == []
    sigs = strat.on_tick(_tick(103, short_ma=102, long_ma=101))
    assert len(sigs) == 1
    assert sigs[0].side == "buy"


def test_trend_filtered_exit_on_atr_trailing_stop():
    strat = TrendFilteredStrategy(
        slope_lookback=1,
        slope_threshold=0.0,
        atr_stop_multiplier=2.0,
        require_features=True,
        stop_on_death_cross=False,
        stop_on_atr=True,
    )
    assert strat.on_tick(_tick(101, short_ma=99, long_ma=100, atr=1.0)) == []
    assert strat.on_tick(_tick(103, short_ma=102, long_ma=101, atr=1.0))[0].side == "buy"
    # 最高价 103，stop=103-2*1=101，价格跌破触发 sell
    sigs = strat.on_tick(_tick(100, short_ma=103, long_ma=102, atr=1.0))
    assert len(sigs) == 1
    assert sigs[0].side == "sell"
    assert sigs[0].reason == "atr_trailing_stop"


def test_trend_filtered_exit_on_death_cross_when_no_atr():
    strat = TrendFilteredStrategy(
        slope_lookback=1,
        slope_threshold=0.0,
        require_features=True,
        stop_on_death_cross=True,
        stop_on_atr=True,
    )
    assert strat.on_tick(_tick(101, short_ma=99, long_ma=100)) == []
    assert strat.on_tick(_tick(103, short_ma=102, long_ma=101))[0].side == "buy"
    sigs = strat.on_tick(_tick(104, short_ma=100, long_ma=101))
    assert len(sigs) == 1
    assert sigs[0].side == "sell"
    assert sigs[0].reason == "ma_death_cross"

