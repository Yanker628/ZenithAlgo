from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zenith.core.walkforward_engine import WalkforwardEngine


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


def test_walkforward_smoke(tmp_path):
    symbol = "BTCUSDT"
    interval = "1h"
    data_dir = tmp_path / "history"
    # 12 根 1h，足够切 2 段
    _write_candles_csv(data_dir / f"{symbol}_{interval}.csv", symbol=symbol, interval=interval, prices=[1, 2, 3, 2, 1, 2, 3, 4, 3, 2, 3, 4])

    # WalkforwardEngine 读取 cfg_path；这里写一个最小配置文件即可覆盖 smoke 场景
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(
        "\n".join(
            [
                f"symbol: \"{symbol}\"",
                f"timeframe: \"{interval}\"",
                "mode: \"paper\"",
                "equity_base: 1000",
                "exchange:",
                "  name: \"binance\"",
                "  base_url: \"https://api.binance.com\"",
                "risk:",
                "  max_position_pct: 1.0",
                "  max_daily_loss_pct: 1.0",
                "strategy:",
                "  type: \"simple_ma\"",
                "  min_ma_diff: 0.0",
                "  cooldown_secs: 0",
                "backtest:",
                f"  data_dir: \"{data_dir}\"",
                f"  symbol: \"{symbol}\"",
                f"  interval: \"{interval}\"",
                "  start: \"2024-01-01T00:00:00Z\"",
                "  end: \"2024-01-01T12:00:00Z\"",
                "  initial_equity: 1000",
                "  auto_download: false",
                "  quiet_risk_logs: true",
                "  flatten_on_end: false",
                "  fees: {maker: 0.0, taker: 0.0, slippage_bp: 0.0}",
                "  sweep:",
                "    mode: \"grid\"",
                "    params: {short_window: [2], long_window: [3]}",
                "    objective: {total_return_weight: 1.0, sharpe_weight: 0.0, max_drawdown_weight: 0.0}",
                "    min_trades: 0",
            ]
        ),
        encoding="utf-8",
    )

    res = WalkforwardEngine(
        cfg_path=str(cfg_path),
        n_segments=2,
        train_ratio=0.5,
        min_trades=0,
        output_dir=str(tmp_path / "wf"),
    ).run().summary
    assert "segments" in res and "overall" in res
    assert len(res["segments"]) == 2
    assert "profitable_segments_ratio" in res["overall"]
    assert "worst_segment_return" in res["overall"]
    assert "median_return" in res["overall"]
    for seg in res["segments"]:
        assert "train" in seg and "test" in seg and "params" in seg and "metrics" in seg
