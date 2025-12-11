from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple


def _require_matplotlib():
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("matplotlib 未安装，无法绘图。请先安装 matplotlib。") from exc
    return plt


def _to_series(
    equity_curve: Iterable[Tuple[datetime, float]]
) -> Tuple[List[datetime], List[float]]:
    points = sorted(equity_curve, key=lambda x: x[0])
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return xs, ys


def _to_mpl_time(xs: List[datetime]) -> List[float]:
    # matplotlib 支持 datetime，但类型检查可能提示不兼容，转为数字避免告警
    import matplotlib.dates as mdates  # type: ignore

    return [float(mdates.date2num(x)) for x in xs]


def plot_equity_curve(
    equity_curve: Iterable[Tuple[datetime, float]],
    save_path: str | None = None,
):
    """
    绘制资金曲线，save_path 不传则仅返回 fig。
    """
    plt = _require_matplotlib()
    import matplotlib.dates as mdates  # type: ignore

    xs_dt, ys = _to_series(equity_curve)
    xs = _to_mpl_time(xs_dt)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(xs, ys, label="Equity")
    locator = mdates.AutoDateLocator()
    formatter = mdates.AutoDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    fig.autofmt_xdate()
    ax.set_title("Equity Curve")
    ax.set_xlabel("Time")
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.3)
    ax.legend()

    if save_path:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(path), bbox_inches="tight")
        plt.close(fig)
    return fig


def plot_drawdown(
    equity_curve: Iterable[Tuple[datetime, float]],
    save_path: str | None = None,
):
    """
    绘制回撤曲线（正数表示回撤比例）。
    """
    plt = _require_matplotlib()
    import matplotlib.dates as mdates  # type: ignore

    xs_dt, ys = _to_series(equity_curve)
    xs = _to_mpl_time(xs_dt)
    if not ys:
        return None

    drawdowns: List[float] = []
    peak = ys[0]
    for v in ys:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak else 0.0
        drawdowns.append(dd)

    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(xs, drawdowns, color="tomato", label="Drawdown")
    locator = mdates.AutoDateLocator()
    formatter = mdates.AutoDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    fig.autofmt_xdate()
    ax.set_title("Drawdown")
    ax.set_xlabel("Time")
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.3)
    ax.legend()

    if save_path:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(path), bbox_inches="tight")
        plt.close(fig)
    return fig


def plot_return_hist(
    equity_curve: Iterable[Tuple[datetime, float]],
    save_path: str | None = None,
    bins: int = 30,
):
    """
    简单收益直方图（基于相邻 equity 之比）。
    """
    plt = _require_matplotlib()
    xs_dt, ys = _to_series(equity_curve)
    xs = _to_mpl_time(xs_dt)
    returns: List[float] = []
    for i in range(1, len(ys)):
        prev = ys[i - 1]
        curr = ys[i]
        if prev > 0:
            returns.append((curr / prev) - 1)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(returns, bins=bins, color="steelblue", alpha=0.8)
    ax.set_title("Return Distribution")
    ax.set_xlabel("Return")
    ax.set_ylabel("Frequency")
    ax.grid(True, alpha=0.3)

    if save_path:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(path), bbox_inches="tight")
        plt.close(fig)
    return fig


def plot_sweep_heatmap(
    csv_path: str | Path,
    x_param: str = "short_window",
    y_param: str = "long_window",
    value_param: str = "score",
    save_path: str | None = None,
    filters: dict | None = None,
):
    """
    从 sweep CSV 生成参数-表现热力图。
    """
    try:
        import pandas as pd  # type: ignore
        import seaborn as sns  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("需要 pandas 和 seaborn 才能绘制热力图") from exc

    df = pd.read_csv(csv_path)
    if filters:
        if "min_trades" in filters:
            df = df[df["total_trades"] >= filters["min_trades"]]
        if "max_drawdown" in filters:
            df = df[df["max_drawdown"] <= filters["max_drawdown"]]
        if "min_sharpe" in filters:
            df = df[df["sharpe"] >= filters["min_sharpe"]]
    if x_param not in df.columns or y_param not in df.columns or value_param not in df.columns:
        raise ValueError(f"缺少必要列: {x_param}, {y_param}, {value_param}")

    pivot = df.pivot_table(index=y_param, columns=x_param, values=value_param, aggfunc="mean")
    plt = _require_matplotlib()
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(pivot, annot=True, fmt=".2f", cmap="coolwarm", ax=ax)
    ax.set_title(f"{value_param} heatmap")
    ax.set_xlabel(x_param)
    ax.set_ylabel(y_param)

    if save_path:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(path), bbox_inches="tight")
        plt.close(fig)
    return fig
