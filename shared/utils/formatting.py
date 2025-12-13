"""格式化工具（日志/报表友好）。"""

from __future__ import annotations


def fmt_price(price: float | None, *, min_decimals: int = 2, max_decimals: int = 8) -> str:
    """格式化价格，避免小数位过短导致“看不出变化”。

    约定：
    - 价格越小，小数位越多（默认最多 8 位）；
    - 去除尾部多余 0，避免日志过长；
    - 仅用于展示，不用于交易计算。
    """
    if price is None:
        return "NA"
    try:
        p = float(price)
    except Exception:
        return str(price)

    ap = abs(p)
    if ap <= 0:
        return "0"

    if ap >= 1000:
        decimals = 2
    elif ap >= 1:
        decimals = 4
    elif ap >= 0.1:
        decimals = 5
    elif ap >= 0.01:
        decimals = 6
    elif ap >= 0.001:
        decimals = 7
    else:
        decimals = 8

    decimals = max(min_decimals, min(max_decimals, int(decimals)))
    s = f"{p:.{decimals}f}"
    return s.rstrip("0").rstrip(".")

