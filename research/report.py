"""实验报告生成（Markdown）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _md_kv(d: dict[str, Any]) -> str:
    parts = []
    for k, v in d.items():
        parts.append(f"- **{k}**: {v}")
    return "\n".join(parts)


def write_report_md(path: Path, *, task: str, meta: dict[str, Any], summary: Any, artifacts: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append(f"# ZenithAlgo Experiment Report ({task})")
    lines.append("")
    lines.append("## Meta")
    lines.append(_md_kv(meta))
    lines.append("")

    if task == "backtest":
        metrics = (summary or {}).get("metrics", {}) if isinstance(summary, dict) else {}
        lines.append("## Metrics")
        lines.append(_md_kv(metrics))
        lines.append("")
        lines.append("## Artifacts")
        for k in ["trades_csv", "equity_csv", "equity_png", "drawdown_png", "return_hist_png"]:
            v = artifacts.get(k)
            if v:
                lines.append(f"- {k}: `{v}`")
        lines.append("")
    else:
        lines.append("## Artifacts")
        lines.append(f"- dir: `{artifacts.get('dir')}`")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")

