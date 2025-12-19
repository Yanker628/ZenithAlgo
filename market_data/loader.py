"""历史数据加载与下载。

支持从 CSV 读取 Tick/Candle，并在需要时通过 Binance REST 补齐 K 线。
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator, List

import pandas as pd
import requests

from shared.models.models import Candle, Tick


def _parse_dt(val: str) -> datetime:
    try:
        if val.isdigit():
            ts_int = int(val)
            if ts_int > 1e12:
                return datetime.fromtimestamp(ts_int / 1000, tz=timezone.utc)
            return datetime.fromtimestamp(ts_int, tz=timezone.utc)
        return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception as exc:
        raise ValueError(f"Invalid datetime value: {val}") from exc


def load_ticks_from_csv(
    path: str | Path,
    tz: timezone = timezone.utc,
    parser: Callable[[dict[str, str]], Tick] | None = None,
) -> Iterator[Tick]:
    """从 CSV 读取 Tick 流。"""
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


def load_candles_from_csv(
    path: str | Path,
    tz: timezone = timezone.utc,
    parser: Callable[[dict[str, str]], Candle] | None = None,
) -> Iterator[Candle]:
    """从 CSV 读取 Candle 流。"""
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
    """简单包装，便于未来扩展（过滤/采样）。"""
    yield from source


def iter_candles(source: Iterable[Candle]) -> Iterator[Candle]:
    yield from source


class HistoricalDataLoader:
    """历史 K 线数据管理器。"""

    def __init__(self, data_dir: str = "dataset/history"):
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

    def generate_meta(self, symbol: str, interval: str) -> None:
        """生成数据集元信息与 Hash 校验"""
        csv_path = self._klines_path(symbol, interval)
        if not csv_path.exists():
            return

        # 1. 计算 Content Hash
        # 读取二进制内容以保证 Hash 唯一性
        with csv_path.open("rb") as f:
            content = f.read()
            data_hash = hashlib.sha256(content).hexdigest()

        # 2. 读取 CSV 获取元数据
        # 使用 pandas 读取以快速获取 schema 和行数
        try:
            df = pd.read_csv(csv_path)
            row_count = len(df)
            columns = list(df.columns)
            # 假设 CSV 中有 standard columns, 尝试获取时间范围
            start_time = df["start_ts"].min() if "start_ts" in df.columns and not df.empty else None
            end_time = df["end_ts"].max() if "end_ts" in df.columns and not df.empty else None
        except Exception as e:
            print(f"Warning: Failed to read CSV for meta generation: {e}")
            row_count = 0
            columns = []
            start_time = None
            end_time = None

        meta = {
            "symbol": symbol,
            "interval": interval,
            "start_time": str(start_time),
            "end_time": str(end_time),
            "row_count": row_count,
            "columns": columns,
            "data_hash": data_hash,
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        meta_path = self.data_dir / "cache" / f"{symbol}_{interval}.meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    def load_klines(self, symbol: str, interval: str, start: datetime, end: datetime) -> List[Candle]:
        """从文件读取一段时间的 K 线，优先读取 Parquet 缓存 (M6-2)。"""
        csv_path = self._klines_path(symbol, interval)
        # Parquet 缓存路径
        cache_dir = self.data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        parquet_path = cache_dir / f"{symbol}_{interval}.parquet"

        df_kline = pd.DataFrame()

        # 策略：如果 Parquet 存在，直接读；如果不存在但 CSV 存在，读取 CSV 并转换；否则为空
        if parquet_path.exists():
            df_kline = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            # 自动转换流：发现只有 CSV，触发转换
            try:
                df_kline = pd.read_csv(csv_path)
                
                # 确保时间列为 datetime (UTC)
                if "start_ts" in df_kline.columns:
                     df_kline["start_ts"] = pd.to_datetime(df_kline["start_ts"], utc=True)
                if "end_ts" in df_kline.columns:
                     df_kline["end_ts"] = pd.to_datetime(df_kline["end_ts"], utc=True)

                 # 保存为 Parquet (Snappy 压缩)
                df_kline.to_parquet(parquet_path, engine="pyarrow", compression="snappy")
                
                # 同时生成元信息
                self.generate_meta(symbol, interval)
                
            except Exception as e:
                print(f"Error converting CSV to Parquet: {e}")
                pass
        
        if df_kline.empty:
            return []

        # 再次确保时间列类型 (防止读取的 Parquet 是旧版本 String 类型)
        if "start_ts" in df_kline.columns and not pd.api.types.is_datetime64_any_dtype(df_kline["start_ts"]):
             df_kline["start_ts"] = pd.to_datetime(df_kline["start_ts"], utc=True)
        if "end_ts" in df_kline.columns and not pd.api.types.is_datetime64_any_dtype(df_kline["end_ts"]):
             df_kline["end_ts"] = pd.to_datetime(df_kline["end_ts"], utc=True)



        # 过滤时间范围
        # Pandas filtering
        mask = (df_kline["end_ts"] >= start) & (df_kline["start_ts"] <= end)
        filtered_df = df_kline[mask]


        candles: list[Candle] = []
        for _, row in filtered_df.iterrows():
            candles.append(
                Candle(
                    symbol=row["symbol"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    start_ts=row["start_ts"].to_pydatetime(),
                    end_ts=row["end_ts"].to_pydatetime(),
                )
            )
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
        """加载回测区间所需 K 线，并可自动补齐缺失数据。"""
        path = self._klines_path(symbol, interval)
        if force_download or (auto_download and not path.exists()):
            self.download_binance_klines(symbol, interval, start, end, path, overwrite=True)
        elif auto_download and path.exists():
            min_start, max_end = self._file_time_range(path)
            if min_start is None or max_end is None:
                self.download_binance_klines(symbol, interval, start, end, path, overwrite=True)
            else:
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
        """从 Binance REST 拉取历史 K 线并写入 CSV。"""
        url = "https://api.binance.com/api/v3/klines"
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        rows: list[list[str]] = []

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
        """将 Candle 序列转换为粗粒度 Tick（按收盘价）。"""
        for c in candles:
            yield Tick(symbol=c.symbol, price=c.close, ts=c.end_ts)

