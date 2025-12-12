"""行情客户端（实时 Binance / 本地假数据）。"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Iterator

import requests
import websockets

from market.models import Tick
from utils.logging import setup_logger


class MarketClient(ABC):
    """行情客户端抽象基类。"""

    @abstractmethod
    def tick_stream(self, symbol: str) -> Iterator[Tick]:
        """生成 Tick 流。

        Parameters
        ----------
        symbol:
            交易对。

        Returns
        -------
        Iterator[Tick]
            按时间顺序产生的 Tick。
        """
        raise NotImplementedError


class FakeMarketClient(MarketClient):
    """本地假数据源，便于离线开发/测试。"""

    def __init__(self, logger=None):
        self.logger = logger or setup_logger("market-fake")

    def tick_stream(self, symbol: str) -> Iterator[Tick]:
        price = 100.0
        while True:
            price += 0.1
            yield Tick(symbol=symbol, price=price, ts=datetime.now(timezone.utc))
            time.sleep(1)


class BinanceMarketClient(MarketClient):
    """Binance 实时行情客户端（REST + WebSocket）。"""

    def __init__(self, ws_base: str | None = "wss://stream.binance.com:9443/ws", logger=None):
        self.ws_base = ws_base or "wss://stream.binance.com:9443/ws"
        self.logger = logger or setup_logger("market-binance")

    def rest_price(self, symbol: str) -> float:
        """通过 REST 拉取最新价格。"""
        url = "https://api.binance.com/api/v3/ticker/price"
        resp = requests.get(url, params={"symbol": symbol}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return float(data["price"])

    async def _ws_loop(self, symbol: str, queue: asyncio.Queue):
        stream_name = f"{symbol.lower()}@trade"
        url = f"{self.ws_base}/{stream_name}"
        while True:
            try:
                async with websockets.connect(url) as ws:
                    self.logger.info("Connected to Binance WS: %s", url)
                    async for msg in ws:
                        data = json.loads(msg)
                        price = float(data["p"])
                        ts_ms = data.get("T")
                        ts = (
                            datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                            if ts_ms
                            else datetime.now(timezone.utc)
                        )
                        await queue.put(Tick(symbol=symbol, price=price, ts=ts))
            except Exception as exc:  # pragma: no cover - 网络异常重连
                self.logger.warning("WS error %s, reconnecting in 3s...", exc)
                await asyncio.sleep(3)

    def tick_stream(self, symbol: str) -> Iterator[Tick]:
        """同步生成器包装异步 WebSocket。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        queue: asyncio.Queue = asyncio.Queue()
        loop.create_task(self._ws_loop(symbol, queue))

        while True:
            tick = loop.run_until_complete(queue.get())
            yield tick


def get_market_client(mode: str, exchange_name: str, ws_url: str | None = None, logger=None) -> MarketClient:
    """根据配置选择行情客户端。

    Parameters
    ----------
    mode:
        运行模式（live/paper/dry-run/backtest 等）。
    exchange_name:
        交易所名称（当前仅支持 binance）。
    ws_url:
        可选 WebSocket URL。

    Returns
    -------
    MarketClient
        对应模式的行情客户端。
    """
    mode_l = mode.lower().replace("_", "-")
    ex_l = exchange_name.lower()

    if mode_l in {"live", "real", "paper", "live-testnet", "live-mainnet"}:
        if ex_l == "binance":
            return BinanceMarketClient(ws_base=ws_url or "wss://stream.binance.com:9443/ws", logger=logger)
        raise ValueError(f"Unsupported exchange for live/paper mode: {exchange_name}")

    if mode_l in {"dry-run", "dry_run", "backtest", "fake", "mock"}:
        return FakeMarketClient(logger=logger)

    raise ValueError(f"Unsupported market mode: {mode}")
