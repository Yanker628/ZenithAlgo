"""SQLite 本地事件账本（M5-2）。

目标
----
- 将“进程级幂等”升级为“跨进程幂等”。
- 订单与成交（fill）事件可追溯，为对账与审计提供可靠数据源。

设计
----
- SQLite，append-only（fills 追加；orders upsert 状态）。
- 以 client_order_id 作为订单主键（天然幂等键）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dumps(obj: Any) -> str:
    if is_dataclass(obj):
        obj = asdict(obj) # type: ignore
    return json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False)


class SqliteEventLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._ensure_schema()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
              client_order_id TEXT PRIMARY KEY,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,
              qty REAL NOT NULL,
              price REAL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              raw_signal_json TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_order_id TEXT NOT NULL,
              symbol TEXT NOT NULL,
              qty REAL NOT NULL,
              price REAL NOT NULL,
              fee REAL,
              ts TEXT NOT NULL,
              raw_json TEXT NOT NULL,
              FOREIGN KEY (client_order_id) REFERENCES orders(client_order_id)
            );
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_fills_cid ON fills(client_order_id);")

    def has_order(self, client_order_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM orders WHERE client_order_id = ? LIMIT 1;",
            (client_order_id,),
        ).fetchone()
        return row is not None

    def insert_order_new(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: str,
        qty: float,
        price: float | None,
        raw_signal: Any,
        created_at: str | None = None,
    ) -> bool:
        created_at = created_at or _utc_now_iso()
        try:
            self._conn.execute(
                """
                INSERT INTO orders (
                  client_order_id, symbol, side, qty, price, status, created_at, raw_signal_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    client_order_id,
                    symbol,
                    side,
                    float(qty),
                    float(price) if price is not None else None,
                    "NEW",
                    created_at,
                    _json_dumps(raw_signal),
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def set_order_status(self, client_order_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE orders SET status = ? WHERE client_order_id = ?;",
            (str(status), client_order_id),
        )

    def append_fill(
        self,
        *,
        client_order_id: str,
        symbol: str,
        qty: float,
        price: float,
        fee: float | None,
        ts: str | None = None,
        raw: Any,
    ) -> None:
        ts = ts or _utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO fills (client_order_id, symbol, qty, price, fee, ts, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                client_order_id,
                symbol,
                float(qty),
                float(price),
                float(fee) if fee is not None else None,
                ts,
                _json_dumps(raw),
            ),
        )

    def load_all_client_order_ids(self) -> set[str]:
        rows = self._conn.execute("SELECT client_order_id FROM orders;").fetchall()
        return {str(r[0]) for r in rows}

    def iter_fills_with_order_side(self) -> Iterable[dict[str, Any]]:
        cur = self._conn.execute(
            """
            SELECT
              f.id, f.client_order_id, f.symbol, f.qty, f.price, f.fee, f.ts, f.raw_json,
              o.side
            FROM fills f
            JOIN orders o ON o.client_order_id = f.client_order_id
            ORDER BY f.id ASC;
            """
        )
        cols = [c[0] for c in cur.description]
        for row in cur.fetchall():
            yield {cols[i]: row[i] for i in range(len(cols))}

