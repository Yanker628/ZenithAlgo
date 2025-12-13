"""参数优化引擎（OptimizationEngine）。

目标：统一为 Engine 风格的入口（`run() -> EngineResult`），把“扫参/批量回测”当作一种研究引擎。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from engine.backtest_engine import BacktestEngine
from engine.base_engine import BaseEngine, EngineResult
from shared.config.config_loader import load_config
from shared.utils.logging import setup_logger
from utils.param_search import grid_search, random_search, SweepResult
from analysis.visualizations.plotter import plot_sweep_heatmap


def _run_sweep_for_symbol(cfg_path: str, symbol: str, sweep_cfg: dict, *, logger=None) -> List[SweepResult]:
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
    if not getattr(cfg, "backtest", None):
        raise ValueError("backtest config not found")
    cfg.backtest["symbol"] = str(symbol)  # type: ignore[index]

    mode = sweep_cfg.get("mode", "grid")
    param_grid = sweep_cfg.get("params", {})  # 注意：你的 yml 里叫 params，不是 param_grid

    # 从 objective 里抽权重，转成 param_search 期望的 weights 结构
    obj = sweep_cfg.get("objective", {}) or {}
    weights = {
        "total_return": float(obj.get("total_return_weight", 0.0)),
        "sharpe": float(obj.get("sharpe_weight", 0.0)),
        "max_drawdown": float(obj.get("max_drawdown_weight", 0.0)),
    }

    output_csv = sweep_cfg.get("output_csv")  # 你以后想把结果落盘可以在 yml 里加
    if not output_csv:
        interval = cfg.backtest.get("interval", "NA")  # type: ignore[index]
        output_csv = f"dataset/research/ma_sweep_{symbol}_{interval}.csv"

    # 过滤/惩罚配置
    min_trades = sweep_cfg.get("min_trades")
    max_dd_filter = sweep_cfg.get("max_drawdown")
    min_sharpe = sweep_cfg.get("min_sharpe")
    low_trades_penalty = float(sweep_cfg.get("low_trades_penalty", 0.0))
    filters = {
        "min_trades": min_trades,
        "max_drawdown": max_dd_filter,
        "min_sharpe": min_sharpe,
    }

    if mode == "random":
        n_samples = int(sweep_cfg.get("n_random", 20))
        return random_search(
            cfg_path,
            param_grid,
            n_samples,
            weights,
            output_csv,
            cfg_obj=cfg,
            filters=filters,
            low_trades_penalty=low_trades_penalty,
        )
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
        try:
            stem = Path(output_csv).stem.replace("ma_sweep_", "")
            heatmap_path = Path("plots") / f"{stem}_heatmap.png"
            heatmap_path.parent.mkdir(parents=True, exist_ok=True)
            plot_sweep_heatmap(output_csv, save_path=str(heatmap_path), filters=filters)
        except Exception as exc:
            if logger is not None:
                logger.warning("热力图生成失败，已跳过：%s", exc)
        return results


class OptimizationEngine(BaseEngine):
    """参数优化/批量回测引擎。

    - 若 `backtest.sweep.enabled=true`：跑 sweep 并返回每个 symbol 的结果列表（按 score 降序）。
    - 否则：返回单次回测 summary（等价 `BacktestEngine`）。
    """

    def __init__(self, *, cfg_path: str = "config/config.yml", top_n: int = 5):
        self._cfg_path = cfg_path
        self._top_n = int(top_n)

    def run(self) -> EngineResult:
        logger = setup_logger("optimize")
        cfg = load_config(self._cfg_path, load_env=False, expand_env=False)
        bt_cfg = getattr(cfg, "backtest", None)
        if not isinstance(bt_cfg, dict):
            raise ValueError("backtest config not found")

        sweep_cfg = bt_cfg.get("sweep")
        if not isinstance(sweep_cfg, dict) or not sweep_cfg.get("enabled"):
            summary = BacktestEngine(cfg_path=self._cfg_path).run().summary
            return EngineResult(summary=summary)

        symbols_cfg = bt_cfg.get("symbols")
        symbols = [str(s) for s in symbols_cfg] if symbols_cfg else [str(bt_cfg.get("symbol"))]

        all_results: dict[str, list[dict[str, Any]]] = {}
        for sym in symbols:
            results = _run_sweep_for_symbol(self._cfg_path, sym, sweep_cfg, logger=logger)
            res_sorted = sorted(results, key=lambda r: r.score, reverse=True)
            all_results[sym] = [
                {"symbol": r.symbol, "params": r.params, "metrics": r.metrics, "score": r.score, "passed": r.passed}
                for r in res_sorted[: self._top_n]
            ]

        return EngineResult(summary={"results": all_results, "top_n": self._top_n})
