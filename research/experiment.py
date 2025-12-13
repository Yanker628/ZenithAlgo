"""实验可复现入口（V2.3）。

统一把一次 backtest / sweep / walkforward 的产物落盘到 results/ 下：
- results.json
- config.yml（配置快照）
- report.md
并在需要时落盘 trades.csv / equity.csv / 图表等。
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.backtest_engine import BacktestEngine
from engine.walkforward_engine import WalkforwardEngine
from analysis.metrics.diagnostics import compute_diagnostics
from utils.hashing import sha256_files, sha256_text
from utils.json_sanitize import sanitize_for_json
from analysis.metrics.metrics_canon import canonicalize_metrics, validate_metrics_schema
from utils.policy import evaluate_policy
from shared.config.config_loader import load_config
from shared.utils.logging import setup_logger
from utils.param_search import grid_search, random_search
from analysis.visualizations.plotter import plot_param_1d, plot_param_importance, plot_sweep_heatmaps
from analysis.reports.report import write_report_md, write_summary_md

EXPERIMENT_SCHEMA_VERSION = "1.0"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _config_hash(cfg_path: str) -> str:
    return sha256_text(Path(cfg_path).read_text(encoding="utf-8"))


def _data_hashes(cfg_obj, *, symbols: list[str]) -> tuple[str, dict[str, str]]:
    bt_cfg = getattr(cfg_obj, "backtest", None) or {}
    data_dir = str(bt_cfg.get("data_dir", "dataset/history"))
    interval = str(bt_cfg.get("interval", getattr(cfg_obj, "timeframe", "")))
    paths = [Path(data_dir) / f"{s}_{interval}.csv" for s in symbols]
    return sha256_files(paths)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = sanitize_for_json(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def _write_meta_json(
    out_dir: Path,
    *,
    task: str,
    symbol: str,
    interval: str,
    start: str | None,
    end: str | None,
    run_ts: str,
    git: dict[str, Any],
    config_hash: str,
    data_hash: str,
    data_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "task": task,
        "symbol": symbol,
        "interval": interval,
        "start": start,
        "end": end,
        "created_at": run_ts,
        "run_ts": run_ts,
        "git_sha": git.get("sha"),
        "git_dirty": git.get("dirty"),
        "git": git,
        "config_hash": config_hash,
        "data_hash": data_hash,
    }
    if data_hashes:
        payload["data_hashes"] = data_hashes
    _write_json(out_dir / "meta.json", payload)
    return payload


def _write_summary_json(
    out_dir: Path,
    *,
    task: str,
    metrics: dict[str, Any],
    diagnostics: dict[str, Any],
    policy: dict[str, Any],
    artifacts: dict[str, Any],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = canonicalize_metrics(metrics)
    validate_metrics_schema(metrics)
    payload: dict[str, Any] = {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "task": task,
        "metrics": metrics,
        "diagnostics": diagnostics,
        "policy": policy,
        "artifacts": artifacts,
        "metrics_spec": {"sharpe": "equity_returns"},
    }
    if details is not None:
        payload["details"] = details
    _write_json(out_dir / "summary.json", payload)
    return payload


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
    run_id = str(meta.get("run_id") or meta.get("run_ts") or _utc_ts())
    return Path("results") / task / symbol / interval / f"{start}_{end}" / run_id


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
    run_id = _utc_ts()
    run_ts = _utc_iso()
    meta = {
        "symbol": bt_cfg.get("symbol", cfg.symbol),
        "interval": bt_cfg.get("interval", cfg.timeframe),
        "start": bt_cfg.get("start"),
        "end": bt_cfg.get("end"),
        "run_id": run_id,
        "run_ts": run_ts,
        "git": _git_info(),
    }
    out_dir = _experiment_dir("backtest", meta)
    _ensure_config_snapshot(cfg_path, out_dir)
    summary = BacktestEngine(cfg_obj=cfg, artifacts_dir=out_dir).run().summary
    metrics = canonicalize_metrics(summary.get("metrics", {}) if isinstance(summary, dict) else {})
    artifacts = {
        "dir": str(out_dir),
        "trades_csv": "trades.csv",
        "equity_csv": "equity.csv",
        "equity_png": "equity.png",
        "drawdown_png": "drawdown.png",
        "return_hist_png": "return_hist.png",
    }
    cfg_hash = _config_hash(cfg_path)
    data_hash, data_hashes = _data_hashes(cfg, symbols=[str(meta["symbol"])])
    meta_json = _write_meta_json(
        out_dir,
        task="backtest",
        symbol=str(meta["symbol"]),
        interval=str(meta["interval"]),
        start=meta.get("start"),
        end=meta.get("end"),
        run_ts=run_ts,
        git=meta["git"],
        config_hash=cfg_hash,
        data_hash=data_hash,
        data_hashes=data_hashes,
    )
    diagnostics = compute_diagnostics(metrics)
    policy = evaluate_policy(metrics, policy_cfg=None, stage="research", git_dirty=bool(meta["git"].get("dirty")))
    summary_json = _write_summary_json(
        out_dir,
        task="backtest",
        metrics=metrics,
        diagnostics=diagnostics,
        policy=policy,
        artifacts=artifacts,
        details={
            "signal_trace": summary.get("signal_trace") if isinstance(summary, dict) else None,
            "data_health": summary.get("data_health") if isinstance(summary, dict) else None,
        },
    )
    _write_json(
        out_dir / "results.json",
        {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "task": "backtest",
            "meta": meta,
            "meta_json": meta_json,
            "summary": summary,
            "summary_json": summary_json,
            "artifacts": artifacts,
        },
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
    run_id = _utc_ts()
    run_ts = _utc_iso()
    meta = {
        "symbol": bt_cfg.get("symbol", cfg.symbol),
        "interval": bt_cfg.get("interval", cfg.timeframe),
        "start": bt_cfg.get("start"),
        "end": bt_cfg.get("end"),
        "run_id": run_id,
        "run_ts": run_ts,
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

        passed = [r for r in results if getattr(r, "passed", True)]
        pool = passed if passed else results
        best = sorted(pool, key=lambda r: r.score, reverse=True)[: max(1, int(top_n))]
        best_params = best[0].params if best else {}

        # 用最佳参数跑一次 backtest，生成 trades/equity/report
        best_bt_dir = sym_dir / "best_backtest"
        cfg_best = deepcopy(cfg_sym)
        cfg_best.backtest = deepcopy(cfg_best.backtest) if cfg_best.backtest else {}  # type: ignore[assignment]
        bt_strategy = dict(cfg_best.backtest.get("strategy", {}) or {})  # type: ignore[union-attr]
        bt_strategy.update(best_params)
        cfg_best.backtest["strategy"] = bt_strategy  # type: ignore[index]
        cfg_best.backtest["skip_plots"] = False  # type: ignore[index]
        bt_summary = BacktestEngine(cfg_obj=cfg_best, artifacts_dir=best_bt_dir).run().summary
        bt_metrics = canonicalize_metrics(bt_summary.get("metrics", {}) if isinstance(bt_summary, dict) else {})

        all_results[sym] = {
            "sweep_csv": str(sweep_csv),
            "filter_stats_json": str(sym_dir / f"{sweep_csv.stem}_filter_stats.json")
            if (sym_dir / f"{sweep_csv.stem}_filter_stats.json").exists()
            else None,
            "heatmaps_dir": str(heatmaps_dir) if heatmaps_dir.exists() else None,
            "plots": plots,
            "viz": viz,
            "top": [
                {
                    "params": r.params,
                    "metrics": r.metrics,
                    "score": r.score,
                    "passed": getattr(r, "passed", True),
                    "filter_reason": getattr(r, "filter_reason", None),
                }
                for r in best
            ],
            "best_params": best_params,
            "best_backtest": {
                "dir": str(best_bt_dir),
                "metrics": bt_metrics,
                "data_health": bt_summary.get("data_health", {}),  # type: ignore
            },
            "policy": {"filters": filters, "passed_any": bool(passed)},
        }

        # best_backtest 子实验 meta/summary（继承父 meta）
        try:
            cfg_hash = _config_hash(cfg_path)
            dh, dhs = _data_hashes(cfg, symbols=[sym])
            _write_meta_json(
                best_bt_dir,
                task="backtest",
                symbol=sym,
                interval=str(meta["interval"]),
                start=meta.get("start"),
                end=meta.get("end"),
                run_ts=run_ts,
                git=meta["git"],
                config_hash=cfg_hash,
                data_hash=dh,
                data_hashes=dhs,
            )
            _write_summary_json(
                best_bt_dir,
                task="backtest",
                metrics=bt_metrics,
                diagnostics=compute_diagnostics(bt_metrics),
                policy=evaluate_policy(
                    bt_metrics,
                    policy_cfg=(filters if isinstance(filters, dict) else None),
                    stage="research",
                    git_dirty=bool(meta["git"].get("dirty")),
                ),
                artifacts={"dir": str(best_bt_dir), "trades_csv": "trades.csv", "equity_csv": "equity.csv"},
                details={"parent": str(sym_dir / "meta.json")},
            )
        except Exception:
            pass

        # 子实验 meta（继承父 meta）
        try:
            cfg_hash = _config_hash(cfg_path)
            dh, dhs = _data_hashes(cfg, symbols=[sym])
            _write_meta_json(
                sym_dir,
                task="sweep",
                symbol=sym,
                interval=str(meta["interval"]),
                start=meta.get("start"),
                end=meta.get("end"),
                run_ts=run_ts,
                git=meta["git"],
                config_hash=cfg_hash,
                data_hash=dh,
                data_hashes=dhs,
            )
            _write_summary_json(
                sym_dir,
                task="sweep",
                metrics=bt_metrics,
                diagnostics=compute_diagnostics(bt_metrics),
                policy=evaluate_policy(
                    bt_metrics,
                    policy_cfg=(filters if isinstance(filters, dict) else None),
                    stage="research",
                    git_dirty=bool(meta["git"].get("dirty")),
                ),
                artifacts={"dir": str(sym_dir), "sweep_csv": str(sweep_csv), "best_backtest_dir": str(best_bt_dir)},
                details={"symbol": sym, "top": all_results[sym].get("top"), "viz": viz},
            )
        except Exception:
            pass

    cfg_hash = _config_hash(cfg_path)
    data_hash, data_hashes = _data_hashes(cfg, symbols=symbols)
    meta_json = _write_meta_json(
        out_dir,
        task="sweep",
        symbol=str(meta["symbol"]),
        interval=str(meta["interval"]),
        start=meta.get("start"),
        end=meta.get("end"),
        run_ts=run_ts,
        git=meta["git"],
        config_hash=cfg_hash,
        data_hash=data_hash,
        data_hashes=data_hashes,
    )
    payload = {"task": "sweep", "meta": meta, "symbols": all_results}
    # sweep 总体 summary：用第一个 symbol 的 best_backtest 作为 metrics 概览
    first_sym = next(iter(all_results.values()), {}) if all_results else {}
    bb = first_sym.get("best_backtest") if isinstance(first_sym, dict) else {}
    metrics = canonicalize_metrics(dict(bb.get("metrics", {}) or {}) if isinstance(bb, dict) else {})
    diagnostics = compute_diagnostics(metrics)
    policy_cfg = sweep_cfg.get("filters") or {
        "min_trades": sweep_cfg.get("min_trades"),
        "max_drawdown": sweep_cfg.get("max_drawdown"),
        "min_sharpe": sweep_cfg.get("min_sharpe"),
    }
    policy = evaluate_policy(metrics, policy_cfg=policy_cfg if isinstance(policy_cfg, dict) else None, stage="research", git_dirty=bool(meta["git"].get("dirty")))
    summary_json = _write_summary_json(
        out_dir,
        task="sweep",
        metrics=metrics,
        diagnostics=diagnostics,
        policy=policy,
        artifacts={"dir": str(out_dir)},
        details={"symbols": all_results},
    )
    _write_json(
        out_dir / "results.json",
        {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "task": "sweep",
            "meta": meta,
            "meta_json": meta_json,
            "summary_json": summary_json,
            "symbols": all_results,
        },
    )
    write_report_md(out_dir / "report.md", task="sweep", meta=meta, summary=payload, artifacts={"dir": str(out_dir)})
    plots = first_sym.get("plots") if isinstance(first_sym, dict) else None  # type: ignore
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
    run_id = _utc_ts()
    run_ts = _utc_iso()
    meta = {
        "symbol": bt_cfg.get("symbol", cfg.symbol),
        "interval": bt_cfg.get("interval", cfg.timeframe),
        "start": bt_cfg.get("start"),
        "end": bt_cfg.get("end"),
        "run_id": run_id,
        "run_ts": run_ts,
        "git": _git_info(),
        "n_segments": n_segments,
        "train_ratio": train_ratio,
        "min_trades": min_trades,
    }
    out_dir = _experiment_dir("walkforward", meta)
    _ensure_config_snapshot(cfg_path, out_dir)
    logger.info("Walkforward experiment dir: %s", out_dir)

    res = WalkforwardEngine(
        cfg_path=cfg_path,
        n_segments=n_segments,
        train_ratio=train_ratio,
        min_trades=min_trades,
        output_dir=str(out_dir / "segments"),
        artifacts_base_dir=str(out_dir / "segments"),
    ).run().summary
    cfg_hash = _config_hash(cfg_path)
    data_hash, data_hashes = _data_hashes(cfg, symbols=[str(meta["symbol"])])
    meta_json = _write_meta_json(
        out_dir,
        task="walkforward",
        symbol=str(meta["symbol"]),
        interval=str(meta["interval"]),
        start=meta.get("start"),
        end=meta.get("end"),
        run_ts=run_ts,
        git=meta["git"],
        config_hash=cfg_hash,
        data_hash=data_hash,
        data_hashes=data_hashes,
    )
    overall = res.get("overall") if isinstance(res, dict) else {}
    overall_metrics = canonicalize_metrics(overall if isinstance(overall, dict) else {})
    diagnostics = compute_diagnostics(overall_metrics)
    policy = evaluate_policy(overall_metrics, policy_cfg=None, stage="research", git_dirty=bool(meta["git"].get("dirty")))
    try:
        segments = res.get("segments") if isinstance(res, dict) else None
        if isinstance(segments, list):
            for i, seg in enumerate(segments, 1):
                if not isinstance(seg, dict):
                    continue
                seg_metrics = canonicalize_metrics(seg.get("metrics", {}) if isinstance(seg.get("metrics"), dict) else {})
                seg_art_dir = seg.get("artifacts_dir")
                if isinstance(seg_art_dir, str) and seg_art_dir:
                    p = Path(seg_art_dir)
                    _write_meta_json(
                        p,
                        task="backtest",
                        symbol=str(meta["symbol"]),
                        interval=str(meta["interval"]),
                        start=str((seg.get("test") or [None, None])[0]),
                        end=str((seg.get("test") or [None, None])[1]),
                        run_ts=run_ts,
                        git=meta["git"],
                        config_hash=cfg_hash,
                        data_hash=data_hash,
                        data_hashes=data_hashes,
                    )
                    _write_summary_json(
                        p,
                        task="backtest",
                        metrics=seg_metrics,
                        diagnostics=compute_diagnostics(seg_metrics),
                        policy=evaluate_policy(seg_metrics, policy_cfg=None, stage="research", git_dirty=bool(meta["git"].get("dirty"))),
                        artifacts={"dir": str(p), "trades_csv": "trades.csv", "equity_csv": "equity.csv"},
                        details={"parent": str(out_dir / "meta.json"), "segment_idx": i, "train": seg.get("train"), "test": seg.get("test")},
                    )
    except Exception:
        pass
    summary_json = _write_summary_json(
        out_dir,
        task="walkforward",
        metrics=overall_metrics,
        diagnostics=diagnostics,
        policy=policy,
        artifacts={"dir": str(out_dir)},
        details={"results": res},
    )
    _write_json(
        out_dir / "results.json",
        {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "task": "walkforward",
            "meta": meta,
            "meta_json": meta_json,
            "summary_json": summary_json,
            "results": res,
        },
    )
    write_report_md(out_dir / "report.md", task="walkforward", meta=meta, summary=res, artifacts={"dir": str(out_dir)})
    write_summary_md(out_dir / "summary.md", task="walkforward", meta=meta, metrics=overall_metrics)
    logger.info("Experiment saved: %s", out_dir)
    return ExperimentResult(task="walkforward", meta=meta, metrics=overall_metrics, artifacts={"dir": str(out_dir)})


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


"""
注意：该模块不再提供命令行入口。
CLI 统一由仓库根目录 `main.py` 承担（开发阶段避免入口分裂）。
"""
