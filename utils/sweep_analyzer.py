from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List


@dataclass
class SweepResult:
    symbol: str
    params: dict
    metrics: dict
    score: float


def load_sweep_results(path: str | Path) -> List[SweepResult]:
    path = Path(path)
    rows: List[SweepResult] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            params = {
                k: row[k]
                for k in row.keys()
                if k
                not in {
                    "symbol",
                    "score",
                    "total_return",
                    "max_drawdown",
                    "sharpe",
                    "win_rate",
                    "avg_win",
                    "avg_loss",
                    "total_trades",
                }
            }
            metrics = {
                k: row.get(k)
                for k in [
                    "total_return",
                    "max_drawdown",
                    "sharpe",
                    "win_rate",
                    "avg_win",
                    "avg_loss",
                    "total_trades",
                ]
            }
            # 尝试把数值字段转成 float/int
            for mk in list(metrics.keys()):
                v = metrics[mk]
                try:
                    metrics[mk] = float(v) if v not in (None, "") else 0.0
                except Exception:
                    pass
            for pk in list(params.keys()):
                v = params[pk]
                try:
                    params[pk] = float(v) if "." in str(v) else int(v)
                except Exception:
                    pass
            try:
                score_val = float(row.get("score", 0.0))
            except Exception:
                score_val = 0.0
            rows.append(
                SweepResult(
                    symbol=row.get("symbol", ""),
                    params=params,
                    metrics=metrics,
                    score=score_val,
                )
            )
    return rows


def get_top_n(results: Iterable[SweepResult], n: int = 10, by: str = "score") -> List[SweepResult]:
    key_funcs = {
        "score": lambda r: r.score,
        "sharpe": lambda r: r.metrics.get("sharpe", 0.0),
        "total_return": lambda r: r.metrics.get("total_return", 0.0),
    }
    key_fn = key_funcs.get(by, key_funcs["score"])
    return sorted(results, key=key_fn, reverse=True)[:n]


def filter_results(results: Iterable[SweepResult], cond: Callable[[SweepResult], bool]) -> List[SweepResult]:
    return [r for r in results if cond(r)]
