"""配置架构定义（Pydantic Schema，M4：Schema Enforcement）。

目标：
- 让配置成为“强类型 + 可演进”的边界协议；
- 启动阶段尽早失败，避免 typo/类型错误在实盘或长回测中“隐蔽爆炸”；
- 尽量消灭业务代码里的 `cfg.get(...)` 与深层字典索引。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExchangeConfig(BaseModel):
    """交易所配置。"""
    name: str = "binance"
    base_url: str = "https://api.binance.com"
    ws_url: Optional[str] = "wss://stream.binance.com:9443/ws"
    
    # 使用 Field(default=None) 允许这些字段在 YAML 中缺失
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    allow_live: bool = False
    symbols_allowlist: List[str] = Field(default_factory=list)
    
    # 交易规则参数
    min_notional: Optional[float] = 5.0
    min_qty: Optional[float] = 0.00001
    qty_step: Optional[float] = 0.00001
    price_step: Optional[float] = 0.01
    max_price_deviation_pct: Optional[float] = 0.05

    model_config = ConfigDict(extra="forbid")


class RiskConfig(BaseModel):
    """风控配置。"""
    max_position_pct: float = 0.3
    max_daily_loss_pct: float = 0.05
    model_config = ConfigDict(extra="forbid")


class StrategyConfig(BaseModel):
    """策略配置（type + params）。

    说明：
    - 策略参数不允许“散落在顶层”：必须进入 `params`；
    - config_loader 会把 `strategy:` 下的扁平字段自动挪到 `params`，从而实现：
      - 用户写起来方便
      - schema 又能做到严格（forbid extra keys）
    """
    type: str = "simple_ma"
    params: Dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _pack_flat_params(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "params" in data and isinstance(data.get("params"), dict) and set(data.keys()) <= {"type", "params"}:
            return data
        strat_type = data.get("type", "simple_ma")
        params = {k: v for k, v in data.items() if k not in {"type", "params"}}
        existing = data.get("params")
        if isinstance(existing, dict):
            params = {**params, **existing}
        return {"type": strat_type, "params": params}


class FeesConfig(BaseModel):
    """回测手续费/滑点配置。"""
    maker: float = 0.0
    taker: float = 0.0004
    slippage_bp: float = 0.0
    model_config = ConfigDict(extra="forbid")


class SweepObjectiveConfig(BaseModel):
    """扫参目标权重。"""
    total_return_weight: float = 0.0
    sharpe_weight: float = 0.0
    max_drawdown_weight: float = 0.0
    model_config = ConfigDict(extra="forbid")


class SweepConfig(BaseModel):
    """扫参配置（grid/random）。"""
    enabled: bool = False
    mode: Literal["grid", "random"] = "grid"
    # 是否在 sweep 结束后额外跑一次“最佳参数单次回测”并导出 trades/equity/report 等产物。
    # 默认关闭：只输出 best_params 与 best_metrics，避免重复跑一遍回测。
    run_best_backtest: bool = False
    params: Dict[str, List[Any]] = Field(default_factory=dict)
    objective: SweepObjectiveConfig = Field(default_factory=SweepObjectiveConfig)
    filters: Optional[Dict[str, Any]] = None
    min_trades: Optional[int] = None
    max_drawdown: Optional[float] = None
    min_sharpe: Optional[float] = None
    low_trades_penalty: float = 0.0
    n_random: int = 20
    heatmap: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra="forbid")


class BacktestConfig(BaseModel):
    """回测配置。"""
    data_dir: str = "dataset/history"
    symbol: str
    interval: str
    start: str
    end: str

    initial_equity: float = 0.0
    auto_download: bool = False
    force_download: bool = False
    quiet_risk_logs: bool = True
    flatten_on_end: bool = False
    record_equity_each_bar: bool = False
    skip_plots: bool = False

    fees: FeesConfig = Field(default_factory=FeesConfig)
    sizing: Optional[Dict[str, Any]] = None
    strategy: Optional[StrategyConfig] = None
    sweep: Optional[SweepConfig] = None
    risk: Optional[Dict[str, Any]] = None
    factors: Optional[List[Dict[str, Any]]] = None
    symbols: Optional[List[str]] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _normalize_strategy(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        strat = data.get("strategy")
        if isinstance(strat, dict):
            data = dict(data)
            data["strategy"] = StrategyConfig._pack_flat_params(strat)  # type: ignore[attr-defined]
        return data


class LedgerConfig(BaseModel):
    """本地事件账本（SQLite ledger）配置。"""
    enabled: bool = True
    path: str = "dataset/state/ledger.sqlite3"
    model_config = ConfigDict(extra="forbid")


class RecoveryConfig(BaseModel):
    """启动恢复/对账配置。"""
    enabled: bool = True
    mode: Literal["observe_only", "trade"] = "observe_only"
    model_config = ConfigDict(extra="forbid")


class MainConfig(BaseModel):
    """应用总配置（对应原 AppConfig）。"""
    symbol: str
    timeframe: str = "1h"
    mode: Literal["backtest", "dry-run", "paper", "live", "live-testnet", "live-mainnet"] = "paper"
    equity_base: float = 1.0

    # 子模块配置
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)

    backtest: Optional[BacktestConfig] = None
    sizing: Optional[Dict[str, Any]] = None
    ledger: LedgerConfig = Field(default_factory=LedgerConfig)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# 兼容旧命名：历史代码/测试仍可能使用 AppConfig
AppConfig = MainConfig
