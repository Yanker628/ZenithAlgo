from __future__ import annotations

import math
from typing import Any


def sanitize_for_json(obj: Any) -> Any:
    """
    把 NaN/Inf 转成字符串，避免写出非标准 JSON（Infinity/NaN）。
    """
    if isinstance(obj, float):
        if math.isnan(obj):
            return "nan"
        if math.isinf(obj):
            return "inf" if obj > 0 else "-inf"
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    return obj

