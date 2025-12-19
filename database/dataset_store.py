"""数据集存储与加载接口（DatasetStore）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from shared.models.models import Candle
from utils.hashing import sha256_file, sha256_text


def _ensure_datetime(df: pd.DataFrame, col: str) -> None:
    if col in df.columns and not pd.api.types.is_datetime64_any_dtype(df[col]):
        try:
            df[col] = pd.to_datetime(df[col], utc=True)
        except Exception:
            # 兼容混合 ISO8601 格式（是否带毫秒可能不一致）
            df[col] = pd.to_datetime(df[col], utc=True, format="mixed")


def _format_ts(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, pd.Timestamp):
        val = val.to_pydatetime()
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).isoformat()
    return str(val)


class DatasetStore:
    """统一数据集加载与元信息管理。"""

    def __init__(self, data_dir: str | Path = "dataset/history", cache_dir: str | Path | None = None):
        self.data_dir = Path(data_dir)
        self.cache_dir = Path(cache_dir) if cache_dir else self.data_dir / "cache"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _csv_path(self, symbol: str, interval: str) -> Path:
        return self.data_dir / f"{symbol}_{interval}.csv"

    def _parquet_path(self, symbol: str, interval: str) -> Path:
        return self.cache_dir / f"{symbol}_{interval}.parquet"

    def _meta_path(self, symbol: str, interval: str) -> Path:
        return self.cache_dir / f"{symbol}_{interval}.meta.json"

    def csv_path(self, symbol: str, interval: str) -> Path:
        return self._csv_path(symbol, interval)

    def parquet_path(self, symbol: str, interval: str) -> Path:
        return self._parquet_path(symbol, interval)

    def meta_path(self, symbol: str, interval: str) -> Path:
        return self._meta_path(symbol, interval)

    def _hash_source_path(self, symbol: str, interval: str) -> Path | None:
        parquet_path = self._parquet_path(symbol, interval)
        if parquet_path.exists():
            return parquet_path
        return None

    def _read_source_path(self, symbol: str, interval: str) -> Path | None:
        parquet_path = self._parquet_path(symbol, interval)
        if parquet_path.exists():
            return parquet_path
        csv_path = self._csv_path(symbol, interval)
        if csv_path.exists():
            return csv_path
        return None

    def _read_frame(self, path: Path) -> pd.DataFrame:
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
        _ensure_datetime(df, "start_ts")
        _ensure_datetime(df, "end_ts")
        return df

    def _write_parquet_cache(self, df: pd.DataFrame, parquet_path: Path) -> None:
        if df.empty:
            return
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(parquet_path, engine="pyarrow", compression="snappy")

    def _ensure_parquet(self, symbol: str, interval: str) -> Path | None:
        csv_path = self._csv_path(symbol, interval)
        parquet_path = self._parquet_path(symbol, interval)
        if parquet_path.exists() and csv_path.exists():
            if csv_path.stat().st_mtime > parquet_path.stat().st_mtime:
                df = self._read_frame(csv_path)
                self._write_parquet_cache(df, parquet_path)
            return parquet_path
        if parquet_path.exists():
            return parquet_path
        if csv_path.exists():
            df = self._read_frame(csv_path)
            self._write_parquet_cache(df, parquet_path)
            return parquet_path
        return None

    def data_hash(self, symbol: str, interval: str) -> str:
        path = self._ensure_parquet(symbol, interval)
        if not path:
            raise FileNotFoundError(f"dataset not found: {symbol} {interval}")
        return sha256_file(path)

    def data_hashes(
        self,
        symbols: Iterable[str],
        interval: str,
        *,
        ensure_meta: bool = True,
    ) -> tuple[str, dict[str, str]]:
        per_symbol: dict[str, str] = {}
        for symbol in symbols:
            if ensure_meta:
                self.ensure_meta(symbol, interval)
            per_symbol[symbol] = self.data_hash(symbol, interval)
        combined_payload = "\n".join(f"{k}={per_symbol[k]}" for k in sorted(per_symbol.keys()))
        return sha256_text(combined_payload), per_symbol

    def generate_meta(self, symbol: str, interval: str) -> dict[str, Any] | None:
        path = self._ensure_parquet(symbol, interval)
        if not path:
            return None
        df = self._read_frame(path)
        row_count = int(len(df))
        columns = list(df.columns)
        start_time = _format_ts(df["start_ts"].min()) if "start_ts" in df.columns and not df.empty else None
        end_time = _format_ts(df["end_ts"].max()) if "end_ts" in df.columns and not df.empty else None

        meta = {
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time,
            "end_time": end_time,
            "row_count": row_count,
            "columns": columns,
            "data_hash": sha256_file(path),
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_format": path.suffix.lstrip("."),
            "hash_source": "parquet",
        }
        meta_path = self._meta_path(symbol, interval)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def ensure_meta(self, symbol: str, interval: str) -> dict[str, Any] | None:
        meta_path = self._meta_path(symbol, interval)
        if meta_path.exists():
            return json.loads(meta_path.read_text(encoding="utf-8"))
        return self.generate_meta(symbol, interval)

    def ensure_meta_for_symbols(self, symbols: Iterable[str], interval: str) -> dict[str, dict[str, Any]]:
        metas: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            meta = self.ensure_meta(symbol, interval)
            if meta:
                metas[symbol] = meta
        return metas

    def load_frames(self, symbols: Iterable[str], interval: str) -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            frames[symbol] = self.load_frame(symbol, interval)
        return frames

    def load_frame(self, symbol: str, interval: str) -> pd.DataFrame:
        parquet_path = self._ensure_parquet(symbol, interval)
        if parquet_path:
            df = self._read_frame(parquet_path)
            self.ensure_meta(symbol, interval)
            return df
        path = self._read_source_path(symbol, interval)
        if not path:
            return pd.DataFrame()
        df = self._read_frame(path)
        self.ensure_meta(symbol, interval)
        return df

    def load_klines(self, symbol: str, interval: str, start: datetime, end: datetime) -> list[Candle]:
        df = self.load_frame(symbol, interval)
        if df.empty:
            return []
        if "start_ts" not in df.columns or "end_ts" not in df.columns:
            return []
        mask = (df["end_ts"] >= start) & (df["start_ts"] <= end)
        filtered_df = df[mask]
        candles: list[Candle] = []
        for _, row in filtered_df.iterrows():
            candles.append(
                Candle(
                    symbol=row["symbol"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0)),
                    start_ts=row["start_ts"].to_pydatetime(),
                    end_ts=row["end_ts"].to_pydatetime(),
                )
            )
        return candles

    def load_klines_for_symbols(
        self,
        symbols: Iterable[str],
        interval: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, list[Candle]]:
        results: dict[str, list[Candle]] = {}
        for symbol in symbols:
            results[symbol] = self.load_klines(symbol, interval, start, end)
        return results
