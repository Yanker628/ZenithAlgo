from pathlib import Path

import pytest

from zenith.common.config.config_loader import load_config


def test_unknown_top_level_key_fails_fast(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(
        "\n".join(
            [
                "symbol: BTCUSDT",
                "timeframe: 1h",
                "equity_base: 1000",
                "exchange:",
                "  name: binance",
                "  base_url: https://example.invalid",
                "risk:",
                "  max_position_pct: 0.3",
                "  max_daily_loss_pct: 1",
                "symobl: BTCUSDT  # typo",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc:
        load_config(str(cfg_path), load_env=False, expand_env=False)
    assert "unknown keys" in str(exc.value).lower()


def test_unknown_backtest_key_fails_fast(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(
        "\n".join(
            [
                "symbol: BTCUSDT",
                "timeframe: 1h",
                "equity_base: 1000",
                "exchange:",
                "  name: binance",
                "  base_url: https://example.invalid",
                "risk:",
                "  max_position_pct: 0.3",
                "  max_daily_loss_pct: 1",
                "backtest:",
                "  data_dir: dataset/history",
                "  interval: 1h",
                '  start: \"2024-01-01T00:00:00Z\"',
                '  end: \"2024-01-02T00:00:00Z\"',
                "  unknow_key: 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc:
        load_config(str(cfg_path), load_env=False, expand_env=False)
    msg = str(exc.value).lower()
    assert "unknown keys" in msg
    assert "backtest" in msg
