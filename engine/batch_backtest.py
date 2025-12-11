from __future__ import annotations

from typing import Any, Dict, List
from pathlib import Path

from engine.backtest_runner import run_backtest
from utils.config_loader import load_config
from utils.param_search import grid_search, random_search, SweepResult
from utils.plotter import plot_sweep_heatmap


def run_single_backtest(cfg_obj, symbol: str | None = None, strategy_params: dict | None = None):
    cfg = cfg_obj
    bt_cfg = cfg.backtest
    if symbol:
        bt_cfg["symbol"] = symbol
    if strategy_params:
        bt_cfg.update(strategy_params)
    cfg.backtest = bt_cfg  # type: ignore[assignment]
    return run_backtest(cfg_obj=cfg)


def run_sweep_for_symbol(cfg_path: str, symbol: str, sweep_cfg: dict) -> List[SweepResult]:
    """
    对单个 symbol 跑参数搜索。

    sweep_cfg 来自 cfg.backtest["sweep"]，字段：
      - mode: grid / random
      - n_random: int (仅 random 用)
      - params: 参数网格
      - objective: 各指标权重
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
        output_csv = f"data/research/ma_sweep_{symbol}_{interval}.csv"

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
            print(f"[WARN] heatmap skipped: {exc}")
        return results


def batch_backtest(cfg_path: str = "config/config.yml", top_n: int = 5):
    cfg = load_config(cfg_path, load_env=False, expand_env=False)
    bt_cfg = getattr(cfg, "backtest", None)
    if bt_cfg is None:
        raise ValueError("backtest config not found")

    # ✅ 关键：从 backtest 里拿 sweep，而不是 cfg.sweep
    sweep_cfg = bt_cfg.get("sweep")
    if not sweep_cfg or not sweep_cfg.get("enabled"):
        # 没开 sweep，就按单次回测跑
        summary = run_backtest(cfg_path=cfg_path)
        print(f"Backtest summary: {summary}")
        return summary

    # 支持多品种：backtest.symbols 优先，否则 fallback 到 backtest.symbol
    symbols_cfg = bt_cfg.get("symbols")
    if symbols_cfg:
        symbols = [str(s) for s in symbols_cfg]
    else:
        symbols = [str(bt_cfg.get("symbol"))]

    all_results: dict[str, List[SweepResult]] = {}
    for sym in symbols:
        res = run_sweep_for_symbol(cfg_path, sym, sweep_cfg)
        # 按 score 排序
        res_sorted = sorted(res, key=lambda r: r.score, reverse=True)
        all_results[sym] = res_sorted

        print(f"=== {sym} Sweep Top {top_n} ===")
        for idx, r in enumerate(res_sorted[:top_n], 1):
            print(
                f"{idx}. score={r.score:.3f}  "
                f"ret={r.metrics.get('total_return', 0):.3f}  "
                f"dd={r.metrics.get('max_drawdown', 0):.3f}  "
                f"sharpe={r.metrics.get('sharpe', 0):.3f}  "
                f"trades={r.metrics.get('total_trades', 0)}  "
                f"win_rate={r.metrics.get('win_rate', 0):.1%}  "
                f"params={r.params}"
            )

    return all_results


if __name__ == "__main__":
    batch_backtest()
