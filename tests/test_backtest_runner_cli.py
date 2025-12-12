from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import backtest_runner


def test_backtest_runner_main_passes_cfg_and_artifacts_dir(monkeypatch, tmp_path, capsys):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text("symbol: BTCUSDT\n", encoding="utf-8")

    called = {"cfg_path": None, "artifacts_dir": None}

    def _fake_run_backtest(*, cfg_path: str, artifacts_dir=None, **_kwargs):
        called["cfg_path"] = cfg_path
        called["artifacts_dir"] = artifacts_dir
        return {"ok": True}

    monkeypatch.setattr(backtest_runner, "run_backtest", _fake_run_backtest)
    rc = backtest_runner.main(["--cfg", str(cfg_path), "--artifacts-dir", "OUT", "--json"])
    assert rc == 0
    assert called["cfg_path"] == str(cfg_path)
    assert called["artifacts_dir"] == "OUT"
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_backtest_runner_main_requires_existing_cfg(tmp_path: Path):
    missing = tmp_path / "missing.yml"
    assert not missing.exists()
    with pytest.raises(SystemExit):
        backtest_runner.main(["--cfg", str(missing)])

