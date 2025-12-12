"""实时/纸面/干跑交易主循环。

该模块负责将行情 Tick 依次送入策略、风控与 broker。
与回测模块的差异仅在于数据源与时间推进方式。
"""

from datetime import datetime, date, timezone

from broker.base import BrokerMode, Broker
from broker.binance import BinanceBroker
from broker.mock import MockBroker
from market.client import BinanceMarketClient, FakeMarketClient
from risk.manager import RiskManager
from strategy.registry import build_strategy
from utils.config_loader import load_config
from utils.logging import setup_logger
from utils.pnl import compute_unrealized_pnl
from utils.sizer import resolve_sizing_cfg, size_signals
from utils.trade_logger import TradeLogger


def create_broker(cfg, trade_logger: TradeLogger | None) -> Broker:
    """根据配置创建 broker 实例。

    Parameters
    ----------
    cfg:
        `AppConfig` 或等价对象，包含 mode/exchange 等字段。
    trade_logger:
        交易日志记录器，dry-run/paper/live 共享。

    Returns
    -------
    Broker
        对应运行模式的 broker。
    """
    mode_str = cfg.mode.replace("_", "-").lower()
    mode_map = {
        "dry-run": BrokerMode.DRY_RUN,
        "paper": BrokerMode.PAPER,
        "live": BrokerMode.LIVE,
        "live-testnet": BrokerMode.LIVE_TESTNET,
        "live-mainnet": BrokerMode.LIVE_MAINNET,
    }
    mode = mode_map.get(mode_str, BrokerMode.DRY_RUN)
    if mode == BrokerMode.DRY_RUN:
        return MockBroker(trade_logger)
    else:
        return BinanceBroker(
            base_url=cfg.exchange.base_url,
            api_key=cfg.exchange.api_key,
            api_secret=cfg.exchange.api_secret,
            mode=mode,
            allow_live=cfg.exchange.allow_live,
            symbols_allowlist=cfg.exchange.symbols_allowlist,
            min_notional=cfg.exchange.min_notional,
            min_qty=cfg.exchange.min_qty,
            qty_step=cfg.exchange.qty_step,
            price_step=cfg.exchange.price_step,
            max_price_deviation_pct=getattr(cfg.exchange, "max_price_deviation_pct", None),
            trade_logger=trade_logger,
        )


def create_market_client(cfg, logger):
    """根据运行模式选择行情客户端。

    Parameters
    ----------
    cfg:
        配置对象，需包含 mode/exchange/ws_url。
    logger:
        用于行情客户端的 logger。

    Returns
    -------
    MarketClient
        实盘/纸面使用 BinanceMarketClient，其余使用 FakeMarketClient。
    """
    mode = cfg.mode.replace("_", "-").lower()
    ws_url = getattr(cfg.exchange, "ws_url", None) or "wss://stream.binance.com:9443/ws"
    if mode in {"live", "real", "paper", "live-testnet", "live-mainnet"}:
        return BinanceMarketClient(ws_base=ws_url, logger=logger)
    return FakeMarketClient(logger=logger)


def run_runner(
    cfg_path: str = "config/config.yml",
    cfg_obj=None,
    max_ticks: int | None = None,
):
    """运行实时/纸面/干跑主循环。

    Parameters
    ----------
    cfg_path:
        配置文件路径。
    cfg_obj:
        已加载的配置对象；提供时会忽略 cfg_path。
    max_ticks:
        可选的最大 tick 数，达到后退出（便于 dry-run/测试）。

    Returns
    -------
    dict
        运行结束时的持仓与 PnL 快照。
    """
    logger = setup_logger("engine")
    cfg = cfg_obj or load_config(cfg_path)

    equity_base = cfg.equity_base or 10000
    strat = build_strategy(getattr(cfg, "strategy", None))
    risk = RiskManager(cfg.risk, equity_base=equity_base)
    trade_logger = TradeLogger()
    broker = create_broker(cfg, trade_logger)
    last_prices: dict[str, float] = {}
    current_trading_day: date | None = None
    last_pnl_log_ts: datetime | None = None
    log_interval_secs = 5

    market_client = create_market_client(cfg, logger)
    sizing_cfg = resolve_sizing_cfg(cfg)

    if isinstance(market_client, BinanceMarketClient):
        try:
            last_price = market_client.rest_price(cfg.symbol)
            logger.info(f"Initial price from REST: {cfg.symbol} {last_price}")
        except Exception as exc:
            logger.warning(f"REST price fetch failed, fallback to WS only: {exc}")

    tick_stream = market_client.tick_stream(cfg.symbol)

    tick_count = 0
    for tick in tick_stream:
        tick_count += 1
        last_prices[tick.symbol] = tick.price

        tick_ts = tick.ts or datetime.now(timezone.utc)
        tick_day = tick_ts.date()
        if current_trading_day is None:
            current_trading_day = tick_day
        elif tick_day != current_trading_day:
            current_trading_day = tick_day
            broker.realized_pnl_today = 0.0
            risk.reset_daily_state()
            logger.info("Trading day changed to %s, reset daily PnL.", current_trading_day.isoformat())

        # 1. 策略产生原始信号
        raw_signals = strat.on_tick(tick)
        if not raw_signals:
            continue

        # 2. 统一 sizing：先补价格，再算真实下单数量
        for sig in raw_signals:
            sig.price = last_prices.get(sig.symbol) or tick.price
        sized_signals = size_signals(raw_signals, broker, sizing_cfg, equity_base, logger=logger)

        # 3. 风控过滤
        filtered_signals = risk.filter_signals(sized_signals)
        if not filtered_signals:
            continue

        # 4. 执行信号
        for sig in filtered_signals:
            result = broker.execute(sig)
            logger.info(f"Order result: {result}")

        # 5. PnL 估算（已实现 + 未实现），推送到风控并打印
        unrealized_pnl = compute_unrealized_pnl(broker.positions, last_prices)
        broker.unrealized_pnl = unrealized_pnl
        total_pnl = broker.realized_pnl_today + unrealized_pnl
        total_pct = (total_pnl / equity_base) * 100
        risk.set_daily_pnl(total_pnl / equity_base)

        now = tick.ts or datetime.now(timezone.utc)
        if (last_pnl_log_ts is None) or ((now - last_pnl_log_ts).total_seconds() >= log_interval_secs):
            logger.info(
                "Tick %s %.2f | PnL(realized_today=%.2f, unrealized=%.2f, total=%.2f, %+.4f%%)",
                tick.symbol,
                tick.price,
                broker.realized_pnl_today,
                unrealized_pnl,
                total_pnl,
                total_pct,
            )
            last_pnl_log_ts = now
        else:
            logger.debug(
                "Tick %s %.2f | PnL(realized_today=%.2f, unrealized=%.2f, total=%.2f, %+.4f%%)",
                tick.symbol,
                tick.price,
                broker.realized_pnl_today,
                unrealized_pnl,
                total_pnl,
                total_pct,
            )

        # 持久化交易日志已在 broker 内部处理
        if max_ticks is not None and tick_count >= max_ticks:
            logger.info("Reached max_ticks=%s, exiting runner.", max_ticks)
            break

    return {
        "positions": broker.positions,
        "realized_pnl_today": broker.realized_pnl_today,
        "realized_pnl_all": broker.realized_pnl_all,
        "unrealized_pnl": broker.unrealized_pnl,
    }


def main():
    run_runner()

if __name__ == "__main__":
    main()
