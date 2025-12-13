from __future__ import annotations

import json
from pathlib import Path

from engine.backtest_engine import BacktestEngine
from shared.config.config_loader import load_config
from analysis.metrics.metrics_canon import CANONICAL_METRIC_KEYS


def _load_expected() -> dict:
    return json.loads(Path("tests/golden/golden_summary.json").read_text(encoding="utf-8"))


def _extract_actual(summary: dict) -> dict:
    metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}
    keys = ["total_return", "max_drawdown", "sharpe", "total_trades", "profit_factor"]
    out = {k: metrics.get(k) for k in keys}
    if out.get("profit_factor") == float("inf"):
        out["profit_factor"] = "inf"
    if out.get("profit_factor") == float("-inf"):
        out["profit_factor"] = "-inf"
    return out


def run_golden(tol: float = 1e-6) -> int:
    cfg_path = "config/golden_backtest.yml"
    cfg = load_config(cfg_path, load_env=False, expand_env=False)
    summary = BacktestEngine(cfg_obj=cfg, artifacts_dir=None).run().summary
    metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}
    missing = [k for k in CANONICAL_METRIC_KEYS if k not in metrics]
    if missing:
        print("Golden backtest FAILED: metrics missing keys:", missing)
        return 1
    actual = _extract_actual(summary)
    expected = _load_expected()

    failed: list[str] = []
    for k, exp in expected.items():
        act = actual.get(k)
        if exp in {"inf", "-inf", "nan"}:
            if act != exp:
                failed.append(f"{k}: expected {exp}, got {act}")
            continue
        if isinstance(exp, (int, float)) and isinstance(act, (int, float)):
            if abs(float(act) - float(exp)) > tol:
                failed.append(f"{k}: expected {exp}, got {act}")
        else:
            if act != exp:
                failed.append(f"{k}: expected {exp}, got {act}")

    if failed:
        print("Golden backtest FAILED:")
        for line in failed:
            print("-", line)
        return 1

    print("Golden backtest OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_golden())
