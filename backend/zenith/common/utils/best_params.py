"""从参数搜索 CSV 里挑选最优参数并生成新配置。"""

from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List


def pick_best_params(csv_path: str | Path, min_trades: int = 30) -> dict:
    """从 sweep CSV 中挑选最佳参数行。

    Parameters
    ----------
    csv_path:
        sweep CSV 路径。
    min_trades:
        最少交易数要求；若无满足行会自动放宽至 0 重试。

    Returns
    -------
    dict
        最佳参数 dict。
    """
    path = Path(csv_path)
    best_row: Dict[str, Any] | None = None

    def _as_float(val, default=0.0):
        try:
            return float(val)
        except Exception:
            return default

    def _scan(threshold: int, *, require_passed: bool):
        nonlocal best_row
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if require_passed and "passed" in row:
                    passed_raw = str(row.get("passed") or "").strip().lower()
                    if passed_raw not in {"1", "true", "yes", "y"}:
                        continue
                trades = _as_float(row.get("total_trades", 0))
                if trades < threshold:
                    continue

                score = _as_float(row.get("score", 0))
                if score == 0:
                    ret = _as_float(row.get("total_return", 0))
                    sharpe = _as_float(row.get("sharpe", 0))
                    dd = _as_float(row.get("max_drawdown", 0))
                    score = 0.4 * ret + 0.4 * sharpe - 0.2 * dd

                row["_score_eval"] = score
                if best_row is None or score > best_row["_score_eval"]:
                    best_row = row

    # 优先使用 passed=true 的组合（若 CSV 提供该列）
    _scan(min_trades, require_passed=True)
    if best_row is None:
        _scan(min_trades, require_passed=False)
    if best_row is None:
        # 放宽交易数限制重试，避免空集
        _scan(0, require_passed=True)
    if best_row is None:
        _scan(0, require_passed=False)

    if best_row is None:
        raise ValueError("No eligible rows found in sweep CSV")

    params = {}
    skip_cols = {
        "symbol",
        "score",
        "total_return",
        "max_drawdown",
        "sharpe",
        "win_rate",
        "avg_win",
        "avg_loss",
        "total_trades",
        "_score_eval",
    }
    for k, v in best_row.items():
        if k in skip_cols or k is None:
            continue
        if v is None or v == "":
            continue
        try:
            params[k] = float(v) if "." in str(v) else int(v)
        except Exception:
            params[k] = v
    return params


def generate_best_config(base_cfg_path: str | Path, output_path: str | Path, params: dict) -> Path:
    """生成包含最佳参数的新配置文件。"""
    import yaml

    # 直接读 YAML 以保留原格式结构，避免 env 占位符报错
    with Path(base_cfg_path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    bt = raw.get("backtest", {})
    strat = bt.get("strategy", {}) or {}
    strat.update(params)
    bt["strategy"] = strat
    raw["backtest"] = bt

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=False, sort_keys=False)
    return out_path


# 兼容命名
def apply_best_params_to_config(base_cfg_path: str | Path, csv_path: str | Path, out_path: str | Path, min_trades: int = 30) -> Path:
    params = pick_best_params(csv_path, min_trades=min_trades)
    return generate_best_config(base_cfg_path, out_path, params)


def apply_best_params_cli():
    import argparse

    parser = argparse.ArgumentParser(description="Apply best params from sweep CSV to a new config file.")
    parser.add_argument("--cfg", required=True, help="Base config path")
    parser.add_argument("--sweep", required=True, help="Sweep CSV path")
    parser.add_argument("--min_trades", type=int, default=30, help="Minimum trades to consider")
    parser.add_argument(
        "--out",
        default=None,
        help="Output config path (default: config/config_best_<symbol>_<interval>.yml)",
    )
    args = parser.parse_args()

    params = pick_best_params(args.sweep, min_trades=args.min_trades)

    # 构造默认输出路径
    out_path = args.out
    if out_path is None:
        sym = params.get("symbol", "best")
        # 从 sweep 文件名猜 interval
        interval = "unknown"
        name = Path(args.sweep).stem
        parts = name.split("_")
        if len(parts) >= 3:
            interval = parts[-1]
        out_path = f"config/config_best_{sym}_{interval}.yml"

    out_path = generate_best_config(args.cfg, out_path, params)
    print(f"Best params: {params}")
    print(f"Written to: {out_path}")


if __name__ == "__main__":
    apply_best_params_cli()
