"""RSI 因子。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from shared.utils.logging import setup_logger

_LOGGER = setup_logger("factor-rsi")
_RUST_LOGGED = False
_FALLBACK_LOGGED = False


@dataclass(frozen=True)
class RSIFactor:
    """相对强弱指数（RSI，SMA 版本）。"""

    period: int = 14
    price_col: str = "close"
    out_col: str | None = None
    name: str = "rsi"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.period <= 0:
            raise ValueError("RSI period must be > 0")
        object.__setattr__(
            self,
            "params",
            {
                "period": self.period,
                "price_col": self.price_col,
                "out_col": self.out_col,
            },
        )

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.price_col not in df.columns:
            raise ValueError(f"RSIFactor requires column: {self.price_col}")
        out = self.out_col or f"rsi_{self.period}"

        try:
            import zenithalgo_rust
        except Exception:
            zenithalgo_rust = None
        if zenithalgo_rust is not None:
            global _RUST_LOGGED
            if not _RUST_LOGGED:
                _LOGGER.info("RSIFactor 使用 Rust 算子加速。")
                _RUST_LOGGED = True
            values = df[self.price_col].astype(float).to_list()
            df[out] = zenithalgo_rust.rsi(values, int(self.period))  # type: ignore
            return df
        global _FALLBACK_LOGGED
        if not _FALLBACK_LOGGED:
            _LOGGER.warning("RSIFactor Rust 算子不可用，回退到 pandas。")
            _FALLBACK_LOGGED = True

        delta = df[self.price_col].diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)

        avg_gain = gain.rolling(self.period, min_periods=self.period).mean()
        avg_loss = loss.rolling(self.period, min_periods=self.period).mean()

        rs = avg_gain / avg_loss
        df[out] = 100.0 - (100.0 / (1.0 + rs))
        return df
