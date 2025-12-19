"""因子（Factors/Features）抽象协议。"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

import pandas as pd


class Factor(Protocol):
    """因子协议：`compute(df) -> df`。"""

    name: str
    params: Mapping[str, Any]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """对输入 df 添加/更新因子列并返回 df。"""
        ...
