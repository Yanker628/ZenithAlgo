from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from engine.backtest_engine import BacktestEngine
from engine.trading_engine import TradingEngine
from shared.models.models import Tick
from shared.config.config_loader import load_config


class ParquetMarketClient:
    """基于 Parquet 的离线行情源，复用回测数据。"""

    def __init__(self, df: pd.DataFrame, *, symbol: str, feature_cols: list[str]):
        self._df = df
        self._symbol = symbol
        self._feature_cols = feature_cols

    def tick_stream(self, symbol: str):
        for _, row in self._df.iterrows():
            features = {}
            for col in self._feature_cols:
                val = row.get(col)
                if pd.notna(val):
                    features[col] = float(val)
            yield Tick(
                symbol=self._symbol,
                price=float(row["close"]),
                ts=row["end_ts"].to_pydatetime(),
                features=features or None,
            )


def _write_config(
    path: Path,
    *,
    data_dir: Path,
    start: str,
    end: str,
    short_window: int,
    long_window: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "mode: dry-run",
                "symbol: BTCUSDT",
                "timeframe: 1h",
                "equity_base: 10000",
                "exchange:",
                "  name: binance",
                "  base_url: https://example.invalid",
                "  api_key: null",
                "  api_secret: null",
                "  ws_url: null",
                "  allow_live: false",
                "  min_notional: 0",
                "  min_qty: 0",
                "  qty_step: 0",
                "  price_step: 0",
                "risk:",
                "  max_position_pct: 1.0",
                "  max_daily_loss_pct: 1.0",
                "strategy:",
                "  type: simple_ma",
                f"  short_window: {short_window}",
                f"  long_window: {long_window}",
                "  min_ma_diff: 0.0",
                "  cooldown_secs: 0",
                "  require_features: true",
                "sizing:",
                "  type: fixed_notional",
                "  trade_notional: 1000",
                "ledger:",
                "  enabled: false",
                "recovery:",
                "  enabled: false",
                "backtest:",
                "  symbol: BTCUSDT",
                "  interval: 1h",
                f'  start: "{start}"',
                f'  end: "{end}"',
                f"  data_dir: {data_dir.as_posix()}",
                "  initial_equity: 10000",
                "  skip_plots: true",
                "  fees:",
                "    maker: 0",
                "    taker: 0",
                "    slippage_bp: 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _format_ts(ts: Any) -> str:
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc).isoformat()
    return str(ts)


def _wrap_prepare_signals(records: list[dict], original):
    def _wrapped(*, tick, **kwargs):
        signals = original(tick=tick, **kwargs)
        for sig in signals:
            records.append(
                {
                    "ts": _format_ts(tick.ts),
                    "client_order_id": sig.client_order_id,
                    "price": float(sig.price) if sig.price is not None else None,
                }
            )
        return signals

    return _wrapped


def test_consistency_m7_backtest_vs_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_path = Path("tests/fixtures/golden/BTCUSDT_1h.parquet")
    if not fixture_path.exists():
        pytest.skip("Missing parquet fixture: BTCUSDT_1h.parquet")

    data_dir = tmp_path / "dataset" / "history"
    cache_dir = data_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = cache_dir / "BTCUSDT_1h.parquet"
    parquet_path.write_bytes(fixture_path.read_bytes())

    df = pd.read_parquet(parquet_path)
    df["start_ts"] = pd.to_datetime(df["start_ts"], utc=True)
    df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)
    df = df.sort_values("end_ts").reset_index(drop=True)

    short_window = 3
    long_window = 5
    df["ma_short"] = df["close"].rolling(short_window, min_periods=short_window).mean()
    df["ma_long"] = df["close"].rolling(long_window, min_periods=long_window).mean()

    start = _format_ts(df["start_ts"].min())
    end = _format_ts(df["end_ts"].max())

    cfg_path = tmp_path / "config.yml"
    _write_config(
        cfg_path,
        data_dir=data_dir,
        start=start,
        end=end,
        short_window=short_window,
        long_window=long_window,
    )

    monkeypatch.chdir(tmp_path)
    cfg = load_config(str(cfg_path), load_env=False, expand_env=False)

    backtest_records: list[dict] = []
    trading_records: list[dict] = []

    import engine.backtest_engine as backtest_engine
    import engine.trading_engine as trading_engine

    monkeypatch.setattr(
        backtest_engine,
        "prepare_signals",
        _wrap_prepare_signals(backtest_records, backtest_engine.prepare_signals),
    )
    monkeypatch.setattr(
        trading_engine,
        "prepare_signals",
        _wrap_prepare_signals(trading_records, trading_engine.prepare_signals),
    )

    market_client = ParquetMarketClient(df, symbol="BTCUSDT", feature_cols=["ma_short", "ma_long"])
    monkeypatch.setattr(
        trading_engine.TradingEngine,
        "_build_market_client",
        staticmethod(lambda cfg, logger: market_client),
    )

    BacktestEngine(cfg_obj=cfg, artifacts_dir=tmp_path / "results_backtest").run()
    TradingEngine(cfg_obj=cfg, max_ticks=len(df)).run()

    assert backtest_records, "Backtest produced no signals; consistency check is empty"
    assert trading_records, "TradingEngine produced no signals; consistency check is empty"
    assert backtest_records == trading_records
