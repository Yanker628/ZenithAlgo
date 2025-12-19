import time
from pathlib import Path

import pandas as pd

from database.dataset_store import DatasetStore


def _write_csv(path: Path, rows: list[dict]) -> None:
    header = ["symbol", "open", "high", "low", "close", "volume", "start_ts", "end_ts"]
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(row[h]) for h in header))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def test_dataset_store_data_hashes_and_meta(tmp_path: Path) -> None:
    data_dir = tmp_path / "history"
    store = DatasetStore(data_dir)

    rows = [
        {
            "symbol": "AAA",
            "open": 1,
            "high": 2,
            "low": 1,
            "close": 2,
            "volume": 10,
            "start_ts": "2024-01-01T00:00:00Z",
            "end_ts": "2024-01-01T01:00:00Z",
        }
    ]
    _write_csv(store.csv_path("AAA", "1h"), rows)
    _write_csv(store.csv_path("BBB", "1h"), rows)

    combined, per_symbol = store.data_hashes(["AAA", "BBB"], "1h")
    assert combined
    assert set(per_symbol.keys()) == {"AAA", "BBB"}

    meta_path = store.meta_path("AAA", "1h")
    assert meta_path.exists()
    meta = meta_path.read_text(encoding="utf-8")
    assert per_symbol["AAA"] in meta
    assert store.parquet_path("AAA", "1h").exists()
    meta_json = meta_path.read_text(encoding="utf-8")
    assert "\"hash_source\": \"parquet\"" in meta_json


def test_dataset_store_parquet_cache_refresh(tmp_path: Path) -> None:
    data_dir = tmp_path / "history"
    store = DatasetStore(data_dir)
    csv_path = store.csv_path("AAA", "1h")

    _write_csv(
        csv_path,
        [
            {
                "symbol": "AAA",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 10,
                "start_ts": "2024-01-01T00:00:00Z",
                "end_ts": "2024-01-01T01:00:00Z",
            }
        ],
    )
    df_first = store.load_frame("AAA", "1h")
    assert len(df_first) == 1
    parquet_path = store.parquet_path("AAA", "1h")
    assert parquet_path.exists()

    time.sleep(1)
    _write_csv(
        csv_path,
        [
            {
                "symbol": "AAA",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 10,
                "start_ts": "2024-01-01T00:00:00Z",
                "end_ts": "2024-01-01T01:00:00Z",
            },
            {
                "symbol": "AAA",
                "open": 2,
                "high": 3,
                "low": 2,
                "close": 3,
                "volume": 12,
                "start_ts": "2024-01-01T01:00:00Z",
                "end_ts": "2024-01-01T02:00:00Z",
            },
        ],
    )
    df_second = store.load_frame("AAA", "1h")
    assert len(df_second) == 2

    cached = pd.read_parquet(parquet_path)
    assert len(cached) == 2
