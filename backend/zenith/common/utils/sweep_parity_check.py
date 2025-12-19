"""Sweep 自动对齐检查脚本。

用法：先跑 sweep，再随机抽样若干组参数回放 backtest，并对齐关键指标。
"""

from __future__ import annotations

import argparse
import random
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

from zenith.core.backtest_engine import BacktestEngine
from zenith.common.config.config_loader import BacktestConfig, load_config


def _latest_sweep_dir(cfg_obj) -> Path:
    bt_cfg = getattr(cfg_obj, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")
    symbol = str(bt_cfg.symbol)
    interval = str(bt_cfg.interval)
    start = str(bt_cfg.start)
    end = str(bt_cfg.end)
    root = Path("results") / "sweep" / symbol / interval / f"{start}_{end}"
    if not root.exists():
        raise FileNotFoundError(f"sweep 目录不存在: {root}")
    run_dirs = sorted([p for p in root.iterdir() if p.is_dir()])
    if not run_dirs:
        raise FileNotFoundError(f"sweep 结果为空: {root}")
    return run_dirs[-1]


def _coerce_value(val: Any, sample: Any) -> Any:
    if isinstance(sample, bool):
        return bool(val)
    if isinstance(sample, int) and not isinstance(sample, bool):
        return int(val)
    if isinstance(sample, float):
        return float(val)
    return val


def _select_rows(df: pd.DataFrame, *, mode: str, n: int, seed: int | None) -> pd.DataFrame:
    if "passed" in df.columns:
        df = df.copy()
        df = df[df["passed"] == True]  # noqa: E712 - pandas 兼容
    if df.empty:
        raise ValueError("筛选后无可用样本（可能全部未通过过滤）")
    if n >= len(df):
        return df
    if mode == "top":
        if "score" not in df.columns:
            raise ValueError("score 列缺失，无法按 top 模式抽样")
        return df.sort_values("score", ascending=False).head(n)
    rng = random.Random(seed)
    idx = rng.sample(range(len(df)), n)
    return df.iloc[idx]


def _build_cfg_for_row(cfg_base, *, row: pd.Series, param_keys: list[str], grid: dict[str, list[Any]]):
    cfg = cfg_base.model_copy(deep=True) if hasattr(cfg_base, "model_copy") else deepcopy(cfg_base)
    bt_cfg = getattr(cfg, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")
    bt_cfg = bt_cfg.model_copy(deep=True)
    if bt_cfg.strategy is None:
        raise ValueError("backtest.strategy not found")
    params = dict(getattr(bt_cfg.strategy, "params", {}) or {})
    for key in param_keys:
        if key not in row:
            continue
        sample = grid.get(key, [row[key]])[0]
        params[key] = _coerce_value(row[key], sample)
    bt_cfg.strategy = bt_cfg.strategy.model_copy(deep=True)
    bt_cfg.strategy.params = params
    bt_cfg.skip_plots = True
    cfg.backtest = bt_cfg  # type: ignore[assignment]
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep 自动对齐检查")
    parser.add_argument("--config", default="config/config.yml", help="配置文件路径")
    parser.add_argument("--sweep-dir", default=None, help="指定 sweep 运行目录（不传则自动找最新）")
    parser.add_argument("--sample-size", type=int, default=3, help="抽样数量")
    parser.add_argument("--sample-mode", choices=["random", "top"], default="random", help="抽样方式")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（仅 random 模式）")
    parser.add_argument("--atol", type=float, default=1e-9, help="对齐容差（浮点绝对误差）")
    args = parser.parse_args()

    cfg = load_config(args.config, load_env=False, expand_env=False)
    bt_cfg = getattr(cfg, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")
    sweep_cfg = getattr(bt_cfg, "sweep", None)
    grid = dict(getattr(sweep_cfg, "params", {}) or {})
    if not grid:
        raise ValueError("backtest.sweep.params 为空，无法抽样")
    param_keys = list(grid.keys())

    sweep_dir = Path(args.sweep_dir) if args.sweep_dir else _latest_sweep_dir(cfg)
    symbol = str(bt_cfg.symbol)
    sweep_csv = sweep_dir / symbol / "sweep.csv"
    if not sweep_csv.exists():
        raise FileNotFoundError(f"sweep.csv 不存在: {sweep_csv}")

    df = pd.read_csv(sweep_csv)
    missing = [k for k in param_keys if k not in df.columns]
    if missing:
        raise ValueError(f"sweep.csv 缺少参数列 {missing}，请重新跑 sweep")
    sample_df = _select_rows(df, mode=args.sample_mode, n=args.sample_size, seed=args.seed)

    metrics_keys = ["total_return", "max_drawdown", "sharpe", "total_trades"]
    failures = 0
    print(f"[对齐检查] sweep={sweep_csv} 抽样={len(sample_df)}")
    for _, row in sample_df.iterrows():
        cfg_run = _build_cfg_for_row(cfg, row=row, param_keys=param_keys, grid=grid)
        summary = BacktestEngine(cfg_obj=cfg_run).run().summary
        metrics = summary.metrics.model_dump() if hasattr(summary, "metrics") else {}

        diffs: dict[str, float] = {}
        ok = True
        for k in metrics_keys:
            lhs = float(row.get(k, 0.0))
            rhs = float(metrics.get(k, 0.0))
            diff = rhs - lhs
            diffs[k] = diff
            if k == "total_trades":
                if int(lhs) != int(rhs):
                    ok = False
            else:
                if abs(diff) > args.atol:
                    ok = False
        combo = {k: row.get(k) for k in param_keys}
        status = "OK" if ok else "DIFF"
        print(f"[{status}] params={combo} diff={diffs}")
        if not ok:
            failures += 1

    if failures:
        print(f"[对齐检查] 失败 {failures} 组，请检查策略或向量化逻辑")
        return 1
    print("[对齐检查] 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
