"""实验可复现入口（V2.3）。

统一把一次 backtest / sweep / walkforward 的产物落盘到 data/experiments/ 下：
- results.json
- config.yml（配置快照）
- report.md
并在需要时落盘 trades.csv / equity.csv / 图表等。
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.backtest_runner import run_backtest
from engine.walkforward import walk_forward
from utils.config_loader import load_config
from utils.logging import setup_logger
from utils.param_search import grid_search, random_search
from utils.plotter import plot_param_1d, plot_param_importance, plot_sweep_heatmaps
from research.report import write_report_md, write_summary_md


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _git_info() -> dict[str, Any]:
    try:
        sha = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
    except Exception:
        sha = None
    try:
        status = (
            subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
        dirty = bool(status)
    except Exception:
        dirty = None
    return {"sha": sha, "dirty": dirty}


def _dump_effective_cfg(cfg_obj, path: Path) -> None:
    strategy_obj = getattr(cfg_obj, "strategy", None)
    risk_obj = getattr(cfg_obj, "risk", None)
    exchange_obj = getattr(cfg_obj, "exchange", None)
    payload = {
        "mode": getattr(cfg_obj, "mode", None),
        "symbol": getattr(cfg_obj, "symbol", None),
        "timeframe": getattr(cfg_obj, "timeframe", None),
        "equity_base": getattr(cfg_obj, "equity_base", None),
        "strategy": asdict(strategy_obj) if strategy_obj is not None else None,
        "sizing": getattr(cfg_obj, "sizing", None),
        "backtest": getattr(cfg_obj, "backtest", None),
        "risk": asdict(risk_obj) if risk_obj is not None else None,
        "exchange": asdict(exchange_obj) if exchange_obj is not None else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_config_snapshot(cfg_path: str, out_dir: Path) -> None:
    """
    产物可复现要求：每次实验目录必须包含
    - config.yml（原始配置快照）
    - effective_config.json（解析后的生效配置；解析失败也要落盘 error 信息）
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 原始配置快照（必须落盘）
    shutil.copy2(cfg_path, out_dir / "config.yml")

    # 2) 生效配置快照（尽量落盘：失败则写 error payload）
    try:
        cfg_obj = load_config(cfg_path, load_env=False, expand_env=False)
        _dump_effective_cfg(cfg_obj, out_dir / "effective_config.json")
    except Exception as exc:
        (out_dir / "effective_config.json").write_text(
            json.dumps({"error": str(exc), "cfg_path": cfg_path}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        setup_logger("experiment").warning("effective_config.json fallback written: %s", exc)


def _select_heatmap_axes(param_grid: dict[str, Any], sweep_cfg: dict[str, Any]) -> tuple[str, str, str]:
    """
    配置命名一致性要求：
    - 默认从 sweep.params 取前两个维度作为 x/y 轴（不硬编码 short/long）
    - 支持 backtest.sweep.heatmap 显式指定 x/y/value
    """
    heatmap_cfg = sweep_cfg.get("heatmap") if isinstance(sweep_cfg, dict) else None
    heatmap_cfg = heatmap_cfg if isinstance(heatmap_cfg, dict) else {}

    x = heatmap_cfg.get("x") or heatmap_cfg.get("x_param")
    y = heatmap_cfg.get("y") or heatmap_cfg.get("y_param")
    value = heatmap_cfg.get("value") or heatmap_cfg.get("value_param") or "score"

    if x and y:
        return str(x), str(y), str(value)

    keys = list(param_grid.keys())
    if len(keys) >= 2:
        return str(keys[0]), str(keys[1]), str(value)

    # 不足 2 维无法生成 2D heatmap；保持历史默认便于定位配置问题
    return "short_window", "long_window", str(value)


def _csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        return next(reader, [])


def _experiment_dir(task: str, meta: dict[str, Any]) -> Path:
    symbol = str(meta.get("symbol") or "UNKNOWN")
    interval = str(meta.get("interval") or "NA")
    start = str(meta.get("start") or "NA")
    end = str(meta.get("end") or "NA")
    run_ts = str(meta.get("run_ts") or _utc_ts())
    return Path("data/experiments") / task / symbol / interval / f"{start}_{end}" / run_ts


@dataclass(frozen=True)
class ExperimentResult:
    task: str
    meta: dict[str, Any]
    metrics: dict[str, Any] | None = None
    artifacts: dict[str, Any] | None = None


def run_backtest_experiment(cfg_path: str) -> ExperimentResult:
    logger = setup_logger("experiment")
    cfg = load_config(cfg_path, load_env=False, expand_env=False)
    bt_cfg = cfg.backtest or {}
    meta = {
        "symbol": bt_cfg.get("symbol", cfg.symbol),
        "interval": bt_cfg.get("interval", cfg.timeframe),
        "start": bt_cfg.get("start"),
        "end": bt_cfg.get("end"),
        "run_ts": _utc_ts(),
        "git": _git_info(),
    }
    out_dir = _experiment_dir("backtest", meta)
    _ensure_config_snapshot(cfg_path, out_dir)
    summary = run_backtest(cfg_obj=cfg, artifacts_dir=out_dir)
    metrics = summary.get("metrics", {}) # type: ignore
    artifacts = {
        "dir": str(out_dir),
        "trades_csv": "trades.csv",
        "equity_csv": "equity.csv",
        "equity_png": "equity.png",
        "drawdown_png": "drawdown.png",
        "return_hist_png": "return_hist.png",
    }
    (out_dir / "results.json").write_text(
        json.dumps({"task": "backtest", "meta": meta, "summary": summary, "artifacts": artifacts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report_md(out_dir / "report.md", task="backtest", meta=meta, summary=summary, artifacts=artifacts)
    write_summary_md(out_dir / "summary.md", task="backtest", meta=meta, metrics=metrics, plots=[str(out_dir / "equity.png")])
    logger.info("Experiment saved: %s", out_dir)
    return ExperimentResult(task="backtest", meta=meta, metrics=metrics, artifacts=artifacts)


def run_sweep_experiment(cfg_path: str, top_n: int = 5) -> ExperimentResult:
    logger = setup_logger("experiment")
    cfg = load_config(cfg_path, load_env=False, expand_env=False)
    bt_cfg = cfg.backtest or {}
    sweep_cfg = (bt_cfg.get("sweep") or {}) if isinstance(bt_cfg, dict) else {}
    meta = {
        "symbol": bt_cfg.get("symbol", cfg.symbol),
        "interval": bt_cfg.get("interval", cfg.timeframe),
        "start": bt_cfg.get("start"),
        "end": bt_cfg.get("end"),
        "run_ts": _utc_ts(),
        "git": _git_info(),
    }
    out_dir = _experiment_dir("sweep", meta)
    _ensure_config_snapshot(cfg_path, out_dir)
    logger.info("Sweep experiment dir: %s", out_dir)

    symbols_cfg = bt_cfg.get("symbols")
    symbols = [str(s) for s in symbols_cfg] if symbols_cfg else [str(bt_cfg.get("symbol", cfg.symbol))]

    all_results: dict[str, Any] = {}
    for sym in symbols:
        cfg_sym = deepcopy(cfg)
        cfg_sym.backtest = deepcopy(cfg_sym.backtest) if cfg_sym.backtest else {}  # type: ignore[assignment]
        cfg_sym.backtest["symbol"] = sym  # type: ignore[index]

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

        sym_dir = out_dir / sym
        sym_dir.mkdir(parents=True, exist_ok=True)
        sweep_csv = sym_dir / "sweep.csv"

        if mode == "random":
            n_samples = int(sweep_cfg.get("n_random", 20))
            results = random_search(
                cfg_path,
                param_grid,
                n_samples,
                weights,
                output_csv=str(sweep_csv),
                cfg_obj=cfg_sym,
                filters=filters,
                low_trades_penalty=low_trades_penalty,
            )
        else:
            results = grid_search(
                cfg_path,
                param_grid,
                weights,
                output_csv=str(sweep_csv),
                cfg_obj=cfg_sym,
                filters=filters,
                low_trades_penalty=low_trades_penalty,
            )

        if not sweep_csv.exists():
            raise FileNotFoundError(f"sweep.csv not found: {sweep_csv}")
        header = _csv_header(sweep_csv)
        header_set = set(header)
        keys = list(param_grid.keys())
        if not keys:
            raise ValueError("sweep.params 为空，无法生成可视化/报告")

        value_param = str((sweep_cfg.get("heatmap", {}) or {}).get("value") or "score")
        if value_param not in header_set:
            # fallback：score 应总是存在
            value_param = "score"
        # 可视化（>=2：2D heatmap；=1：1D 曲线；任意维度都生成重要性图兜底）
        heatmaps_dir = sym_dir / "heatmaps"
        heatmaps_dir.mkdir(parents=True, exist_ok=True)
        plots: list[str] = []
        viz: dict[str, Any] = {"value": value_param}
        try:
            if len(keys) >= 2:
                x_param, y_param, value_param = _select_heatmap_axes(param_grid, sweep_cfg)
                required_cols = {x_param, y_param, value_param}
                missing = [c for c in required_cols if c not in header_set]
                if missing:
                    raise ValueError(f"sweep.csv 缺少列 {missing}，当前 header={header}")

                plots += plot_sweep_heatmaps(
                    str(sweep_csv),
                    x_param=x_param,
                    y_param=y_param,
                    value_param=value_param,
                    save_dir=heatmaps_dir,
                    filters=filters,
                    x_values=list(param_grid.get(x_param, []) or []),
                    y_values=list(param_grid.get(y_param, []) or []),
                    mask_filtered=True,
                )
                viz.update({"type": "heatmap", "x": x_param, "y": y_param, "value": value_param})

                # 额外维度：优先切片一维（>=3 值才有信息量）
                import pandas as pd  # type: ignore

                df = pd.read_csv(sweep_csv)
                candidates = [k for k in keys if k not in {x_param, y_param} and k in df.columns]
                slice_param = None
                for c in candidates:
                    if df[c].nunique(dropna=True) >= 3:
                        slice_param = c
                        break
                if slice_param:
                    plots += plot_sweep_heatmaps(
                        str(sweep_csv),
                        x_param=x_param,
                        y_param=y_param,
                        value_param=value_param,
                        slice_param=slice_param,
                        save_dir=heatmaps_dir / f"slices_{slice_param}",
                        filters=filters,
                        x_values=list(param_grid.get(x_param, []) or []),
                        y_values=list(param_grid.get(y_param, []) or []),
                        mask_filtered=True,
                    )
            else:
                p0 = keys[0]
                if p0 not in header_set:
                    raise ValueError(f"sweep.csv 缺少列: {p0}")
                plot_param_1d(
                    str(sweep_csv),
                    param=p0,
                    value_param=value_param,
                    save_path=heatmaps_dir / f"curve_{value_param}_{p0}.png",
                    filters=filters,
                    mask_filtered=True,
                )
                plots.append(str(heatmaps_dir / f"curve_{value_param}_{p0}.png"))
                viz.update({"type": "curve_1d", "param": p0, "value": value_param})
        except Exception as exc:
            logger.warning("Plot heatmaps failed (symbol=%s): %s", sym, exc)

        # 兜底：无论维度多少，生成一张参数重要性（确保至少 1 张“有信息量”的图）
        if not plots:
            try:
                plot_param_importance(
                    str(sweep_csv),
                    value_param=value_param,
                    params=keys,
                    save_path=heatmaps_dir / f"importance_{value_param}.png",
                    filters=filters,
                    mask_filtered=True,
                )
                plots.append(str(heatmaps_dir / f"importance_{value_param}.png"))
                viz.update({"type": "importance", "value": value_param})
            except Exception as exc:
                logger.warning("Plot importance failed (symbol=%s): %s", sym, exc)

        best = sorted(results, key=lambda r: r.score, reverse=True)[: max(1, int(top_n))]
        best_params = best[0].params if best else {}

        # 用最佳参数跑一次 backtest，生成 trades/equity/report
        best_bt_dir = sym_dir / "best_backtest"
        cfg_best = deepcopy(cfg_sym)
        cfg_best.backtest = deepcopy(cfg_best.backtest) if cfg_best.backtest else {}  # type: ignore[assignment]
        bt_strategy = dict(cfg_best.backtest.get("strategy", {}) or {})  # type: ignore[union-attr]
        bt_strategy.update(best_params)
        cfg_best.backtest["strategy"] = bt_strategy  # type: ignore[index]
        cfg_best.backtest["skip_plots"] = False  # type: ignore[index]
        bt_summary = run_backtest(cfg_obj=cfg_best, artifacts_dir=best_bt_dir)

        all_results[sym] = {
            "sweep_csv": str(sweep_csv),
            "filter_stats_json": str(sym_dir / f"{sweep_csv.stem}_filter_stats.json")
            if (sym_dir / f"{sweep_csv.stem}_filter_stats.json").exists()
            else None,
            "heatmaps_dir": str(heatmaps_dir) if heatmaps_dir.exists() else None,
            "plots": plots,
            "viz": viz,
            "top": [{"params": r.params, "metrics": r.metrics, "score": r.score} for r in best],
            "best_params": best_params,
            "best_backtest": {
                "dir": str(best_bt_dir),
                "metrics": bt_summary.get("metrics", {}),  # type: ignore
                "data_health": bt_summary.get("data_health", {}),  # type: ignore
            },
        }

    payload = {"task": "sweep", "meta": meta, "symbols": all_results}
    (out_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report_md(out_dir / "report.md", task="sweep", meta=meta, summary=payload, artifacts={"dir": str(out_dir)})
    # summary：取第一个 symbol 的 best_backtest 作为概览
    first_sym = next(iter(all_results.values()), {}) if all_results else {}
    bb = first_sym.get("best_backtest") if isinstance(first_sym, dict) else {}
    metrics = dict(bb.get("metrics", {}) or {}) if isinstance(bb, dict) else {}
    plots = first_sym.get("plots") if isinstance(first_sym, dict) else None # type: ignore
    write_summary_md(out_dir / "summary.md", task="sweep", meta=meta, metrics=metrics, plots=plots if isinstance(plots, list) else None)
    logger.info("Experiment saved: %s", out_dir)
    return ExperimentResult(task="sweep", meta=meta, metrics=None, artifacts={"dir": str(out_dir)})


def run_walkforward_experiment(
    cfg_path: str,
    n_segments: int = 3,
    train_ratio: float = 0.7,
    min_trades: int = 10,
) -> ExperimentResult:
    logger = setup_logger("experiment")
    cfg = load_config(cfg_path, load_env=False, expand_env=False)
    bt_cfg = cfg.backtest or {}
    meta = {
        "symbol": bt_cfg.get("symbol", cfg.symbol),
        "interval": bt_cfg.get("interval", cfg.timeframe),
        "start": bt_cfg.get("start"),
        "end": bt_cfg.get("end"),
        "run_ts": _utc_ts(),
        "git": _git_info(),
        "n_segments": n_segments,
        "train_ratio": train_ratio,
        "min_trades": min_trades,
    }
    out_dir = _experiment_dir("walkforward", meta)
    _ensure_config_snapshot(cfg_path, out_dir)
    logger.info("Walkforward experiment dir: %s", out_dir)

    res = walk_forward(
        cfg_path=cfg_path,
        n_segments=n_segments,
        train_ratio=train_ratio,
        min_trades=min_trades,
        output_dir=str(out_dir / "segments"),
        artifacts_base_dir=str(out_dir / "segments"),
    )
    (out_dir / "results.json").write_text(
        json.dumps({"task": "walkforward", "meta": meta, "results": res}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report_md(out_dir / "report.md", task="walkforward", meta=meta, summary=res, artifacts={"dir": str(out_dir)})
    overall = res.get("overall") if isinstance(res, dict) else {}
    write_summary_md(out_dir / "summary.md", task="walkforward", meta=meta, metrics=overall if isinstance(overall, dict) else {})
    logger.info("Experiment saved: %s", out_dir)
    return ExperimentResult(task="walkforward", meta=meta, metrics=res.get("overall"), artifacts={"dir": str(out_dir)})


def run_experiment(cfg_path: str, task: str, **kwargs) -> ExperimentResult:
    """统一实验入口。"""
    task = task.strip().lower()
    if task == "backtest":
        return run_backtest_experiment(cfg_path)
    if task == "sweep":
        return run_sweep_experiment(cfg_path, top_n=int(kwargs.get("top_n", 5)))
    if task == "walkforward":
        return run_walkforward_experiment(
            cfg_path,
            n_segments=int(kwargs.get("n_segments", 3)),
            train_ratio=float(kwargs.get("train_ratio", 0.7)),
            min_trades=int(kwargs.get("min_trades", 10)),
        )
    raise ValueError(f"Unknown experiment task: {task}")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m research.experiment", description="实验入口：backtest / sweep / walkforward")
    p.add_argument("--task", required=True, choices=["backtest", "sweep", "walkforward"], help="实验类型")
    p.add_argument("--cfg", required=True, help="配置文件路径，如 config/config.yml")
    p.add_argument("--top-n", "--top_n", dest="top_n", type=int, default=5, help="sweep: 取 top N 组合（默认 5）")
    p.add_argument(
        "--n-segments",
        "--n_segments",
        dest="n_segments",
        type=int,
        default=3,
        help="walkforward: 分段数（默认 3）",
    )
    p.add_argument(
        "--train-ratio",
        "--train_ratio",
        dest="train_ratio",
        type=float,
        default=0.7,
        help="walkforward: 训练集占比（默认 0.7）",
    )
    p.add_argument(
        "--min-trades",
        "--min_trades",
        dest="min_trades",
        type=int,
        default=10,
        help="walkforward: 最小交易次数（默认 10）",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    cfg_path = str(args.cfg)
    if not Path(cfg_path).exists():
        raise SystemExit(f"Config file not found: {cfg_path}")

    res = run_experiment(
        cfg_path=cfg_path,
        task=str(args.task),
        top_n=int(args.top_n),
        n_segments=int(args.n_segments),
        train_ratio=float(args.train_ratio),
        min_trades=int(args.min_trades),
    )
    # 给 IDE/CI 一个稳定“验收点”输出：实验目录
    out_dir = None
    if res.artifacts and isinstance(res.artifacts, dict):
        out_dir = res.artifacts.get("dir")
    if out_dir:
        print(out_dir)
    else:
        print(json.dumps(asdict(res), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
