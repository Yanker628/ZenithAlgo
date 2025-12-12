"""实验报告生成（Markdown）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _md_kv(d: dict[str, Any]) -> str:
    parts = []
    for k, v in d.items():
        parts.append(f"- **{k}**: {v}")
    return "\n".join(parts)


def _pick(d: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {k: d.get(k) for k in keys if k in d}


def _fmt_pct(x: Any) -> str:
    try:
        v = float(x)
    except Exception:
        return str(x)
    return f"{v * 100:.2f}%"


def _stability_conclusion(metrics: dict[str, Any]) -> str:
    tr = float(metrics.get("total_return", metrics.get("total_return_avg", 0.0)) or 0.0)
    sharpe = float(metrics.get("sharpe", metrics.get("sharpe_avg", 0.0)) or 0.0)
    dd = float(metrics.get("max_drawdown", metrics.get("max_drawdown_max", 0.0)) or 0.0)
    trades = int(metrics.get("total_trades", 0) or 0)

    if trades == 0:
        return "无成交（需要检查策略信号/数据/特征/过滤条件）。"
    if sharpe >= 1.0 and dd <= 0.2 and tr > 0:
        return "整体较稳健：收益为正、夏普较高且回撤受控。"
    if tr <= 0 and sharpe < 0:
        return "整体偏弱：收益为负且风险调整收益不足，建议调整过滤/止损/参数范围。"
    if dd > 0.3:
        return "风险偏高：最大回撤偏大，建议收紧仓位/止损或增加风控过滤。"
    return "中性：存在一定收益或稳定性，但仍需进一步做更严格的稳健性验证。"


def _data_health_block(meta: dict[str, Any], summary: Any) -> dict[str, Any]:
    if isinstance(summary, dict) and isinstance(summary.get("data_health"), dict):
        return dict(summary["data_health"])
    # sweep：用第一个 symbol 的 best_backtest.data_health 作为概览
    if isinstance(summary, dict) and isinstance(summary.get("symbols"), dict):
        symbols = summary.get("symbols") or {}
        if symbols:
            first = next(iter(symbols.values()))
            if isinstance(first, dict):
                bb = first.get("best_backtest")
                if isinstance(bb, dict) and isinstance(bb.get("data_health"), dict):
                    return dict(bb["data_health"])
    # 回退：只给可追溯的时间/品种信息
    return _pick(meta, ["symbol", "interval", "start", "end"])


def _trade_health_block(metrics: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        metrics,
        [
            "total_trades",
            "win_rate",
            "profit_factor",
            "expectancy",
            "avg_trade_return",
            "std_trade_return",
            "exposure",
            "turnover",
        ],
    )


def _core_perf_block(metrics: dict[str, Any]) -> dict[str, Any]:
    return _pick(metrics, ["total_return", "total_return_avg", "sharpe", "sharpe_avg", "max_drawdown", "max_drawdown_max"])


def write_report_md(path: Path, *, task: str, meta: dict[str, Any], summary: Any, artifacts: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append(f"# ZenithAlgo Experiment Report ({task})")
    lines.append("")
    lines.append("## Meta")
    lines.append(_md_kv(meta))
    lines.append("")

    # 首页固定结构
    metrics: dict[str, Any] = {}
    if task == "backtest" and isinstance(summary, dict):
        metrics = dict(summary.get("metrics", {}) or {})
    elif task == "walkforward" and isinstance(summary, dict):
        overall = summary.get("overall") if isinstance(summary.get("overall"), dict) else {}
        metrics = dict(overall) if isinstance(overall, dict) else {}
    elif task == "sweep" and isinstance(summary, dict):
        # sweep 首页用每个 symbol 的 best_backtest 指标（若多 symbol，展示第一个作为概览）
        symbols = summary.get("symbols") if isinstance(summary.get("symbols"), dict) else {}
        if symbols:
            first = next(iter(symbols.values()))
            bb = first.get("best_backtest") if isinstance(first, dict) else {}
            metrics = dict(bb.get("metrics", {}) or {}) if isinstance(bb, dict) else {}

    lines.append("## Data Health")
    lines.append(_md_kv(_data_health_block(meta, summary)))
    lines.append("")

    lines.append("## Trade Health")
    lines.append(_md_kv(_trade_health_block(metrics)))
    lines.append("")

    lines.append("## Core Performance")
    core = _core_perf_block(metrics)
    # 展示时把 total_return/total_return_avg 做百分比更直观
    if "total_return" in core:
        core["total_return"] = _fmt_pct(core["total_return"])
    if "total_return_avg" in core:
        core["total_return_avg"] = _fmt_pct(core["total_return_avg"])
    lines.append(_md_kv(core))
    lines.append("")

    lines.append("## Stability Conclusion")
    lines.append(_stability_conclusion(metrics))
    lines.append("")

    # task-specific details
    if task == "sweep" and isinstance(summary, dict):
        lines.append("## Sweep Summary")
        symbols = summary.get("symbols") if isinstance(summary.get("symbols"), dict) else {}
        if not symbols:
            lines.append("- (no symbols)")
        else:
            for sym, info in symbols.items():
                if not isinstance(info, dict):
                    continue
                lines.append(f"### {sym}")
                viz = info.get("viz") if isinstance(info.get("viz"), dict) else {}
                if viz:
                    lines.append("- viz: " + json.dumps(viz, ensure_ascii=False))
                best_params = info.get("best_params") if isinstance(info.get("best_params"), dict) else {}
                if best_params:
                    lines.append("- best_params: " + json.dumps(best_params, ensure_ascii=False))
                bb = info.get("best_backtest") if isinstance(info.get("best_backtest"), dict) else {}
                bbm = bb.get("metrics") if isinstance(bb.get("metrics"), dict) else {} # type: ignore
                if bbm:
                    lines.append("- best_metrics: " + json.dumps(_pick(bbm, ["total_return", "sharpe", "max_drawdown", "total_trades"]), ensure_ascii=False))
                plots = info.get("plots") if isinstance(info.get("plots"), list) else []
                if plots:
                    lines.append("- plots:")
                    for p in plots[:10]:
                        lines.append(f"  - `{p}`")
        lines.append("")

    if task == "walkforward" and isinstance(summary, dict):
        lines.append("## Walk-Forward Summary")
        overall = summary.get("overall") if isinstance(summary.get("overall"), dict) else {}
        if overall:
            lines.append(_md_kv(overall))
        lines.append("")

    lines.append("## Artifacts")
    if artifacts.get("dir"):
        lines.append(f"- dir: `{artifacts.get('dir')}`")
    for k in ["trades_csv", "equity_csv", "equity_png", "drawdown_png", "return_hist_png"]:
        v = artifacts.get(k)
        if v:
            lines.append(f"- {k}: `{v}`")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary_md(path: Path, *, task: str, meta: dict[str, Any], metrics: dict[str, Any], plots: list[str] | None = None) -> None:
    """
    轻量 summary：用于快速抓重点（验收点）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# ZenithAlgo Summary ({task})")
    lines.append("")
    lines.append("## Core")
    core = _core_perf_block(metrics)
    if "total_return" in core:
        core["total_return"] = _fmt_pct(core["total_return"])
    if "total_return_avg" in core:
        core["total_return_avg"] = _fmt_pct(core["total_return_avg"])
    lines.append(_md_kv(core))
    lines.append("")
    lines.append("## Conclusion")
    lines.append(_stability_conclusion(metrics))
    lines.append("")
    if plots:
        lines.append("## Plots")
        for p in plots[:10]:
            lines.append(f"- `{p}`")
        lines.append("")
    lines.append("## Meta")
    lines.append(_md_kv(_pick(meta, ["symbol", "interval", "start", "end", "run_ts"])))
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
