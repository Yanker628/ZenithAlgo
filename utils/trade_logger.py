import csv
import _csv
from dataclasses import dataclass
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Optional, TextIO


@dataclass
class TradeRecord:
    ts: Any
    symbol: str
    side: str
    qty: float
    price: float | None
    mode: str
    realized_pnl_after_trade: float
    position_qty_after_trade: float | None
    position_avg_price_after_trade: float | None


class TradeLogger:
    def __init__(self, base_dir: str | Path = "data/trades"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.current_date: date | None = None
        self.file: Optional[TextIO] = None
        self.writer: Optional[_csv._writer] = None

    def _ensure_file(self):
        today = datetime.now(timezone.utc).date()
        if self.current_date == today and self.file:
            return

        if self.file:
            self.file.close()

        self.current_date = today
        file_path = self.base_dir / f"trades_{today}.csv"
        new_file = not file_path.exists()
        self.file = file_path.open("a", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file)
        if new_file:
            self.writer.writerow(
                [
                    "ts",
                    "symbol",
                    "side",
                    "qty",
                    "price",
                    "mode",
                    "realized_pnl_after_trade",
                    "position_qty_after_trade",
                    "position_avg_price_after_trade",
                ]
            )

    def log(self, record: TradeRecord):
        self._ensure_file()
        ts = record.ts
        if isinstance(ts, datetime):
            ts_val = ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_val = str(ts)

        if self.writer is None or self.file is None:
            raise RuntimeError("TradeLogger not initialized")

        self.writer.writerow(
            [
                ts_val,
                record.symbol,
                record.side,
                f"{record.qty:.4f}",
                f"{record.price:.2f}" if record.price is not None else "",
                record.mode,
                f"{record.realized_pnl_after_trade:.4f}",
                f"{record.position_qty_after_trade:.4f}" if record.position_qty_after_trade is not None else "",
                f"{record.position_avg_price_after_trade:.2f}" if record.position_avg_price_after_trade is not None else "",
            ]
        )
        self.file.flush()

    def close(self):
        if self.file:
            self.file.close()
            self.file = None
            self.writer = None
