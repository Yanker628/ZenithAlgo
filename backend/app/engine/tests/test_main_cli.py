from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import main as app_main


def test_main_backtest_delegates_to_experiment(monkeypatch):
    calls: list[dict[str, Any]] = []

    def _fake_run_experiment(cfg_path: str, task: str, **kwargs):
        calls.append({"cfg_path": cfg_path, "task": task, "kwargs": kwargs})
        return {"ok": True}

    monkeypatch.setattr(app_main, "run_experiment", _fake_run_experiment)
    res = app_main.main(["--config", "config/golden_backtest.yml", "backtest"])
    assert res == {"ok": True}
    assert calls == [{"cfg_path": "config/golden_backtest.yml", "task": "backtest", "kwargs": {}}]


def test_main_backtest_accepts_config_after_subcommand(monkeypatch):
    calls: list[dict[str, Any]] = []

    def _fake_run_experiment(cfg_path: str, task: str, **kwargs):
        calls.append({"cfg_path": cfg_path, "task": task, "kwargs": kwargs})
        return {"ok": True}

    monkeypatch.setattr(app_main, "run_experiment", _fake_run_experiment)
    res = app_main.main(["backtest", "--config", "config/golden_backtest.yml"])
    assert res == {"ok": True}
    assert calls == [{"cfg_path": "config/golden_backtest.yml", "task": "backtest", "kwargs": {}}]


def test_main_runner_uses_trading_engine(monkeypatch):
    @dataclass
    class _Res:
        summary: dict[str, Any]

    class _FakeEngine:
        def __init__(self, *, cfg_path: str, max_ticks: int | None = None, **_kwargs):
            self.cfg_path = cfg_path
            self.max_ticks = max_ticks

        def run(self):
            return _Res(summary={"cfg_path": self.cfg_path, "max_ticks": self.max_ticks})

    monkeypatch.setattr(app_main, "TradingEngine", _FakeEngine)
    res = app_main.main(["--config", "config/config.yml", "runner", "--max-ticks", "12"])
    assert res == {"cfg_path": "config/config.yml", "max_ticks": 12}
