from datetime import datetime, date, timezone

from broker.base import BrokerMode, Broker
from broker.binance import BinanceBroker
from broker.mock import MockBroker
from market.client import BinanceMarketClient, FakeMarketClient
from market.models import OrderSignal
from risk.manager import RiskManager
from strategy.simple_ma import SimpleMAStrategy
from utils.config_loader import load_config, StrategyConfig
from utils.logging import setup_logger
from utils.pnl import compute_unrealized_pnl
from utils.trade_logger import TradeLogger


def create_broker(cfg, trade_logger: TradeLogger | None) -> Broker:
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
        trade_logger=trade_logger,
    )


def create_market_client(cfg, logger):
    mode = cfg.mode.replace("_", "-").lower()
    ws_url = getattr(cfg.exchange, "ws_url", None) or "wss://stream.binance.com:9443/ws"
    if mode in {"live", "real", "paper", "live-testnet", "live-mainnet"}:
        return BinanceMarketClient(ws_base=ws_url, logger=logger)
    return FakeMarketClient(logger=logger)

def create_strategy(strat_cfg: StrategyConfig | None) -> SimpleMAStrategy:
    if strat_cfg is None:
        return SimpleMAStrategy()
    if strat_cfg.type != "simple_ma":
        raise ValueError(f"Unsupported strategy type: {strat_cfg.type}")
    params = strat_cfg.params or {}
    return SimpleMAStrategy(
        short_window=int(params.get("short_window", 5)),
        long_window=int(params.get("long_window", 20)),
        min_ma_diff=float(params.get("min_ma_diff", 0.0)),
        cooldown_secs=int(params.get("cooldown_secs", 0)),
    )


def main():
    logger = setup_logger("engine")
    cfg = load_config("config/config.yml")

    equity_base = cfg.equity_base or 10000
    strat = create_strategy(getattr(cfg, "strategy", None))
    risk = RiskManager(cfg.risk, equity_base=equity_base)
    trade_logger = TradeLogger()
    broker = create_broker(cfg, trade_logger)
    last_prices: dict[str, float] = {}
    current_trading_day: date | None = None
    last_pnl_log_ts: datetime | None = None
    log_interval_secs = 5

    market_client = create_market_client(cfg, logger)

    if isinstance(market_client, BinanceMarketClient):
        try:
            last_price = market_client.rest_price(cfg.symbol)
            logger.info(f"Initial price from REST: {cfg.symbol} {last_price}")
        except Exception as exc:
            logger.warning(f"REST price fetch failed, fallback to WS only: {exc}")

    tick_stream = market_client.tick_stream(cfg.symbol)

    for tick in tick_stream:
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

        # 2. 风控过滤
        filtered_signals = risk.filter_signals(raw_signals)
        if not filtered_signals:
            continue

        # 3. 执行信号
        for sig in filtered_signals:
            # 把当前价格塞到 signal 上，让 broker 执行层使用
            sig.price = last_prices.get(sig.symbol)
            result = broker.execute(sig)
            logger.info(f"Order result: {result}")

        # 4. PnL 估算（已实现 + 未实现），推送到风控并打印
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

if __name__ == "__main__":
    main()
