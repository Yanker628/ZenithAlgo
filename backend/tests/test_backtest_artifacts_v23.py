from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone

from zenith.common.config.config_loader import AppConfig, ExchangeConfig, RiskConfig, StrategyConfig
from zenith.core.backtest_engine import BacktestEngine


def _write_candles_csv(path, *, symbol: str, interval: str, prices: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "open", "high", "low", "close", "volume", "start_ts", "end_ts"])
        for i, p in enumerate(prices):
            start = ts0 + timedelta(hours=i)
            end = start + timedelta(hours=1)
            w.writerow([symbol, p, p + 1, p - 1, p, 1.0, start.isoformat(), end.isoformat()])


def test_run_backtest_exports_trades_and_equity(tmp_path):
    symbol = "BTCUSDT"
    interval = "1h"
    data_dir = tmp_path / "history"
    candles_path = data_dir / f"{symbol}_{interval}.csv"
    _write_candles_csv(candles_path, symbol=symbol, interval=interval, prices=[1, 2, 3, 2, 1])

    cfg = AppConfig(
        exchange=ExchangeConfig(name="binance", base_url="https://api.binance.com"),
        risk=RiskConfig(max_position_pct=1.0, max_daily_loss_pct=1.0),
        symbol=symbol,
        timeframe=interval,
        equity_base=1000,
        mode="paper",
        strategy=StrategyConfig(type="simple_ma", params={}),
        backtest={
            "data_dir": str(data_dir),
            "symbol": symbol,
            "interval": interval,
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T06:00:00Z",
            "initial_equity": 1000,
            "auto_download": False,
            "quiet_risk_logs": True,
            "flatten_on_end": False,
            "fees": {"maker": 0.0, "taker": 0.0, "slippage_bp": 0.0},
            "strategy": {"short_window": 2, "long_window": 3, "min_ma_diff": 0.0, "cooldown_secs": 0},
            "sizing": {"type": "fixed_notional", "trade_notional": 200},
        },
        sizing=None,
    )

    out = tmp_path / "artifacts"
    summary = BacktestEngine(cfg_obj=cfg, artifacts_dir=out).run().summary
    assert (out / "trades.csv").exists()
    assert (out / "equity.csv").exists()
    assert summary.metrics.total_trades >= 1
