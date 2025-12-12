from __future__ import annotations

from pathlib import Path

import pytest

from research import experiment


def test_experiment_main_prints_artifacts_dir(monkeypatch, tmp_path, capsys):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text("symbol: BTCUSDT\n", encoding="utf-8")

    def _fake_run_experiment(cfg_path: str, task: str, **_kwargs):
        return experiment.ExperimentResult(task=task, meta={}, artifacts={"dir": "OUT_DIR"})

    monkeypatch.setattr(experiment, "run_experiment", _fake_run_experiment)
    rc = experiment.main(["--task", "sweep", "--cfg", str(cfg_path), "--top-n", "3"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "OUT_DIR"


def test_experiment_main_requires_existing_cfg(tmp_path):
    missing = tmp_path / "missing.yml"
    assert not Path(missing).exists()
    with pytest.raises(SystemExit):
        experiment.main(["--task", "sweep", "--cfg", str(missing)])

