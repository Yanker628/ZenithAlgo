"""配置加载器（Pydantic 版，M4：Schema Enforcement）。

支持 YAML 配置、环境变量占位符 `${VAR}` 展开，以及 .env/.env.local 自动加载。
"""

from __future__ import annotations

import os
import re
import yaml
from pathlib import Path
from typing import Any, Union

from pydantic import ValidationError

from .schema import (
    AppConfig,
    BacktestConfig,
    ExchangeConfig,
    MainConfig,
    RiskConfig,
    SweepConfig,
    StrategyConfig,
)


def _load_env_file(env_path: Path):
    """解析并加载 .env 文件到 os.environ"""
    if not env_path.exists():
        return
    # 简单的手动解析，为了不强制依赖 python-dotenv
    try:
        content = env_path.read_text(encoding='utf-8')
    except Exception:
        return

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_envs(cfg_path: Path):
    """加载配置文件目录与仓库根目录下的 .env/.env.local。"""
    candidates = [
        cfg_path.parent / ".env",
        cfg_path.parent / ".env.local",
        cfg_path.parent.parent / ".env",
        cfg_path.parent.parent / ".env.local",
    ]
    for env_file in candidates:
        _load_env_file(env_file)


def _expand_env_vars(value: Any, expand: bool = True) -> Any:
    """递归展开配置中的环境变量占位符。"""
    if isinstance(value, str):
        if not expand:
            return value
        
        def replacer(match):
            var_name = match.group(1)
            if var_name not in os.environ:
                raise ValueError(f"Missing environment variable: {var_name}")
            return os.environ[var_name]

        return re.sub(r"\$\{([^}]+)\}", replacer, value)
    
    if isinstance(value, dict):
        return {k: _expand_env_vars(v, expand) for k, v in value.items()}
    
    if isinstance(value, list):
        return [_expand_env_vars(v, expand) for v in value]
    
    return value


def load_config(
    path: Union[str, Path] = "config/config.yml", 
    load_env: bool = True, 
    expand_env: bool = True
) -> MainConfig:
    """加载并验证配置。

    Returns:
        MainConfig: 强类型的配置对象。
    """
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    # 1. 加载环境变量
    if load_env:
        _load_envs(cfg_path)

    # 2. 读取 YAML
    with cfg_path.open("r", encoding="utf-8") as f:
        raw_cfg = yaml.safe_load(f) or {}

    # 3. 展开环境变量 (保持原来的 strict 检查)
    expanded_cfg = _expand_env_vars(raw_cfg, expand=expand_env)

    # 4. 特殊字段预处理：backtest 补齐 symbol
    if "backtest" in expanded_cfg and isinstance(expanded_cfg["backtest"], dict):
        bt = expanded_cfg["backtest"]
        if "symbol" not in bt and "symbol" in expanded_cfg:
            bt["symbol"] = expanded_cfg["symbol"]

    # 5. 策略参数提取：扁平化字段归入 params（以便 schema 严格 forbid）
    # 原逻辑：strat_cfg_raw 里的非 type 字段都挪到 params
    if "strategy" in expanded_cfg and isinstance(expanded_cfg["strategy"], dict):
        strat_dict = expanded_cfg["strategy"]
        strat_type = strat_dict.get("type", "simple_ma")
        # 复制所有参数到 params，Pydantic 的 StrategyConfig 会处理
        params = {k: v for k, v in strat_dict.items() if k != "type"}
        # 如果原来没有 params 字段，就用提取出来的；如果原来有，就合并
        existing_params = strat_dict.get("params", {})
        final_params = {**params, **existing_params}
        
        expanded_cfg["strategy"] = {
            "type": strat_type,
            "params": final_params
        }

    # 5.1 backtest.strategy 同样做扁平化（扫参/回测覆盖参数习惯直接写在 strategy 下）
    if "backtest" in expanded_cfg and isinstance(expanded_cfg["backtest"], dict):
        bt = expanded_cfg["backtest"]
        if "strategy" in bt and isinstance(bt["strategy"], dict):
            bt_strat = bt["strategy"]
            bt_type = bt_strat.get("type")
            params = {k: v for k, v in bt_strat.items() if k != "type" and k != "params"}
            existing_params = bt_strat.get("params", {})
            final_params = {**params, **(existing_params if isinstance(existing_params, dict) else {})}
            bt["strategy"] = {"type": bt_type} if bt_type else {}
            bt["strategy"]["type"] = bt_type or expanded_cfg.get("strategy", {}).get("type", "simple_ma")
            bt["strategy"]["params"] = final_params

    # 6. Mode 归一化 (保留原逻辑)
    if "mode" in expanded_cfg:
        expanded_cfg["mode"] = expanded_cfg["mode"].replace("_", "-").lower()

    # 7. Pydantic 转换与校验
    try:
        return MainConfig(**expanded_cfg)
    except ValidationError as exc:
        unknown = []
        for err in exc.errors():
            if err.get("type") == "extra_forbidden":
                loc = err.get("loc") or ()
                unknown.append(".".join(str(x) for x in loc))
        if unknown:
            raise ValueError(f"config contains unknown keys: {', '.join(sorted(set(unknown)))}") from exc
        raise ValueError(f"Configuration validation failed: {exc}") from exc


# 兼容旧导入：历史代码/测试可能从 config_loader 导入这些名字
__all__ = [
    "load_config",
    "AppConfig",
    "MainConfig",
    "ExchangeConfig",
    "RiskConfig",
    "StrategyConfig",
    "BacktestConfig",
    "SweepConfig",
]
