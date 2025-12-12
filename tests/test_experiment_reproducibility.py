from __future__ import annotations

import json
from pathlib import Path

from research import experiment


def test_ensure_config_snapshot_writes_required_files_on_load_error(monkeypatch, tmp_path: Path):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text("symbol: BTCUSDT\n", encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(experiment, "load_config", _boom)

    out_dir = tmp_path / "out"
    experiment._ensure_config_snapshot(str(cfg_path), out_dir)

    assert (out_dir / "config.yml").exists()
    eff = out_dir / "effective_config.json"
    assert eff.exists()
    payload = json.loads(eff.read_text(encoding="utf-8"))
    assert payload["error"] == "boom"
    assert payload["cfg_path"] == str(cfg_path)


def test_select_heatmap_axes_default_from_param_grid():
    x, y, value = experiment._select_heatmap_axes(
        {"long_window": [60, 90], "slope_threshold": [0.05, 0.1]},
        {},
    )
    assert (x, y, value) == ("long_window", "slope_threshold", "score")


def test_select_heatmap_axes_can_be_overridden():
    x, y, value = experiment._select_heatmap_axes(
        {"long_window": [60, 90], "slope_threshold": [0.05, 0.1]},
        {"heatmap": {"x": "short_window", "y": "long_window", "value": "sharpe"}},
    )
    assert (x, y, value) == ("short_window", "long_window", "sharpe")

