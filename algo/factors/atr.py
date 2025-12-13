"""ATR 因子。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ATRFactor:
    """平均真实波幅（ATR，SMA 版本）。"""

    period: int = 14
    high_col: str = "high"
    low_col: str = "low"
    close_col: str = "close"
    out_col: str | None = None
    name: str = "atr"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.period <= 0:
            raise ValueError("ATR period must be > 0")
        object.__setattr__(
            self,
            "params",
            {
                "period": self.period,
                "high_col": self.high_col,
                "low_col": self.low_col,
                "close_col": self.close_col,
                "out_col": self.out_col,
            },
        )

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in (self.high_col, self.low_col, self.close_col):
            if col not in df.columns:
                raise ValueError(f"ATRFactor requires column: {col}")
        out = self.out_col or f"atr_{self.period}"

        prev_close = df[self.close_col].shift(1)
        tr1 = df[self.high_col] - df[self.low_col]
        tr2 = (df[self.high_col] - prev_close).abs()
        tr3 = (df[self.low_col] - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        df[out] = tr.rolling(self.period, min_periods=self.period).mean()
        return df

