"""研究/回测的结构化 Schema（Pydantic，M4）。

原则：
- “边界强类型，内部渐进”：主要用于配置与产物/结果的边界协议；
- schema_version 先行：未来结构升级可做迁移与兼容策略，而不是默默把历史结果搞废。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EXPERIMENT_SCHEMA_VERSION = "1.0"


class GitInfo(BaseModel):
    sha: str = "UNKNOWN"
    dirty: bool = False
    model_config = ConfigDict(extra="forbid")


class ExperimentMetaJson(BaseModel):
    """results/*/meta.json（复现骨钉）。"""

    schema_version: str = EXPERIMENT_SCHEMA_VERSION
    task: str
    symbol: str
    interval: str
    start: Optional[str] = None
    end: Optional[str] = None
    created_at: str
    run_ts: str

    git_sha: str = "UNKNOWN"
    git_dirty: bool = False
    git: GitInfo = Field(default_factory=GitInfo)

    config_hash: str
    data_hash: str
    data_hashes: Optional[Dict[str, str]] = None

    model_config = ConfigDict(extra="forbid")


class CanonicalMetrics(BaseModel):
    """metrics 的固定 key 集合（与 `analysis/metrics/metrics_canon.py` 对齐）。"""

    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_trade_return: float = 0.0
    std_trade_return: float = 0.0
    exposure: float = 0.0
    turnover: float = 0.0

    model_config = ConfigDict(extra="forbid")


class PositionSnapshot(BaseModel):
    qty: float
    avg_price: float
    model_config = ConfigDict(extra="forbid")


class DataHealth(BaseModel):
    n_bars: int
    symbol: str
    interval: str
    start: str
    end: str
    n_features: int
    feature_nan_ratio: float = 0.0
    model_config = ConfigDict(extra="allow")


class BacktestSummary(BaseModel):
    """BacktestEngine.run().summary（强类型）。"""

    realized_pnl: float
    final_unrealized: float
    cash: float
    positions: Dict[str, PositionSnapshot] = Field(default_factory=dict)
    metrics: CanonicalMetrics
    data_health: DataHealth
    signal_trace: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class SummaryJson(BaseModel):
    """results/*/summary.json（验收/回归入口）。"""

    schema_version: str = EXPERIMENT_SCHEMA_VERSION
    task: str
    metrics: CanonicalMetrics
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    policy: Dict[str, Any] = Field(default_factory=dict)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    metrics_spec: Dict[str, Any] = Field(default_factory=dict)
    details: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


ExperimentTask = Literal["backtest", "sweep", "walkforward"]


class ResultsJson(BaseModel):
    """results/*/results.json（整包结果）。"""

    schema_version: str = EXPERIMENT_SCHEMA_VERSION
    task: ExperimentTask
    meta: Dict[str, Any]
    meta_json: Dict[str, Any]
    summary_json: Optional[Dict[str, Any]] = None

    # backtest
    summary: Optional[Dict[str, Any]] = None
    artifacts: Optional[Dict[str, Any]] = None

    # sweep/walkforward 的结构相对复杂，先允许 extra，避免阻塞主流程
    model_config = ConfigDict(extra="allow")
