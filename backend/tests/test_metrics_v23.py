from __future__ import annotations

from datetime import datetime, timedelta, timezone

from zenith.analysis.metrics.metrics import compute_metrics


def test_metrics_include_v23_fields_and_drawdown_positive():
    ts0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    equity_curve = [
        (ts0, 100.0),
        (ts0 + timedelta(hours=1), 110.0),
        (ts0 + timedelta(hours=2), 90.0),
        (ts0 + timedelta(hours=3), 120.0),
    ]
    trades = [
        {"ts": ts0 + timedelta(hours=1), "side": "buy", "qty": 1.0, "slippage_price": 100.0, "realized_delta": 0.0},
        {"ts": ts0 + timedelta(hours=2), "side": "sell", "qty": 1.0, "slippage_price": 90.0, "realized_delta": -10.0},
        {"ts": ts0 + timedelta(hours=3), "side": "buy", "qty": 1.0, "slippage_price": 100.0, "realized_delta": 5.0},
    ]
    m = compute_metrics(equity_curve, trades)
    assert m["max_drawdown"] >= 0
    for k in ["profit_factor", "expectancy", "avg_trade_return", "std_trade_return", "exposure", "turnover"]:
        assert k in m

