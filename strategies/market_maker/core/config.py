from __future__ import annotations

import os
from dataclasses import dataclass


def _getenv_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _getenv_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return bool(default)
    return raw.strip() in {"1", "true", "TRUE", "yes", "YES", "on", "ON"}


@dataclass(frozen=True)
class EngineConfig:
    """
    Minimal, stable defaults. Keep all env parsing in one place.

    Back-compat env vars:
      - MM_REFRESH_THRESHOLD
      - MM_OB_STALE_S
      - MM_ORACLE_STALE_S
      - MM_REF_PRICE_SOURCE (oracle | oracle_then_mexc | mexc)
      - MM_ALLOW_MEXC_REF_TRADING (1/0)
      - MM_MIN_MARKET_SPREAD_PCT (used only when volume_mode_enabled=True)
      - MM_MODE=volume enables volume_mode_enabled
    """

    # Data freshness
    ob_stale_s: float = 3.0
    oracle_stale_s: float = 3.0

    # Execution stability
    refresh_threshold: float = 0.0002  # 0.02%
    min_refresh_interval_s: float = 0.8  # throttle cancel/replace

    # Reference price policy
    ref_price_source: str = "oracle"  # oracle | oracle_then_mexc | mexc
    allow_live_without_oracle: bool = False

    # Optional "volume" mode (off by default for stability)
    volume_mode_enabled: bool = False
    min_market_spread_pct: float = 0.01
    step_in_ticks: int = 0  # 0 disables step-in

    # Logging
    warn_every_s: float = 10.0

    @classmethod
    def from_env(cls) -> "EngineConfig":
        mode = (os.getenv("MM_MODE") or "").lower()
        ref_source = (os.getenv("MM_REF_PRICE_SOURCE") or "oracle").lower()
        if ref_source not in {"oracle", "oracle_then_mexc", "mexc"}:
            ref_source = "oracle"

        step_in_ticks = _getenv_int("MM_STEP_IN_TICKS", 0)
        volume_mode_enabled = mode == "volume" or _getenv_bool("MM_VOLUME_MODE", False)
        if not volume_mode_enabled:
            step_in_ticks = 0

        return cls(
            ob_stale_s=_getenv_float("MM_OB_STALE_S", 3.0),
            oracle_stale_s=_getenv_float("MM_ORACLE_STALE_S", 3.0),
            refresh_threshold=_getenv_float("MM_REFRESH_THRESHOLD", 0.0002),
            min_refresh_interval_s=_getenv_float("MM_MIN_REFRESH_INTERVAL_S", 0.8),
            ref_price_source=ref_source,
            allow_live_without_oracle=_getenv_bool("MM_ALLOW_MEXC_REF_TRADING", False),
            volume_mode_enabled=volume_mode_enabled,
            min_market_spread_pct=_getenv_float("MM_MIN_MARKET_SPREAD_PCT", 0.01),
            step_in_ticks=step_in_ticks,
            warn_every_s=_getenv_float("MM_WARN_EVERY_S", 10.0),
        )

