"""实验产物“可复现契约”测试。

目标：确保 research.experiment 的产物落盘结构稳定。
一旦未来重构触碰到可复现契约，CI 应该立刻报错。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research import experiment as exp


def _write_minimal_backtest_dataset(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "symbol,open,high,low,close,volume,start_ts,end_ts",
                "BTCUSDT,100,101,99,100,1,2024-01-01T00:00:00+00:00,2024-01-01T01:00:00+00:00",
                "BTCUSDT,101,102,100,101,1,2024-01-01T01:00:00+00:00,2024-01-01T02:00:00+00:00",
                "BTCUSDT,102,103,101,102,1,2024-01-01T02:00:00+00:00,2024-01-01T03:00:00+00:00",
                "BTCUSDT,103,104,102,103,1,2024-01-01T03:00:00+00:00,2024-01-01T04:00:00+00:00",
                "BTCUSDT,104,105,103,104,1,2024-01-01T04:00:00+00:00,2024-01-01T05:00:00+00:00",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_minimal_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "mode: backtest",
                "symbol: BTCUSDT",
                "timeframe: 1h",
                "equity_base: 10000",
                "exchange:",
                "  name: binance",
                "  base_url: https://example.invalid",
                "  api_key: null",
                "  api_secret: null",
                "  ws_url: null",
                "  allow_live: false",
                "risk:",
                "  max_position_pct: 1.0",
                "  max_daily_loss_pct: 0.5",
                "strategy:",
                "  type: simple_ma",
                "  short_window: 2",
                "  long_window: 3",
                "  min_ma_diff: 0.0",
                "  cooldown_secs: 0",
                "backtest:",
                "  symbol: BTCUSDT",
                "  interval: 1h",
                '  start: "2024-01-01T00:00:00Z"',
                '  end: "2024-01-01T05:00:00Z"',
                "  data_dir: dataset/history",
                "  skip_plots: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_backtest_experiment_artifacts_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 固定 run_id，方便定位输出目录与断言。
    monkeypatch.setattr(exp, "_utc_ts", lambda: "20000101000000")
    monkeypatch.setattr(exp, "_utc_iso", lambda: "2000-01-01T00:00:00Z")

    # 隔离运行目录：避免污染仓库根目录的 results/。
    monkeypatch.chdir(tmp_path)

    cfg_path = tmp_path / "config" / "config.yml"
    _write_minimal_config(cfg_path)

    dataset_path = tmp_path / "dataset" / "history" / "BTCUSDT_1h.csv"
    _write_minimal_backtest_dataset(dataset_path)

    exp.run_experiment(str(cfg_path), task="backtest")

    out_dir = (
        tmp_path
        / "results"
        / "backtest"
        / "BTCUSDT"
        / "1h"
        / "2024-01-01T00:00:00Z_2024-01-01T05:00:00Z"
        / "20000101000000"
    )
    assert out_dir.exists() and out_dir.is_dir()

    # 产物契约：配置快照
    assert (out_dir / "config.yml").is_file()
    assert (out_dir / "effective_config.json").is_file()

    # 产物契约：研究/实验输出
    assert (out_dir / "meta.json").is_file()
    assert (out_dir / "summary.json").is_file()
    assert (out_dir / "results.json").is_file()

    # 产物契约：回测引擎导出
    assert (out_dir / "trades.csv").is_file()
    assert (out_dir / "equity.csv").is_file()
