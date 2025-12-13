"""RSI 因子。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


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

        delta = df[self.price_col].diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)

        avg_gain = gain.rolling(self.period, min_periods=self.period).mean()
        avg_loss = loss.rolling(self.period, min_periods=self.period).mean()

        rs = avg_gain / avg_loss
        df[out] = 100.0 - (100.0 / (1.0 + rs))
        return df

