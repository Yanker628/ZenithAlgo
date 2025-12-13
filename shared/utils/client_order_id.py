"""订单幂等 ID（client_order_id）生成。

要求：
- 同一交易意图在重放/重启后可重建（deterministic）。
- 长度可控，适配交易所 client id 字段限制（用 hash 缩短）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime


def make_client_order_id(
    *,
    strategy_id: str,
    symbol: str,
    side: str,
    intent_ts: datetime,
    signal_seq: int,
    reason: str | None = None,
) -> str:
    raw = "|".join(
        [
            str(strategy_id),
            str(symbol),
            str(side),
            intent_ts.isoformat(),
            str(int(signal_seq)),
            str(reason or ""),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"za_{digest}"

