"""实验可复现入口（V2.3）。

统一把一次 backtest / sweep / walkforward 的产物落盘到 data/experiments/ 下：
- results.json
- config.yml（配置快照）
- report.md
并在需要时落盘 trades.csv / equity.csv / 图表等。
"""

from __future__ import annotations

import json
import shutil
import subprocess
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
from utils.plotter import plot_sweep_heatmaps
from research.report import write_report_md


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
    out_dir.mkdir(parents=True, exist_ok=True)
    # 1) 原始配置快照
    try:
        shutil.copy2(cfg_path, out_dir / "config.yml")
    except Exception:
        pass
    # 2) 生效配置快照（解析后的对象）
    try:
        cfg_obj = load_config(cfg_path, load_env=False, expand_env=False)
        _dump_effective_cfg(cfg_obj, out_dir / "effective_config.json")
    except Exception:
        pass


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
    summary, _ = run_backtest(cfg_obj=cfg, artifacts_dir=out_dir)
    metrics = summary.get("metrics", {})
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

        # 热力图（基础版：short_window x long_window -> score）
        heatmaps_dir = sym_dir / "heatmaps"
        try:
            plot_sweep_heatmaps(
                str(sweep_csv),
                x_param="short_window",
                y_param="long_window",
                value_param="score",
                save_dir=heatmaps_dir,
                filters=filters,
            )
            # 尝试对额外维度做切片（>=3 张时更有用）
            import pandas as pd  # type: ignore

            df = pd.read_csv(sweep_csv)
            candidates = [c for c in df.columns if c not in {"symbol", "score", "short_window", "long_window"}]
            slice_param = None
            for c in candidates:
                if df[c].nunique(dropna=True) >= 3:
                    slice_param = c
                    break
            if slice_param:
                plot_sweep_heatmaps(
                    str(sweep_csv),
                    x_param="short_window",
                    y_param="long_window",
                    value_param="score",
                    slice_param=slice_param,
                    save_dir=heatmaps_dir / f"slices_{slice_param}",
                    filters=filters,
                )
        except Exception:
            pass

        best = sorted(results, key=lambda r: r.score, reverse=True)[: max(1, int(top_n))]
        best_params = best[0].params if best else {}

        # 用最佳参数跑一次 backtest，生成 trades/equity/report
        best_bt_dir = sym_dir / "best_backtest"
        cfg_best = deepcopy(cfg_sym)
        cfg_best.backtest = deepcopy(cfg_best.backtest) if cfg_best.backtest else {}  # type: ignore[assignment]
        cfg_best.backtest.update(best_params)  # type: ignore[union-attr]
        cfg_best.backtest["skip_plots"] = False  # type: ignore[index]
        bt_summary, _ = run_backtest(cfg_obj=cfg_best, artifacts_dir=best_bt_dir)

        all_results[sym] = {
            "sweep_csv": str(sweep_csv),
            "filter_stats_json": str(sym_dir / f"{sweep_csv.stem}_filter_stats.json")
            if (sym_dir / f"{sweep_csv.stem}_filter_stats.json").exists()
            else None,
            "heatmaps_dir": str(heatmaps_dir) if heatmaps_dir.exists() else None,
            "top": [{"params": r.params, "metrics": r.metrics, "score": r.score} for r in best],
            "best_params": best_params,
            "best_backtest": {"dir": str(best_bt_dir), "metrics": bt_summary.get("metrics", {})},
        }

    payload = {"task": "sweep", "meta": meta, "symbols": all_results}
    (out_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report_md(out_dir / "report.md", task="sweep", meta=meta, summary=payload, artifacts={"dir": str(out_dir)})
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
