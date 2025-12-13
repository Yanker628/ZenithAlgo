"""配置 Schema 校验（M4：Schema Enforcement）。

目标：
- 在启动阶段尽早失败，避免 typo/类型错误在实盘或长回测中“隐蔽爆炸”。
- 对核心配置块（顶层/exchange/risk/backtest）做严格校验；
  对策略参数等“开放字段”保持兼容（由策略模块自行解释）。
"""

from __future__ import annotations

import difflib
from datetime import date, datetime
from typing import Any, Iterable


def _suggest_key(key: str, allowed: Iterable[str]) -> str | None:
    matches = difflib.get_close_matches(key, list(allowed), n=1, cutoff=0.75)
    return matches[0] if matches else None


def _ensure_allowed_keys(block: dict[str, Any], *, allowed: set[str], ctx: str) -> None:
    unknown = [k for k in block.keys() if k not in allowed]
    if not unknown:
        return
    parts = []
    for k in sorted(unknown):
        suggestion = _suggest_key(k, allowed)
        if suggestion:
            parts.append(f"{k} (did you mean '{suggestion}'?)")
        else:
            parts.append(k)
    raise ValueError(f"{ctx} contains unknown keys: {', '.join(parts)}")


def _require(block: dict[str, Any], key: str, *, ctx: str) -> Any:
    if key not in block:
        raise ValueError(f"Missing required config key: {ctx}.{key}")
    return block[key]


def _expect_dict(val: Any, *, ctx: str) -> dict[str, Any]:
    if not isinstance(val, dict):
        raise ValueError(f"{ctx} must be a dict")
    return val


def _expect_str(val: Any, *, ctx: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{ctx} must be a non-empty string")
    return val


def _expect_bool(val: Any, *, ctx: str) -> bool:
    if isinstance(val, bool):
        return val
    raise ValueError(f"{ctx} must be a bool")


def _expect_number(val: Any, *, ctx: str) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    raise ValueError(f"{ctx} must be a number")


def _expect_datetime_like(val: Any, *, ctx: str) -> Any:
    # YAML 可能把未加引号的 ISO 时间解析为 datetime/date；这里允许并在 engine 内统一处理。
    if isinstance(val, (str, datetime, date)):
        return val
    raise ValueError(f"{ctx} must be an ISO datetime string or datetime/date")


def validate_raw_config(cfg: dict[str, Any]) -> None:
    """校验 raw config dict（来自 YAML + env 展开后）。"""
    if not isinstance(cfg, dict):
        raise ValueError("Config root must be a dict")

    top_allowed = {
        "symbol",
        "timeframe",
        "mode",
        "equity_base",
        "exchange",
        "risk",
        "strategy",
        "backtest",
        "sizing",
    }
    _ensure_allowed_keys(cfg, allowed=top_allowed, ctx="config")

    _expect_str(_require(cfg, "symbol", ctx="config"), ctx="config.symbol")
    _expect_str(_require(cfg, "timeframe", ctx="config"), ctx="config.timeframe")

    exchange = _expect_dict(_require(cfg, "exchange", ctx="config"), ctx="config.exchange")
    _validate_exchange(exchange)

    risk = _expect_dict(_require(cfg, "risk", ctx="config"), ctx="config.risk")
    _validate_risk(risk)

    strategy = cfg.get("strategy")
    if strategy is not None:
        if not isinstance(strategy, dict):
            raise ValueError("config.strategy must be a dict")
        # 只强约束 type；其余参数留给策略层解释
        if "type" in strategy:
            _expect_str(strategy["type"], ctx="config.strategy.type")

    backtest = cfg.get("backtest")
    if backtest is not None:
        backtest = _expect_dict(backtest, ctx="config.backtest")
        _validate_backtest(backtest)

    sizing = cfg.get("sizing")
    if sizing is not None and not isinstance(sizing, dict):
        raise ValueError("config.sizing must be a dict")


def _validate_exchange(exchange: dict[str, Any]) -> None:
    allowed = {
        "name",
        "base_url",
        "api_key",
        "api_secret",
        "ws_url",
        "allow_live",
        "symbols_allowlist",
        "min_notional",
        "min_qty",
        "qty_step",
        "price_step",
        "max_price_deviation_pct",
    }
    _ensure_allowed_keys(exchange, allowed=allowed, ctx="config.exchange")

    _expect_str(_require(exchange, "name", ctx="config.exchange"), ctx="config.exchange.name")
    _expect_str(_require(exchange, "base_url", ctx="config.exchange"), ctx="config.exchange.base_url")
    if "allow_live" in exchange and exchange["allow_live"] is not None:
        _expect_bool(exchange["allow_live"], ctx="config.exchange.allow_live")


def _validate_risk(risk: dict[str, Any]) -> None:
    allowed = {"max_position_pct", "max_daily_loss_pct"}
    _ensure_allowed_keys(risk, allowed=allowed, ctx="config.risk")

    _expect_number(_require(risk, "max_position_pct", ctx="config.risk"), ctx="config.risk.max_position_pct")
    _expect_number(_require(risk, "max_daily_loss_pct", ctx="config.risk"), ctx="config.risk.max_daily_loss_pct")


def _validate_backtest(bt: dict[str, Any]) -> None:
    allowed = {
        "data_dir",
        "symbol",
        "symbols",
        "interval",
        "start",
        "end",
        "initial_equity",
        "auto_download",
        "force_download",
        "quiet_risk_logs",
        "flatten_on_end",
        "record_equity_each_bar",
        "skip_plots",
        "fees",
        "sizing",
        "risk",
        "strategy",
        "factors",
        "sweep",
    }
    _ensure_allowed_keys(bt, allowed=allowed, ctx="config.backtest")

    _expect_str(_require(bt, "data_dir", ctx="config.backtest"), ctx="config.backtest.data_dir")
    _expect_str(_require(bt, "interval", ctx="config.backtest"), ctx="config.backtest.interval")
    _expect_datetime_like(_require(bt, "start", ctx="config.backtest"), ctx="config.backtest.start")
    _expect_datetime_like(_require(bt, "end", ctx="config.backtest"), ctx="config.backtest.end")

    if "symbol" in bt and bt["symbol"] is not None:
        _expect_str(bt["symbol"], ctx="config.backtest.symbol")

    if "auto_download" in bt and bt["auto_download"] is not None:
        _expect_bool(bt["auto_download"], ctx="config.backtest.auto_download")
    if "force_download" in bt and bt["force_download"] is not None:
        _expect_bool(bt["force_download"], ctx="config.backtest.force_download")
    if "quiet_risk_logs" in bt and bt["quiet_risk_logs"] is not None:
        _expect_bool(bt["quiet_risk_logs"], ctx="config.backtest.quiet_risk_logs")
    if "flatten_on_end" in bt and bt["flatten_on_end"] is not None:
        _expect_bool(bt["flatten_on_end"], ctx="config.backtest.flatten_on_end")
    if "record_equity_each_bar" in bt and bt["record_equity_each_bar"] is not None:
        _expect_bool(bt["record_equity_each_bar"], ctx="config.backtest.record_equity_each_bar")
    if "skip_plots" in bt and bt["skip_plots"] is not None:
        _expect_bool(bt["skip_plots"], ctx="config.backtest.skip_plots")

    if "fees" in bt and bt["fees"] is not None:
        fees = _expect_dict(bt["fees"], ctx="config.backtest.fees")
        _validate_fees(fees)

    if "sweep" in bt and bt["sweep"] is not None:
        sweep = _expect_dict(bt["sweep"], ctx="config.backtest.sweep")
        _validate_sweep(sweep)

    if "risk" in bt and bt["risk"] is not None:
        if not isinstance(bt["risk"], dict):
            raise ValueError("config.backtest.risk must be a dict")

    if "sizing" in bt and bt["sizing"] is not None:
        if not isinstance(bt["sizing"], dict):
            raise ValueError("config.backtest.sizing must be a dict")

    if "strategy" in bt and bt["strategy"] is not None:
        if not isinstance(bt["strategy"], dict):
            raise ValueError("config.backtest.strategy must be a dict")
        if "type" in bt["strategy"]:
            _expect_str(bt["strategy"]["type"], ctx="config.backtest.strategy.type")

    if "factors" in bt and bt["factors"] is not None:
        if not isinstance(bt["factors"], list):
            raise ValueError("config.backtest.factors must be a list")


def _validate_fees(fees: dict[str, Any]) -> None:
    allowed = {"maker", "taker", "slippage_bp"}
    _ensure_allowed_keys(fees, allowed=allowed, ctx="config.backtest.fees")
    if "maker" in fees and fees["maker"] is not None:
        _expect_number(fees["maker"], ctx="config.backtest.fees.maker")
    if "taker" in fees and fees["taker"] is not None:
        _expect_number(fees["taker"], ctx="config.backtest.fees.taker")
    if "slippage_bp" in fees and fees["slippage_bp"] is not None:
        _expect_number(fees["slippage_bp"], ctx="config.backtest.fees.slippage_bp")


def _validate_sweep(sweep: dict[str, Any]) -> None:
    allowed = {
        "enabled",
        "mode",
        "params",
        "objective",
        "filters",
        "min_trades",
        "max_drawdown",
        "min_sharpe",
        "low_trades_penalty",
        "n_random",
        "heatmap",
    }
    _ensure_allowed_keys(sweep, allowed=allowed, ctx="config.backtest.sweep")
    if "enabled" in sweep and sweep["enabled"] is not None:
        _expect_bool(sweep["enabled"], ctx="config.backtest.sweep.enabled")
    if "mode" in sweep and sweep["mode"] is not None:
        _expect_str(sweep["mode"], ctx="config.backtest.sweep.mode")
    if "params" in sweep and sweep["params"] is not None:
        if not isinstance(sweep["params"], dict):
            raise ValueError("config.backtest.sweep.params must be a dict")
    if "objective" in sweep and sweep["objective"] is not None:
        if not isinstance(sweep["objective"], dict):
            raise ValueError("config.backtest.sweep.objective must be a dict")
    if "filters" in sweep and sweep["filters"] is not None:
        if not isinstance(sweep["filters"], dict):
            raise ValueError("config.backtest.sweep.filters must be a dict")

