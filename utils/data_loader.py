from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Iterable, Callable, List

import requests

from market.models import Tick, Candle


def _parse_dt(val: str) -> datetime:
    try:
        # 支持 ISO 格式或秒/毫秒时间戳
        if val.isdigit():
            # 判断是秒还是毫秒
            ts_int = int(val)
            if ts_int > 1e12:
                return datetime.fromtimestamp(ts_int / 1000, tz=timezone.utc)
            return datetime.fromtimestamp(ts_int, tz=timezone.utc)
        return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception as exc:
        raise ValueError(f"Invalid datetime value: {val}") from exc


def load_ticks_from_csv(path: str | Path, tz: timezone = timezone.utc, parser: Callable[[dict[str, str]], Tick] | None = None) -> Iterator[Tick]:
    """
    从 CSV 文件读取 Tick，默认列名：symbol,price,ts。ts 支持 ISO 或秒/毫秒时间戳。
    """
    with Path(path).open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if parser:
                yield parser(row)
                continue
            symbol = row["symbol"]
            price = float(row["price"])
            ts = _parse_dt(row["ts"]).astimezone(tz)
            yield Tick(symbol=symbol, price=price, ts=ts)


def load_candles_from_csv(path: str | Path, tz: timezone = timezone.utc, parser: Callable[[dict[str, str]], Candle] | None = None) -> Iterator[Candle]:
    """
    从 CSV 文件读取 Candle，默认列名：symbol,open,high,low,close,volume,start_ts,end_ts。
    时间字段支持 ISO 或秒/毫秒时间戳。
    """
    with Path(path).open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if parser:
                yield parser(row)
                continue
            symbol = row["symbol"]
            open_ = float(row["open"])
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            volume = float(row.get("volume", 0) or 0)
            start_ts = _parse_dt(row["start_ts"]).astimezone(tz)
            end_ts = _parse_dt(row["end_ts"]).astimezone(tz)
            yield Candle(
                symbol=symbol,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                start_ts=start_ts,
                end_ts=end_ts,
            )


def iter_ticks(source: Iterable[Tick]) -> Iterator[Tick]:
    """
    简单包装，便于未来扩展（过滤/采样）。
    """
    for t in source:
        yield t


def iter_candles(source: Iterable[Candle]) -> Iterator[Candle]:
    for c in source:
        yield c


class HistoricalDataLoader:
    def __init__(self, data_dir: str = "data/history"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _klines_path(self, symbol: str, interval: str) -> Path:
        return self.data_dir / f"{symbol}_{interval}.csv"

    def _file_time_range(self, path: Path) -> tuple[datetime | None, datetime | None]:
        min_start = None
        max_end = None
        if not path.exists():
            return None, None
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    s = _parse_dt(row["start_ts"])
                    e = _parse_dt(row["end_ts"])
                except Exception:
                    continue
                if min_start is None or s < min_start:
                    min_start = s
                if max_end is None or e > max_end:
                    max_end = e
        return min_start, max_end

    def load_klines(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        从 CSV 读取一段时间的 K 线，返回 Candle 列表。
        约定文件路径: data_dir/<symbol>_<interval>.csv
        """
        path = self._klines_path(symbol, interval)
        candles: list[Candle] = []
        for candle in load_candles_from_csv(path):
            if candle.end_ts < start or candle.start_ts > end:
                continue
            candles.append(candle)
        return candles

    def load_klines_for_backtest(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        auto_download: bool = False,
        force_download: bool = False,
    ) -> List[Candle]:
        path = self._klines_path(symbol, interval)
        if force_download or (auto_download and not path.exists()):
            self.download_binance_klines(symbol, interval, start, end, path, overwrite=True)
        elif auto_download and path.exists():
            min_start, max_end = self._file_time_range(path)
            if min_start is None or max_end is None:
                self.download_binance_klines(symbol, interval, start, end, path, overwrite=True)
            else:
                # 仅补缺，不覆盖已有完整区间
                if min_start > start:
                    self.download_binance_klines(symbol, interval, start, min_start, path, overwrite=False)
                if max_end < end:
                    self.download_binance_klines(symbol, interval, max_end, end, path, overwrite=False)
        if not path.exists():
            raise FileNotFoundError(f"Kline file not found: {path}")
        return self.load_klines(symbol, interval, start, end)

    def download_binance_klines(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        dest_path: Path,
        overwrite: bool = False,
    ):
        """
        从 Binance 公共 REST 拉取历史 K 线并写入 CSV。
        overwrite=False 时会合并已有文件，避免覆盖已有数据。
        """
        url = "https://api.binance.com/api/v3/klines"
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        rows: list[list[str]] = []

        # 如已有文件且不覆盖，先读入旧行
        existing_rows: list[list[str]] = []
        if dest_path.exists() and not overwrite:
            for candle in load_candles_from_csv(dest_path):
                existing_rows.append(
                    [
                        candle.symbol,
                        f"{candle.open}",
                        f"{candle.high}",
                        f"{candle.low}",
                        f"{candle.close}",
                        f"{candle.volume}",
                        candle.start_ts.isoformat(),
                        candle.end_ts.isoformat(),
                    ]
                )

        cur = start_ms
        while cur < end_ms:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": cur,
                "endTime": end_ms,
                "limit": 1000,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            for item in data:
                open_time = datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc)
                close_time = datetime.fromtimestamp(item[6] / 1000, tz=timezone.utc)
                rows.append(
                    [
                        symbol,
                        item[1],
                        item[2],
                        item[3],
                        item[4],
                        item[5],
                        open_time.isoformat(),
                        close_time.isoformat(),
                    ]
                )
            cur = data[-1][6] + 1
            if cur >= end_ms:
                break

        all_rows = existing_rows + rows if not overwrite else rows
        # 去重 + 排序，按 start_ts
        def _key(r: list[str]):
            try:
                return datetime.fromisoformat(r[6])
            except Exception:
                return datetime.min

        dedup: dict[str, list[str]] = {}
        for r in all_rows:
            dedup[r[6]] = r
        merged_rows = sorted(dedup.values(), key=_key)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with dest_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["symbol", "open", "high", "low", "close", "volume", "start_ts", "end_ts"])
            writer.writerows(merged_rows)

    def candle_to_ticks(self, candles: list[Candle]) -> Iterator[Tick]:
        """
        将 K 线转换为粗粒度 Tick 流，按收盘价生成 Tick。
        """
        for c in candles:
            yield Tick(symbol=c.symbol, price=c.close, ts=c.end_ts)
