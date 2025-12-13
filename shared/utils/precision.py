"""精度与步进工具（用于 qty/price 的裁剪与展示稳定）。"""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR


def decimals_from_step(step: float) -> int:
    """根据 step（通常是 10 的负次幂）推导小数位数。"""
    try:
        d = Decimal(str(step))
    except Exception:
        return 0
    if d == 0:
        return 0
    exp = d.as_tuple().exponent
    return max(0, -int(exp))


def floor_to_step(value: float, step: float) -> float:
    """把 value 向下裁剪到 step 的整数倍（避免 float 精度噪声）。"""
    if step is None:
        return float(value)
    s = float(step)
    if s <= 0:
        return float(value)

    v = Decimal(str(value))
    sd = Decimal(str(step))
    if sd <= 0:
        return float(value)

    n = (v / sd).to_integral_value(rounding=ROUND_FLOOR)
    out = n * sd
    decs = decimals_from_step(s)
    if decs > 0:
        out = out.quantize(Decimal(1).scaleb(-decs))
    else:
        out = out.quantize(Decimal(1))
    return float(out)

