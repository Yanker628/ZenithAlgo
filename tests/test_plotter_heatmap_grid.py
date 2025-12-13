from __future__ import annotations

import csv
from pathlib import Path

from analysis.visualizations.plotter import _prepare_heatmap_pivot


def _write_sweep_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        # long_window=60 全部 sharpe<0 -> 过滤后应显示为空白但保留列
        (60, 0.05, -1.0, 20, 0.1, 0.5),
        (60, 0.10, -1.0, 20, 0.1, 0.5),
        (60, 0.20, -1.0, 20, 0.1, 0.5),
        (90, 0.05, 0.1, 20, 0.1, 0.3),
        (90, 0.10, 0.1, 20, 0.1, 0.2),
        (90, 0.20, 0.1, 20, 0.1, 0.1),
        (120, 0.05, 0.1, 20, 0.1, 0.4),
        (120, 0.10, 0.1, 20, 0.1, 0.2),
        (120, 0.20, 0.1, 20, 0.1, 0.1),
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["long_window", "slope_threshold", "sharpe", "total_trades", "max_drawdown", "score"])
        for r in rows:
            w.writerow(r)


def test_prepare_heatmap_pivot_keeps_full_grid_with_masked_filters(tmp_path: Path):
    csv_path = tmp_path / "sweep.csv"
    _write_sweep_csv(csv_path)

    import pandas as pd

    df = pd.read_csv(csv_path)
    pivot = _prepare_heatmap_pivot(
        df,
        x_param="long_window",
        y_param="slope_threshold",
        value_param="score",
        x_values=[60, 90, 120],
        y_values=[0.05, 0.1, 0.2],
        filters={"min_sharpe": 0.0},
        mask_filtered=True,
    )
    assert list(pivot.columns) == [60, 90, 120]
    assert list(pivot.index) == [0.05, 0.1, 0.2]
