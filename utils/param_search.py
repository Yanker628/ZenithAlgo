"""参数搜索（Grid/Random Search）。"""

from __future__ import annotations

import csv
import itertools
import random
from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List

from engine.backtest_engine import BacktestEngine
from engine.vector_backtest import run_ma_crossover_vectorized, run_trend_filtered_vectorized
from shared.config.config_loader import BacktestConfig, StrategyConfig, load_config


@dataclass
class SweepResult:
    """一次参数组合回测的结果。"""
    symbol: str
    params: dict
    metrics: dict
    score: float
    passed: bool = True
    filter_reason: str | None = None


def _product_dict(param_grid: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    combos: list[dict] = []
    for vals in itertools.product(*values):
        combo = dict(zip(keys, vals))
        combos.append(combo)
    return combos


def _calc_score(metrics: dict, weights: dict | None, low_trades_penalty: float = 0.0) -> float:
    """
    支持两种权重键名：
    - w_ret / w_sharpe / w_dd （内部默认）
    - total_return / sharpe / max_drawdown （来自 yml objective）
    """
    if not weights:
        weights = {"w_ret": 1.0, "w_sharpe": 0.5, "w_dd": -0.5}
    # 兼容 yml objective 写法
    ret_w = weights.get("w_ret", weights.get("total_return", 0.0))
    sh_w = weights.get("w_sharpe", weights.get("sharpe", 0.0))
    dd_w = weights.get("w_dd", weights.get("max_drawdown", 0.0))
    base_score = (
        ret_w * metrics.get("total_return", 0.0)
        + sh_w * metrics.get("sharpe", 0.0)
        + dd_w * metrics.get("max_drawdown", 0.0)
    )
    trades = metrics.get("total_trades", 0) or 0
    penalty = (low_trades_penalty / trades) if low_trades_penalty and trades > 0 else 0.0
    return base_score - penalty


def _filter_reason(metrics: dict, filters: dict | None) -> str | None:
    if not filters:
        return None
    min_trades = filters.get("min_trades")
    if min_trades is not None and (metrics.get("total_trades", 0) or 0) < min_trades:
        return "min_trades"
    max_dd = filters.get("max_drawdown")
    if max_dd is not None and metrics.get("max_drawdown", 0) > max_dd:
        return "max_drawdown"
    min_sharpe = filters.get("min_sharpe")
    if min_sharpe is not None and metrics.get("sharpe", 0) < min_sharpe:
        return "min_sharpe"
    return None


def passes_policy(metrics: dict, policy_cfg: dict | None) -> bool:
    """兼容旧接口命名（filters=policy）。"""
    return _filter_reason(metrics, policy_cfg) is None


def _write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _prepare_output_path(backtest_cfg: BacktestConfig | dict, output_csv: str | None, prefix: str = "ma_sweep") -> Path:
    if output_csv:
        return Path(output_csv)
    if isinstance(backtest_cfg, BacktestConfig):
        symbol = backtest_cfg.symbol
        interval = backtest_cfg.interval
    else:
        symbol = backtest_cfg.get("symbol", "UNKNOWN")
        interval = backtest_cfg.get("interval", "NA")
    filename = f"{prefix}_{symbol}_{interval}.csv"
    return Path("results") / "research" / filename


def _run_single_combo(
    cfg_base,
    combo: dict,
    weights: dict | None,
    filters: dict | None = None,
    low_trades_penalty: float = 0.0,
) -> SweepResult:
    cfg = cfg_base.model_copy(deep=True) if hasattr(cfg_base, "model_copy") else deepcopy(cfg_base)
    bt_cfg = getattr(cfg, "backtest", None)
    if not isinstance(bt_cfg, BacktestConfig):
        raise ValueError("backtest config not found")

    bt_cfg = bt_cfg.model_copy(deep=True)
    bt_strategy = bt_cfg.strategy.model_copy(deep=True) if bt_cfg.strategy else StrategyConfig(type=cfg.strategy.type, params=dict(cfg.strategy.params))
    bt_strategy.params = {**dict(bt_strategy.params or {}), **dict(combo)}
    bt_cfg.strategy = bt_strategy
    bt_cfg.skip_plots = True
    cfg.backtest = bt_cfg  # type: ignore[assignment]

    use_vectorized = bool(getattr(bt_cfg.sweep, "vectorized", True))
    strategy_type = str(getattr(bt_cfg.strategy, "type", "") or getattr(cfg.strategy, "type", ""))
    if use_vectorized:
        if strategy_type == "simple_ma":
            vec = run_ma_crossover_vectorized(cfg)
            metrics = vec.metrics
        elif strategy_type == "trend_filtered":
            vec = run_trend_filtered_vectorized(cfg)
            metrics = vec.metrics
        else:
            summary = BacktestEngine(cfg_obj=cfg).run().summary
            metrics = summary.metrics.model_dump() if hasattr(summary, "metrics") else {}
    else:
        summary = BacktestEngine(cfg_obj=cfg).run().summary
        metrics = summary.metrics.model_dump() if hasattr(summary, "metrics") else {}
    score = _calc_score(metrics, weights, low_trades_penalty=low_trades_penalty)
    reason = _filter_reason(metrics, filters)
    passed = reason is None
    symbol = bt_cfg.symbol
    return SweepResult(symbol=symbol, params=combo, metrics=metrics, score=score, passed=passed, filter_reason=reason)


def grid_search(
    cfg_path: str,
    param_grid: dict,
    objective_weights: dict | None = None,
    output_csv: str | None = None,
    cfg_obj=None,
    filters: dict | None = None,
    low_trades_penalty: float = 0.0,
) -> List[SweepResult]:
    """网格搜索。

    Parameters
    ----------
    cfg_path:
        配置路径。
    param_grid:
        参数网格，如 {"short_window":[5,10], ...}。
    objective_weights:
        评分权重（可用 w_ret/w_sharpe/w_dd 或 total_return/sharpe/max_drawdown）。
    output_csv:
        输出 CSV 路径；None 时写入默认 `results/research/`。
    cfg_obj:
        已加载配置对象。
    filters:
        过滤条件（min_trades/max_drawdown/min_sharpe）。
    low_trades_penalty:
        交易数过少的惩罚系数。

    Returns
    -------
    list[SweepResult]
        所有组合结果。
    """
    cfg = cfg_obj or load_config(cfg_path, load_env=False, expand_env=False)
    if not isinstance(getattr(cfg, "backtest", None), BacktestConfig):
        raise ValueError("backtest config not found")
    cfg_base = cfg.model_copy(deep=True) if hasattr(cfg, "model_copy") else deepcopy(cfg)

    combos = _product_dict(param_grid)
    results: list[SweepResult] = []
    filter_stats: dict[str, int] = {"min_trades": 0, "max_drawdown": 0, "min_sharpe": 0, "passed": 0}

    for combo in combos:
        res = _run_single_combo(cfg_base, combo, objective_weights, filters, low_trades_penalty)
        results.append(res)
        reason = _filter_reason(res.metrics, filters)
        if reason is None:
            filter_stats["passed"] += 1
        else:
            filter_stats[reason] = filter_stats.get(reason, 0) + 1

    out_path = _prepare_output_path(cfg.backtest, output_csv)  # type: ignore[arg-type]
    rows = []
    for r in results:
        row = {
            "symbol": r.symbol,
            **r.params,
            **r.metrics,
            "score": r.score,
            "passed": r.passed,
            "filter_reason": r.filter_reason,
        }
        rows.append(row)
    _write_csv(out_path, rows)
    try:
        stats_path = out_path.parent / f"{out_path.stem}_filter_stats.json"
        stats_path.write_text(
            __import__("json").dumps(filter_stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return results


def random_search(
    cfg_path: str,
    param_grid: dict,
    n_samples: int,
    objective_weights: dict | None = None,
    output_csv: str | None = None,
    cfg_obj=None,
    filters: dict | None = None,
    low_trades_penalty: float = 0.0,
) -> List[SweepResult]:
    """随机搜索（从网格中抽样 n_samples 组）。"""
    cfg = cfg_obj or load_config(cfg_path, load_env=False, expand_env=False)
    if not isinstance(getattr(cfg, "backtest", None), BacktestConfig):
        raise ValueError("backtest config not found")
    cfg_base = cfg.model_copy(deep=True) if hasattr(cfg, "model_copy") else deepcopy(cfg)

    combos = _product_dict(param_grid)
    if n_samples < len(combos):
        combos = random.sample(combos, n_samples)

    results: list[SweepResult] = []
    filter_stats: dict[str, int] = {"min_trades": 0, "max_drawdown": 0, "min_sharpe": 0, "passed": 0}
    for combo in combos:
        res = _run_single_combo(cfg_base, combo, objective_weights, filters, low_trades_penalty)
        results.append(res)
        reason = _filter_reason(res.metrics, filters)
        if reason is None:
            filter_stats["passed"] += 1
        else:
            filter_stats[reason] = filter_stats.get(reason, 0) + 1

    out_path = _prepare_output_path(cfg.backtest, output_csv, prefix="ma_sweep_random")  # type: ignore[arg-type]
    rows = []
    for r in results:
        row = {
            "symbol": r.symbol,
            **r.params,
            **r.metrics,
            "score": r.score,
            "passed": r.passed,
            "filter_reason": r.filter_reason,
        }
        rows.append(row)
    _write_csv(out_path, rows)
    try:
        stats_path = out_path.parent / f"{out_path.stem}_filter_stats.json"
        stats_path.write_text(
            __import__("json").dumps(filter_stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return results


if __name__ == "__main__":
    grid_search(
        "config/config.yml",
        {
            "short_window": [5, 10],
            "long_window": [20, 50],
            "min_ma_diff": [0.5, 1.0],
        },
    )
