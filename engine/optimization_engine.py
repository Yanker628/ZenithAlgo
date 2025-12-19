"""参数优化引擎（OptimizationEngine）。

目标：统一为 Engine 风格的入口（`run() -> EngineResult`），把“扫参/批量回测”当作一种研究引擎。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from database.dataset_store import DatasetStore
from engine.backtest_engine import BacktestEngine
from engine.base_engine import BaseEngine, EngineResult
from shared.config.config_loader import BacktestConfig, SweepConfig, load_config
from shared.utils.logging import setup_logger
from utils.param_search import grid_search, random_search, SweepResult
from analysis.visualizations.plotter import plot_sweep_heatmap


def _run_sweep_for_symbol(
    *,
    cfg_path: str,
    symbol: str,
    sweep_cfg: SweepConfig,
    output_dir: Path,
    logger=None,
) -> tuple[List[SweepResult], dict[str, Any]]:
    """对单个 symbol 跑参数搜索。

    Parameters
    ----------
    cfg_path:
        配置路径。
    symbol:
        回测品种。
    sweep_cfg:
        `backtest.sweep` 配置段。

    Returns
    -------
    list[SweepResult]
        每组参数的回测结果与得分。
    """
    cfg = load_config(cfg_path, load_env=False, expand_env=False)

    # 把 symbol 写回 backtest 配置里，方便 run_backtest / param_search 使用
    if not isinstance(getattr(cfg, "backtest", None), BacktestConfig):
        raise ValueError("backtest config not found")
    cfg.backtest.symbol = str(symbol)  # type: ignore[union-attr]

    mode = str(sweep_cfg.mode or "grid")
    param_grid = dict(sweep_cfg.params or {})

    # 从 objective 里抽权重，转成 param_search 期望的 weights 结构
    obj = sweep_cfg.objective
    weights = {
        "total_return": float(obj.total_return_weight),
        "sharpe": float(obj.sharpe_weight),
        "max_drawdown": float(obj.max_drawdown_weight),
    }

    interval = cfg.backtest.interval  # type: ignore[union-attr]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = str(output_dir / f"{symbol}_{interval}_sweep.csv")

    # 过滤/惩罚配置
    min_trades = sweep_cfg.min_trades
    max_dd_filter = sweep_cfg.max_drawdown
    min_sharpe = sweep_cfg.min_sharpe
    low_trades_penalty = float(sweep_cfg.low_trades_penalty)
    filters = {
        "min_trades": min_trades,
        "max_drawdown": max_dd_filter,
        "min_sharpe": min_sharpe,
    }

    if mode == "random":
        n_samples = int(sweep_cfg.n_random)
        results = random_search(
            cfg_path,
            param_grid,
            n_samples,
            weights,
            output_csv,
            cfg_obj=cfg,
            filters=filters,
            low_trades_penalty=low_trades_penalty,
        )
        return results, {"csv": output_csv, "heatmap_png": None}
    else:
        results = grid_search(
            cfg_path,
            param_grid,
            weights,
            output_csv,
            cfg_obj=cfg,
            filters=filters,
            low_trades_penalty=low_trades_penalty,
        )
        # 生成热力图（可选）
        heatmap_path = None
        try:
            stem = Path(output_csv).stem
            plots_dir = output_dir / "plots"
            plots_dir.mkdir(parents=True, exist_ok=True)
            heatmap_path = plots_dir / f"{stem}_heatmap.png"
            plot_sweep_heatmap(output_csv, save_path=str(heatmap_path), filters=filters)
        except Exception as exc:
            if logger is not None:
                logger.warning("热力图生成失败，已跳过：%s", exc)
        return results, {"csv": output_csv, "heatmap_png": str(heatmap_path) if heatmap_path else None}


class OptimizationEngine(BaseEngine):
    """参数优化/批量回测引擎。

    - 若 `backtest.sweep.enabled=true`：跑 sweep 并返回每个 symbol 的结果列表（按 score 降序）。
    - 否则：返回单次回测 summary（等价 `BacktestEngine`）。
    """

    def __init__(
        self,
        *,
        cfg_path: str = "config/config.yml",
        top_n: int = 5,
        artifacts_dir: str | Path | None = None,
    ):
        self._cfg_path = cfg_path
        self._top_n = int(top_n)
        self._artifacts_dir = artifacts_dir

    def run(self) -> EngineResult:
        logger = setup_logger("optimize")
        cfg = load_config(self._cfg_path, load_env=False, expand_env=False)
        bt_cfg = getattr(cfg, "backtest", None)
        if not isinstance(bt_cfg, BacktestConfig):
            raise ValueError("backtest config not found")

        sweep_cfg = bt_cfg.sweep
        if sweep_cfg is None or not sweep_cfg.enabled:
            logger.info("Using Engine: BacktestEngine (Standard)")
            summary = BacktestEngine(cfg_path=self._cfg_path).run().summary
            return EngineResult(summary=summary)
        
        logger.info("Using Engine: OptimizationEngine (Sweep Mode)")

        symbols_cfg = bt_cfg.symbols
        symbols = [str(s) for s in symbols_cfg] if symbols_cfg else [str(bt_cfg.symbol)]
        DatasetStore(bt_cfg.data_dir).ensure_meta_for_symbols(symbols, str(bt_cfg.interval))

        base_out_dir = Path(self._artifacts_dir) if self._artifacts_dir is not None else Path("results") / "sweep_engine"
        base_out_dir.mkdir(parents=True, exist_ok=True)

        all_results: dict[str, list[dict[str, Any]]] = {}
        artifacts: dict[str, Any] = {"dir": str(base_out_dir), "symbols": {}}
        for sym in symbols:
            sym_dir = base_out_dir / sym
            logger.info("Sweep start: symbol=%s out_dir=%s", sym, sym_dir)
            results, sym_art = _run_sweep_for_symbol(
                cfg_path=self._cfg_path,
                symbol=sym,
                sweep_cfg=sweep_cfg,
                output_dir=sym_dir,
                logger=logger,
            )
            res_sorted = sorted(results, key=lambda r: r.score, reverse=True)
            all_results[sym] = [
                {"symbol": r.symbol, "params": r.params, "metrics": r.metrics, "score": r.score, "passed": r.passed}
                for r in res_sorted[: self._top_n]
            ]
            artifacts["symbols"][sym] = sym_art

        return EngineResult(summary={"results": all_results, "top_n": self._top_n}, artifacts=artifacts)
