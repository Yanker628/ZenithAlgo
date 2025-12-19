from __future__ import annotations

import argparse
import time
from typing import Callable

import numpy as np
import pandas as pd


def _timeit(fn: Callable[[], None], rounds: int) -> float:
    start = time.perf_counter()
    for _ in range(rounds):
        fn()
    return time.perf_counter() - start


def _gen_prices(n: int) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = np.cumsum(rng.normal(0, 1, n)) + 100
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    return pd.DataFrame({"close": close, "high": high, "low": low})


def main() -> None:
    parser = argparse.ArgumentParser(description="Rust 算子基准测试（本地）")
    parser.add_argument("--n", type=int, default=200_000, help="样本数量")
    parser.add_argument("--rounds", type=int, default=3, help="重复次数")
    parser.add_argument("--window", type=int, default=14, help="窗口/周期")
    args = parser.parse_args()

    df = _gen_prices(args.n)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    try:
        import zenithalgo_rust
    except Exception:
        zenithalgo_rust = None

    print(f"样本数={args.n}, rounds={args.rounds}, window={args.window}")

    def pandas_ma() -> None:
        close.rolling(args.window, min_periods=args.window).mean()

    def pandas_rsi() -> None:
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.rolling(args.window, min_periods=args.window).mean()
        avg_loss = loss.rolling(args.window, min_periods=args.window).mean()
        rs = avg_gain / avg_loss
        _ = 100.0 - (100.0 / (1.0 + rs))

    def pandas_atr() -> None:
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        tr.rolling(args.window, min_periods=args.window).mean()

    print("Pandas MA:", _timeit(pandas_ma, args.rounds))
    print("Pandas RSI:", _timeit(pandas_rsi, args.rounds))
    print("Pandas ATR:", _timeit(pandas_atr, args.rounds))
    print(
        "Pandas EMA:",
        _timeit(
            lambda: close.ewm(span=args.window, adjust=False, min_periods=args.window).mean(),
            args.rounds,
        ),
    )

    if zenithalgo_rust is None:
        print("Rust 模块不可用，跳过 Rust 基准。")
        return

    def rust_ma() -> None:
        zenithalgo_rust.ma(close.to_list(), args.window)

    def rust_rsi() -> None:
        zenithalgo_rust.rsi(close.to_list(), args.window)

    def rust_atr() -> None:
        zenithalgo_rust.atr(high.to_list(), low.to_list(), close.to_list(), args.window)

    print("Rust MA:", _timeit(rust_ma, args.rounds))
    print("Rust RSI:", _timeit(rust_rsi, args.rounds))
    print("Rust ATR:", _timeit(rust_atr, args.rounds))
    print("Rust EMA:", _timeit(lambda: zenithalgo_rust.ema(close.to_list(), args.window), args.rounds))


if __name__ == "__main__":
    main()
