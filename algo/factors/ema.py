"""EMA 因子。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from shared.utils.logging import setup_logger

_LOGGER = setup_logger("factor-ema")
_RUST_LOGGED = False
_FALLBACK_LOGGED = False


@dataclass(frozen=True)
class EMAFactor:
    """指数移动平均（EMA）。"""

    period: int = 14
    price_col: str = "close"
    out_col: str | None = None
    name: str = "ema"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.period <= 0:
            raise ValueError("EMA period must be > 0")
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
            raise ValueError(f"EMAFactor requires column: {self.price_col}")
        out = self.out_col or f"ema_{self.period}"

        try:
            import zenithalgo_rust
        except Exception:
            zenithalgo_rust = None
        if zenithalgo_rust is not None:
            global _RUST_LOGGED
            if not _RUST_LOGGED:
                _LOGGER.info("EMAFactor 使用 Rust 算子加速。")
                _RUST_LOGGED = True
            values = df[self.price_col].astype(float).to_list()
            df[out] = zenithalgo_rust.ema(values, int(self.period))  # type: ignore
            return df
        global _FALLBACK_LOGGED
        if not _FALLBACK_LOGGED:
            _LOGGER.warning("EMAFactor Rust 算子不可用，回退到 pandas。")
            _FALLBACK_LOGGED = True

        df[out] = (
            df[self.price_col]
            .astype(float)
            .ewm(span=self.period, adjust=False, min_periods=self.period)
            .mean()
        )
        return df
