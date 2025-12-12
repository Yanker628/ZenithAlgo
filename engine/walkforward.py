"""Walk-Forward 验证。

按时间分段训练（sweep 找最优参数）+ 测试（回测评估），
用于更稳健地评估参数泛化能力。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from engine.backtest_runner import run_backtest, parse_iso
from utils.best_params import pick_best_params
from utils.config_loader import load_config
from utils.metrics_canon import CANONICAL_METRIC_KEYS, canonicalize_metrics
from utils.param_search import grid_search, random_search


def _split_segments(
    start: datetime,
    end: datetime,
    n_segments: int = 3,
    train_ratio: float = 0.7,
) -> List[Tuple[Tuple[datetime, datetime], Tuple[datetime, datetime]]]:
    """将整体区间切成 n 段 train/test 子区间。"""
    segments = []
    total_seconds = (end - start).total_seconds()
    seg_len = total_seconds / n_segments
    for i in range(n_segments):
        seg_start = start + i * (end - start) / n_segments
        seg_end = start + (i + 1) * (end - start) / n_segments
        train_end = seg_start + (seg_end - seg_start) * train_ratio
        segments.append(((seg_start, train_end), (train_end, seg_end)))
    return segments


def walk_forward(
    cfg_path: str = "config/config.yml",
    n_segments: int = 3,
    train_ratio: float = 0.7,
    min_trades: int = 10,
    output_dir: str = "data/walkforward",
    artifacts_base_dir: str | None = None,
):
    """执行 Walk-Forward 验证。

    Parameters
    ----------
    cfg_path:
        配置文件路径。
    n_segments:
        分段数量。
    train_ratio:
        每段训练占比。
    min_trades:
        训练段筛选最优参数时要求的最少交易数。
    output_dir:
        sweep CSV 输出目录。
    artifacts_base_dir:
        可选：为每个测试段 backtest 生成 trades/equity/图表等产物的根目录。

    Returns
    -------
    dict
        含每段参数/指标以及 overall 汇总的结果。
    """
    cfg = load_config(cfg_path, load_env=False, expand_env=False)
    bt_cfg = getattr(cfg, "backtest", None)
    if not bt_cfg:
        raise ValueError("backtest config not found")

    symbol = bt_cfg.get("symbol", cfg.symbol)
    interval = bt_cfg.get("interval", cfg.timeframe)
    start = parse_iso(bt_cfg["start"])
    end = parse_iso(bt_cfg["end"])
    segments = _split_segments(start, end, n_segments, train_ratio)

    results = {"segments": [], "overall": {}}
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sweep_cfg = bt_cfg.get("sweep", {}) or {}
    mode = str(sweep_cfg.get("mode", "grid")).lower()
    param_grid = sweep_cfg.get("params", {}) or {}
    obj = sweep_cfg.get("objective", {}) or {}
    weights = {
        "total_return": float(obj.get("total_return_weight", 0.0)),
        "sharpe": float(obj.get("sharpe_weight", 0.0)),
        "max_drawdown": float(obj.get("max_drawdown_weight", 0.0)),
    }
    filters = sweep_cfg.get("filters") or {
        "min_trades": sweep_cfg.get("min_trades"),
        "max_drawdown": sweep_cfg.get("max_drawdown"),
        "min_sharpe": sweep_cfg.get("min_sharpe"),
    }
    low_trades_penalty = float(sweep_cfg.get("low_trades_penalty", 0.0))

    for idx, ((train_start, train_end), (test_start, test_end)) in enumerate(segments, 1):
        # 训练段：跑 sweep
        bt_train = deepcopy(bt_cfg)
        bt_train["start"] = train_start.isoformat()
        bt_train["end"] = train_end.isoformat()
        bt_train["skip_plots"] = True
        cfg_train = deepcopy(cfg)
        cfg_train.backtest = bt_train  # type: ignore[assignment]

        sweep_csv = out_dir / f"{symbol}_{interval}_wf_train{idx}.csv"
        if mode == "random":
            n_samples = int(sweep_cfg.get("n_random", 20))
            random_search(
                cfg_path,
                param_grid,
                n_samples,
                objective_weights=weights,
                output_csv=str(sweep_csv),
                cfg_obj=cfg_train,
                filters=filters,
                low_trades_penalty=low_trades_penalty,
            )
        else:
            grid_search(
                cfg_path,
                param_grid,
                objective_weights=weights,
                output_csv=str(sweep_csv),
                cfg_obj=cfg_train,
                filters=filters,
                low_trades_penalty=low_trades_penalty,
            )
        best_params = pick_best_params(sweep_csv, min_trades=min_trades)

        # 测试段：应用最佳参数回测
        bt_test = deepcopy(bt_cfg)
        bt_test["start"] = test_start.isoformat()
        bt_test["end"] = test_end.isoformat()
        bt_test["skip_plots"] = True
        bt_test["strategy"] = deepcopy(bt_test.get("strategy", {}))
        bt_test["strategy"].update(best_params)
        cfg_test = deepcopy(cfg)
        cfg_test.backtest = bt_test  # type: ignore[assignment]

        artifacts_dir = None
        if artifacts_base_dir:
            artifacts_dir = str(Path(artifacts_base_dir) / f"seg{idx}" / "test_backtest")
        summary = run_backtest(cfg_obj=cfg_test, artifacts_dir=artifacts_dir)
        results["segments"].append(
            {
                "train": [train_start.isoformat(), train_end.isoformat()],
                "test": [test_start.isoformat(), test_end.isoformat()],
                "params": best_params,
                "metrics": canonicalize_metrics(summary.get("metrics", {}) if isinstance(summary, dict) else {}),
                "artifacts_dir": artifacts_dir,
            }
        )
    # 汇总：输出 canonical metrics（字段与 backtest/sweep 保持一致）
    if results["segments"]:
        segs = results["segments"]
        n = len(segs)
        returns = [float(seg["metrics"].get("total_return", 0.0) or 0.0) for seg in segs]
        profitable_segments_ratio = (sum(1 for r in returns if r > 0) / n) if n else 0.0
        worst_segment_return = min(returns) if n else 0.0
        sorted_returns = sorted(returns)
        if n == 0:
            median_return = 0.0
        elif n % 2 == 1:
            median_return = sorted_returns[n // 2]
        else:
            median_return = (sorted_returns[n // 2 - 1] + sorted_returns[n // 2]) / 2

        def _wavg(key: str) -> float:
            num = 0.0
            den = 0.0
            for seg in segs:
                m = seg.get("metrics", {}) or {}
                w = float(m.get("total_trades", 0) or 0)
                v = float(m.get(key, 0.0) or 0.0)
                num += v * w
                den += w
            return (num / den) if den > 0 else 0.0

        def _avg(key: str) -> float:
            return sum(float((seg.get("metrics", {}) or {}).get(key, 0.0) or 0.0) for seg in segs) / n if n else 0.0

        def _max(key: str) -> float:
            return max(float((seg.get("metrics", {}) or {}).get(key, 0.0) or 0.0) for seg in segs) if n else 0.0

        total_trades_sum = sum(int((seg.get("metrics", {}) or {}).get("total_trades", 0) or 0) for seg in segs)
        overall_metrics: dict[str, Any] = {
            "total_return": _avg("total_return"),
            "max_drawdown": _max("max_drawdown"),
            "sharpe": _avg("sharpe"),
            "win_rate": _wavg("win_rate"),
            "avg_win": _wavg("avg_win"),
            "avg_loss": _wavg("avg_loss"),
            "total_trades": total_trades_sum,
            "profit_factor": _avg("profit_factor"),
            "expectancy": _wavg("expectancy"),
            "avg_trade_return": _wavg("avg_trade_return"),
            "std_trade_return": _avg("std_trade_return"),
            "exposure": _avg("exposure"),
            "turnover": _avg("turnover"),
        }
        overall_metrics = canonicalize_metrics(overall_metrics)

        reasons: list[str] = []
        if profitable_segments_ratio < 0.6:
            reasons.append("unstable_segments")
        if worst_segment_return < -0.05:
            reasons.append("worst_segment_return")
        if median_return <= 0:
            reasons.append("median_return")
        if any(int((seg.get("metrics", {}) or {}).get("total_trades", 0) or 0) == 0 for seg in segs):
            reasons.append("no_trades_segment")

        results["overall"] = {
            **{k: overall_metrics[k] for k in CANONICAL_METRIC_KEYS if k in overall_metrics},
            "profitable_segments_ratio": profitable_segments_ratio,
            "worst_segment_return": worst_segment_return,
            "median_return": median_return,
            "final_decision": "reject" if reasons else "accept",
            "reasons": reasons,
        }

    return results


if __name__ == "__main__":
    import json

    res = walk_forward()
    print(json.dumps(res, indent=2))
