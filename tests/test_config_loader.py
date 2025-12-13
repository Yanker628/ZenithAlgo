import os
from pathlib import Path

import pytest

from shared.config.config_loader import AppConfig, load_config


def test_load_config_expands_env_and_returns_appconfig(monkeypatch: pytest.MonkeyPatch):
    cfg_path = Path("config/config.yml")
    assert cfg_path.exists(), "示例配置缺失"

    monkeypatch.setenv("BINANCE_API_KEY", "dummy_key")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy_secret")

    cfg = load_config(str(cfg_path), load_env=False)
    assert isinstance(cfg, AppConfig)
    assert isinstance(cfg.symbol, str) and cfg.symbol
    assert cfg.exchange.api_key == "dummy_key"
    assert cfg.equity_base == 1000
    assert cfg.mode == "paper"
    assert cfg.backtest is not None
    assert isinstance(cfg.backtest.symbol, str) and cfg.backtest.symbol
    assert cfg.risk.max_position_pct > 0


def test_load_config_missing_env_raises(monkeypatch: pytest.MonkeyPatch):
    cfg_path = Path("config/config.yml")
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)

    with pytest.raises(ValueError) as exc:
        load_config(str(cfg_path), load_env=False)
    assert "Missing environment variable" in str(exc.value)
