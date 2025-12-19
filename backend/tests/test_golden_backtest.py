from __future__ import annotations

import json
from pathlib import Path

from zenith.core.backtest_engine import BacktestEngine
from zenith.common.config.config_loader import load_config
from zenith.analysis.metrics.metrics_canon import CANONICAL_METRIC_KEYS


def test_golden_backtest_metrics_stable():
    cfg_path = "config/golden_backtest.yml"
    cfg = load_config(cfg_path, load_env=False, expand_env=False)
    summary = BacktestEngine(cfg_obj=cfg, artifacts_dir=None).run().summary
    metrics = summary.metrics.model_dump()

    for k in CANONICAL_METRIC_KEYS:
        assert k in metrics

    # Verify signal trace logic
    trace = summary.signal_trace
    assert trace["raw"] >= trace["after_sizing"]
    assert trace["after_sizing"] >= trace["after_risk"]
    assert trace["after_risk"] >= 0

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
