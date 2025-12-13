"""配置加载与数据结构。

支持 YAML 配置、环境变量占位符 `${VAR}` 展开，以及 .env/.env.local 自动加载。
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict, cast

import yaml

from shared.config.validation import validate_raw_config


class ExchangeConfigDict(TypedDict):
    name: str
    base_url: str
    api_key: str | None
    api_secret: str | None
    ws_url: str | None
    allow_live: bool | None
    symbols_allowlist: list[str] | None
    min_notional: float | None
    min_qty: float | None
    qty_step: float | None
    price_step: float | None
    max_price_deviation_pct: float | None


class RiskConfigDict(TypedDict):
    max_position_pct: float
    max_daily_loss_pct: float


class StrategyConfigDict(TypedDict, total=False):
    type: str
    # 其余字段按策略自定义；这里不做强约束
    # 例如 simple_ma: short_window/long_window/min_ma_diff/cooldown_secs


class RawConfigRequired(TypedDict):
    exchange: ExchangeConfigDict
    risk: RiskConfigDict
    symbol: str
    timeframe: str


class RawConfig(RawConfigRequired, total=False):
    mode: str
    strategy: StrategyConfigDict
    backtest: dict[str, Any]
    sizing: dict[str, Any]
    ledger: dict[str, Any]


@dataclass
class ExchangeConfig:
    """交易所相关配置。"""
    name: str
    base_url: str
    api_key: str | None = None
    api_secret: str | None = None
    ws_url: str | None = None
    allow_live: bool = False
    symbols_allowlist: list[str] | None = None
    min_notional: float | None = None
    min_qty: float | None = None
    qty_step: float | None = None
    price_step: float | None = None
    max_price_deviation_pct: float | None = None

@dataclass
class RiskConfig:
    """风控参数配置。"""
    max_position_pct: float
    max_daily_loss_pct: float


@dataclass
class StrategyConfig:
    """策略配置（type + params）。"""
    type: str = "simple_ma"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    """应用总配置。"""
    exchange: ExchangeConfig
    risk: RiskConfig
    symbol: str
    timeframe: str
    equity_base: float = 1.0
    mode: str = "paper"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    backtest: dict[str, Any] | None = None
    sizing: dict[str, Any] | None = None
    ledger: dict[str, Any] | None = None

def _load_env_file(env_path: Path):
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_envs(cfg_path: Path):
    """
    加载配置文件目录与仓库根目录下的 .env/.env.local（不覆盖已有环境变量）。
    """
    candidates = [
        cfg_path.parent / ".env",
        cfg_path.parent / ".env.local",
        cfg_path.parent.parent / ".env",
        cfg_path.parent.parent / ".env.local",
    ]
    for env_file in candidates:
        _load_env_file(env_file)


def load_config(path: str, load_env: bool = True, expand_env: bool = True) -> AppConfig:
    """从 YAML 读取并解析配置。

    Parameters
    ----------
    path:
        配置文件路径。
    load_env:
        是否自动加载 .env/.env.local。
    expand_env:
        是否展开 `${VAR}` 占位符。

    Returns
    -------
    AppConfig
        解析后的配置对象。

    Raises
    ------
    FileNotFoundError
        配置文件不存在。
    ValueError
        缺少必填字段或缺失环境变量。
    """
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    if load_env:
        _load_envs(cfg_path)

    with cfg_path.open("r", encoding="utf-8") as f:
        raw_cfg: dict[str, Any] = yaml.safe_load(f) or {}

    def _expand_env(value: Any) -> Any:
        if isinstance(value, str):
            if not expand_env:
                return value
            # 保留未设置的变量占位符，避免静默替换为空
            def replacer(match):
                var_name = match.group(1)
                if var_name not in os.environ:
                    raise ValueError(f"Missing environment variable: {var_name}")
                return os.environ[var_name]

            return re.sub(r"\$\{([^}]+)\}", replacer, value)
        if isinstance(value, dict):
            return {k: _expand_env(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_expand_env(v) for v in value]
        return value

    cfg = cast(RawConfig, _expand_env(raw_cfg))
    validate_raw_config(cast(dict[str, Any], cfg))

    try:
        exchange_cfg = ExchangeConfig(**cast(dict[str, Any], cfg["exchange"]))
        risk_cfg = RiskConfig(**cast(dict[str, Any], cfg["risk"]))
        symbol: str = cfg["symbol"]
        timeframe: str = cfg["timeframe"]
        equity_base: float = float(cfg.get("equity_base", 1.0))
        mode_raw: str = cfg.get("mode", "paper")
        mode: str = mode_raw.replace("_", "-").lower()
        strat_cfg_raw = cfg.get("strategy", {}) or {}
        strat_type = cast(dict[str, Any], strat_cfg_raw).get("type", "simple_ma")
        params = dict(cast(dict[str, Any], strat_cfg_raw))
        params.pop("type", None)
        strategy_cfg = StrategyConfig(type=strat_type, params=params)
        backtest_cfg = cfg.get("backtest")
        sizing_cfg = cfg.get("sizing")
        ledger_cfg = cfg.get("ledger")
        # 确保 backtest 至少有 symbol 键，便于回测/测试访问
        if isinstance(backtest_cfg, dict) and "symbol" not in backtest_cfg:
            backtest_cfg["symbol"] = symbol
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"Missing required config key: {missing}") from exc

    return AppConfig(
        exchange=exchange_cfg,
        risk=risk_cfg,
        symbol=symbol,
        timeframe=timeframe,
        equity_base=equity_base,
        mode=mode,
        strategy=strategy_cfg,
        backtest=backtest_cfg,
        sizing=sizing_cfg if isinstance(sizing_cfg, dict) else None,
        ledger=ledger_cfg if isinstance(ledger_cfg, dict) else None,
    )
