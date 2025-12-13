from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.config.config_loader import AppConfig, ExchangeConfig, RiskConfig, StrategyConfig
from utils.param_search import grid_search


def _write_candles_csv(path: Path, *, symbol: str, interval: str, prices: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "open", "high", "low", "close", "volume", "start_ts", "end_ts"])
        for i, p in enumerate(prices):
            start = ts0 + timedelta(hours=i)
            end = start + timedelta(hours=1)
            w.writerow([symbol, p, p + 1, p - 1, p, 1.0, start.isoformat(), end.isoformat()])


def test_sweep_writes_score_and_filters_set_blocked_score(tmp_path):
    symbol = "BTCUSDT"
    interval = "1h"
    data_dir = tmp_path / "history"
    _write_candles_csv(data_dir / f"{symbol}_{interval}.csv", symbol=symbol, interval=interval, prices=[1, 2, 3, 2, 1, 2, 3])

    cfg = AppConfig(
        exchange=ExchangeConfig(name="binance", base_url="https://api.binance.com"),
        risk=RiskConfig(max_position_pct=1.0, max_daily_loss_pct=1.0),
        symbol=symbol,
        timeframe=interval,
        equity_base=1000,
        mode="paper",
        strategy=StrategyConfig(type="simple_ma", params={"min_ma_diff": 0.0, "cooldown_secs": 0}),
        backtest={
            "data_dir": str(data_dir),
            "symbol": symbol,
            "interval": interval,
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T10:00:00Z",
            "initial_equity": 1000,
            "auto_download": False,
            "quiet_risk_logs": True,
            "flatten_on_end": False,
            "fees": {"maker": 0.0, "taker": 0.0, "slippage_bp": 0.0},
        },
        sizing={"type": "fixed_notional", "trade_notional": 200},
    )

    out_csv = tmp_path / "sweep.csv"
    results = grid_search(
        cfg_path="config/config.yml",
        param_grid={"short_window": [2, 5], "long_window": [3, 50]},
        objective_weights={"total_return": 1.0, "sharpe": 0.0, "max_drawdown": 0.0},
        output_csv=str(out_csv),
        cfg_obj=cfg,
        filters={"min_trades": 1},
    )
    assert out_csv.exists()
    assert len(results) == 4

    # long_window=50 -> features 全 NaN -> require_features 策略不交易 -> 应被标记为 passed=false（filter_reason=min_trades）
    blocked = [r for r in results if r.params["long_window"] == 50]
    assert blocked
    assert all((not r.passed) and (r.filter_reason is not None) for r in blocked)

    # CSV 应包含 score 列
    with out_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        row = next(iter(reader))
        assert "score" in row
