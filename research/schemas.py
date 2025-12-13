"""Schema definitions for ZenithAlgo.

This module provides Pydantic models (or dataclasses) for:
1. Experiment Results (meta, metrics, artifacts)
2. Backtest Summaries
3. Configuration Snapshots
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GitInfo:
    sha: Optional[str] = None
    dirty: Optional[bool] = None


@dataclass
class ExperimentMeta:
    task: str
    symbol: str
    interval: str
    start: Optional[str]
    end: Optional[str]
    run_id: str
    run_ts: str
    git: GitInfo
    config_hash: Optional[str] = None
    data_hash: Optional[str] = None
    data_hashes: Optional[Dict[str, str]] = None


@dataclass
class Artifacts:
    dir: str
    trades_csv: Optional[str] = None
    equity_csv: Optional[str] = None
    equity_png: Optional[str] = None
    drawdown_png: Optional[str] = None
    return_hist_png: Optional[str] = None


@dataclass
class BacktestSummary:
    realized_pnl: float
    final_unrealized: float
    cash: float
    positions: Dict[str, Any]
    metrics: Dict[str, Any]
    data_health: Dict[str, Any]


@dataclass
class ExperimentResult:
    task: str
    meta: Dict[str, Any]
    metrics: Optional[Dict[str, Any]] = None
    artifacts: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None