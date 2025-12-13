"""因子（Factors/Features）抽象协议。

V2.3 约定：因子层是“纯计算”，输入 CandleFrame（pandas DataFrame），输出添加列后的 DataFrame。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

import pandas as pd


class Factor(Protocol):
    """因子协议：`compute(df) -> df`。"""

    name: str
    params: Mapping[str, Any]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """对输入 df 添加/更新因子列并返回 df。"""

