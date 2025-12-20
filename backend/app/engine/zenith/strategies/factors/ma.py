"""MA 因子。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from zenith.common.utils.logging import setup_logger

_LOGGER = setup_logger("factor-ma")
_RUST_LOGGED = False
_FALLBACK_LOGGED = False


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
        try:
            import zenithalgo_rust
        except Exception:
            zenithalgo_rust = None
        if zenithalgo_rust is not None:
            global _RUST_LOGGED
            if not _RUST_LOGGED:
                _LOGGER.info("MAFactor 使用 Rust 算子加速。")
                _RUST_LOGGED = True
            # Rust 版本：输入数组，输出与原长度一致的均线序列
            values = df[self.price_col].astype(float).to_list()
            df[out] = zenithalgo_rust.ma(values, int(self.window))  # type: ignore
            return df
        global _FALLBACK_LOGGED
        if not _FALLBACK_LOGGED:
            _LOGGER.warning("MAFactor Rust 算子不可用，回退到 pandas。")
            _FALLBACK_LOGGED = True
        df[out] = df[self.price_col].rolling(self.window, min_periods=self.window).mean()
        return df
