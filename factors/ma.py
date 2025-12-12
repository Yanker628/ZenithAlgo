"""MA 因子。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class MAFactor:
    """简单移动平均（SMA）。"""

    window: int
    price_col: str = "close"
    out_col: str | None = None
    name: str = "ma"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.window <= 0:
            raise ValueError("MA window must be > 0")
        object.__setattr__(
            self,
            "params",
            {
                "window": self.window,
                "price_col": self.price_col,
                "out_col": self.out_col,
            },
        )

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.price_col not in df.columns:
            raise ValueError(f"MAFactor requires column: {self.price_col}")
        out = self.out_col or f"ma_{self.window}"
        df[out] = df[self.price_col].rolling(self.window, min_periods=self.window).mean()
        return df

