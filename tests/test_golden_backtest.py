from __future__ import annotations

import json
from pathlib import Path

from engine.backtest_engine import BacktestEngine
from shared.config.config_loader import load_config
from analysis.metrics.metrics_canon import CANONICAL_METRIC_KEYS


def test_golden_backtest_metrics_stable():
    cfg_path = "config/golden_backtest.yml"
    cfg = load_config(cfg_path, load_env=False, expand_env=False)
    summary = BacktestEngine(cfg_obj=cfg, artifacts_dir=None).run().summary
    metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}

    for k in CANONICAL_METRIC_KEYS:
        assert k in metrics

    expected = json.loads(Path("tests/golden/golden_summary.json").read_text(encoding="utf-8"))
    for k, v in expected.items():
        assert k in metrics
        if v == "inf":
            assert float(metrics[k]) > 0 and float(metrics[k]) == float("inf")
            continue
        if isinstance(v, (int, float)):
            assert abs(float(metrics[k]) - float(v)) <= 1e-6
        else:
            assert metrics[k] == v
