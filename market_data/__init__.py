"""行情数据模块（market_data）。

该包聚合：
- 实时行情客户端（REST/WS）
- 历史数据加载与下载（CSV + REST 补齐）
- 数据模型的稳定导出入口（见 `market_data/models.py`）

说明
----
为了避免与“数据目录”语义混淆，这里统一使用 `market_data/` 作为行情模块的官方命名。
"""

from market_data.client import BinanceMarketClient, FakeMarketClient, MarketClient, get_market_client
from market_data.loader import HistoricalDataLoader

__all__ = [
    "MarketClient",
    "FakeMarketClient",
    "BinanceMarketClient",
    "get_market_client",
    "HistoricalDataLoader",
]
