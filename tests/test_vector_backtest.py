from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from shared.config.config_loader import BacktestConfig
from engine.vector_backtest import run_ma_crossover_vectorized, run_signal_vectorized


def test_vector_backtest_ma_basic(tmp_path):
    df = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"] * 6,
            "open": [1, 2, 3, 4, 5, 6],
            "high": [2, 3, 4, 5, 6, 7],
            "low": [0, 1, 2, 3, 4, 5],
            "close": [1, 2, 3, 4, 5, 6],
            "volume": [1, 1, 1, 1, 1, 1],
            "start_ts": [
                "2024-01-01T00:00:00Z",
                "2024-01-01T01:00:00Z",
                "2024-01-01T02:00:00Z",
                "2024-01-01T03:00:00Z",
                "2024-01-01T04:00:00Z",
                "2024-01-01T05:00:00Z",
            ],
            "end_ts": [
                "2024-01-01T01:00:00Z",
                "2024-01-01T02:00:00Z",
                "2024-01-01T03:00:00Z",
                "2024-01-01T04:00:00Z",
                "2024-01-01T05:00:00Z",
                "2024-01-01T06:00:00Z",
            ],
        }
    )
    data_dir = tmp_path / "dataset" / "history"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / "BTCUSDT_1h.csv"
    df.to_csv(csv_path, index=False)

    cfg = type("Cfg", (), {})()
    cfg.strategy = type("Strategy", (), {"type": "simple_ma", "params": {"short_window": 2, "long_window": 3}})()
    cfg.backtest = BacktestConfig(
        data_dir=str(data_dir),
        symbol="BTCUSDT",
        interval="1h",
        start="2024-01-01T00:00:00Z",
        end="2024-01-01T06:00:00Z",
        initial_equity=1000.0,
    )
    result = run_ma_crossover_vectorized(cfg)
    assert result.equity_curve
    assert "total_return" in result.metrics


def test_vector_backtest_with_signals(tmp_path):
    df = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"] * 4,
            "open": [1, 2, 3, 4],
            "high": [2, 3, 4, 5],
            "low": [0, 1, 2, 3],
            "close": [1, 2, 3, 4],
            "volume": [1, 1, 1, 1],
            "start_ts": [
                "2024-01-01T00:00:00Z",
                "2024-01-01T01:00:00Z",
                "2024-01-01T02:00:00Z",
                "2024-01-01T03:00:00Z",
            ],
            "end_ts": [
                "2024-01-01T01:00:00Z",
                "2024-01-01T02:00:00Z",
                "2024-01-01T03:00:00Z",
                "2024-01-01T04:00:00Z",
            ],
        }
    )
    data_dir = tmp_path / "dataset" / "history"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / "BTCUSDT_1h.csv"
    df.to_csv(csv_path, index=False)

    cfg = type("Cfg", (), {})()
    cfg.strategy = type("Strategy", (), {"type": "simple_ma", "params": {"short_window": 2, "long_window": 3}})()
    cfg.backtest = BacktestConfig(
        data_dir=str(data_dir),
        symbol="BTCUSDT",
        interval="1h",
        start="2024-01-01T00:00:00Z",
        end="2024-01-01T04:00:00Z",
        initial_equity=1000.0,
    )

    signals = [
        {"ts": "2024-01-01T02:00:00Z", "side": "buy", "qty": 1.0},
        {"ts": "2024-01-01T04:00:00Z", "side": "sell", "qty": 1.0},
    ]
    price_df = df.copy()
    price_df["end_ts"] = pd.to_datetime(price_df["end_ts"], utc=True)
    result = run_signal_vectorized(cfg, price_df=price_df, signals=signals)
    assert result.equity_curve
    assert len(result.trades) >= 1
