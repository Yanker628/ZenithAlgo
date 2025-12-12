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
from utils.param_search import grid_search


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

    for idx, ((train_start, train_end), (test_start, test_end)) in enumerate(segments, 1):
        # 训练段：跑 sweep
        bt_train = deepcopy(bt_cfg)
        bt_train["start"] = train_start.isoformat()
        bt_train["end"] = train_end.isoformat()
        bt_train["skip_plots"] = True
        cfg_train = deepcopy(cfg)
        cfg_train.backtest = bt_train  # type: ignore[assignment]

        sweep_csv = out_dir / f"{symbol}_{interval}_wf_train{idx}.csv"
        # 用 grid_search 扫描
        grid_search(
            cfg_path,
            bt_cfg.get("sweep", {}).get("params", {}),
            objective_weights=None,
            output_csv=str(sweep_csv),
            cfg_obj=cfg_train,
            filters=bt_cfg.get("sweep", {}).get("filters"),
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

        summary = run_backtest(cfg_obj=cfg_test)
        results["segments"].append(
            {
                "train": [train_start.isoformat(), train_end.isoformat()],
                "test": [test_start.isoformat(), test_end.isoformat()],
                "params": best_params,
                "metrics": summary.get("metrics", {}),
            }
        )
    # 汇总：简单取各段指标平均（可扩展为加权）
    if results["segments"]:
        total_return = sum(seg["metrics"].get("total_return", 0) for seg in results["segments"]) / len(
            results["segments"]
        )
        sharpe = sum(seg["metrics"].get("sharpe", 0) for seg in results["segments"]) / len(results["segments"])
        max_dd = max(seg["metrics"].get("max_drawdown", 0) for seg in results["segments"])
        results["overall"] = {"total_return_avg": total_return, "sharpe_avg": sharpe, "max_drawdown_max": max_dd}

    return results


if __name__ == "__main__":
    import json

    res = walk_forward()
    print(json.dumps(res, indent=2))
