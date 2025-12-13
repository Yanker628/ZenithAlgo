"""实盘/纸面/干跑交易引擎（TradingEngine）。

目标是“一眼能看懂”：配置 → 行情源 → 策略/风控/执行 → PnL 日内控制 → 总结。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from broker.abstract_broker import BrokerMode, Broker
from broker.live_broker import LiveBroker
from broker.paper_broker import DryRunBroker, PaperBroker
from engine.base_engine import BaseEngine, EngineResult
from engine.sources.market_event_source import MarketEventSource
from market_data.client import BinanceMarketClient, FakeMarketClient
from algo.risk.manager import RiskManager
from engine.signal_pipeline import prepare_signals
from algo.strategy.registry import build_strategy
from shared.config.config_loader import load_config
from shared.utils.logging import setup_logger
from utils.pnl import compute_unrealized_pnl
from utils.sizer import resolve_sizing_cfg
from shared.utils.trade_logger import TradeLogger


class TradingEngine(BaseEngine):
    def __init__(
        self,
        *,
        cfg_path: str = "config/config.yml",
        cfg_obj=None,
        max_ticks: int | None = None,
    ):
        self._cfg_path = cfg_path
        self._cfg_obj = cfg_obj
        self._max_ticks = max_ticks

        self.cfg = None
        self.broker: Broker | None = None
        self.last_prices: dict[str, float] = {}

    def run(self) -> EngineResult:
        logger = setup_logger("engine")
        cfg = self._load_cfg()
        self.cfg = cfg

        equity_base = float(getattr(cfg, "equity_base", 0) or 0) or 10000.0
        strat = build_strategy(getattr(cfg, "strategy", None))
        risk = RiskManager(cfg.risk, equity_base=equity_base)

        trade_logger = TradeLogger()
        broker = self._build_broker(cfg, trade_logger=trade_logger)
        self.broker = broker
        self._maybe_startup_reconcile(cfg=cfg, broker=broker, logger=logger)

        market_client = self._build_market_client(cfg, logger=logger)
        sizing_cfg = resolve_sizing_cfg(cfg)
        self._maybe_warmup_price(cfg, market_client=market_client, logger=logger)

        self._run_loop(
            cfg=cfg,
            broker=broker,
            risk=risk,
            strat=strat,
            sizing_cfg=sizing_cfg,
            equity_base=equity_base,
            market_client=market_client,
            logger=logger,
        )

        return EngineResult(summary=self._build_summary(broker))

    def _load_cfg(self):
        return self._cfg_obj or load_config(self._cfg_path)

    @staticmethod
    def _build_broker(cfg, *, trade_logger: TradeLogger) -> Broker:
        mode_str = cfg.mode.replace("_", "-").lower()
        mode_map = {
            "dry-run": BrokerMode.DRY_RUN,
            "paper": BrokerMode.PAPER,
            "live": BrokerMode.LIVE,
            "live-testnet": BrokerMode.LIVE_TESTNET,
            "live-mainnet": BrokerMode.LIVE_MAINNET,
        }
        mode = mode_map.get(mode_str, BrokerMode.DRY_RUN)
        ledger_cfg = getattr(cfg, "ledger", None)
        ledger_path = "dataset/state/ledger.sqlite3"
        ledger_enabled = True
        if ledger_cfg is not None and not isinstance(ledger_cfg, dict):
            ledger_enabled = bool(getattr(ledger_cfg, "enabled", True))
            ledger_path = str(getattr(ledger_cfg, "path", None) or ledger_path)
        elif isinstance(ledger_cfg, dict):
            ledger_enabled = bool(ledger_cfg.get("enabled", True))
            ledger_path = str(ledger_cfg.get("path") or ledger_path)
        ledger_path = ledger_path if ledger_enabled else None

        recovery_cfg = getattr(cfg, "recovery", None)
        recovery_enabled = True
        recovery_mode = "observe_only"
        if recovery_cfg is not None and not isinstance(recovery_cfg, dict):
            recovery_enabled = bool(getattr(recovery_cfg, "enabled", True))
            recovery_mode = str(getattr(recovery_cfg, "mode", None) or recovery_mode).strip().lower()
        elif isinstance(recovery_cfg, dict):
            recovery_enabled = bool(recovery_cfg.get("enabled", True))
            recovery_mode = str(recovery_cfg.get("mode") or recovery_mode).strip().lower()
        if mode == BrokerMode.DRY_RUN:
            return DryRunBroker(trade_logger, ledger_path=ledger_path)
        if mode == BrokerMode.PAPER:
            return PaperBroker(mode=BrokerMode.PAPER, trade_logger=trade_logger, ledger_path=ledger_path)
        return LiveBroker(
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
            ledger_path=ledger_path,
            recovery_enabled=recovery_enabled,
            recovery_mode=recovery_mode,
        )

    @staticmethod
    def _maybe_startup_reconcile(*, cfg, broker: Broker, logger) -> None:
        if not isinstance(broker, LiveBroker):
            return
        if not getattr(broker, "recovery_enabled", False):
            return
        symbols = list(getattr(cfg.exchange, "symbols_allowlist", None) or [])
        if not symbols:
            symbols = [cfg.symbol]
        summary = broker.startup_reconcile(symbols=symbols)
        logger.info("Startup reconcile summary: %s", summary)

    @staticmethod
    def _build_market_client(cfg, *, logger) -> Any:
        mode = cfg.mode.replace("_", "-").lower()
        ws_url = getattr(cfg.exchange, "ws_url", None) or "wss://stream.binance.com:9443/ws"
        if mode in {"live", "real", "paper", "live-testnet", "live-mainnet"}:
            return BinanceMarketClient(ws_base=ws_url, logger=logger)
        return FakeMarketClient(logger=logger)

    @staticmethod
    def _maybe_warmup_price(cfg, *, market_client: Any, logger) -> None:
        if not isinstance(market_client, BinanceMarketClient):
            return
        try:
            last_price = market_client.rest_price(cfg.symbol)
            logger.info("Initial price from REST: %s %s", cfg.symbol, last_price)
        except Exception as exc:
            logger.warning("REST price fetch failed, fallback to WS only: %s", exc)

    def _run_loop(
        self,
        *,
        cfg,
        broker: Broker,
        risk: RiskManager,
        strat,
        sizing_cfg: dict[str, Any] | None,
        equity_base: float,
        market_client: Any,
        logger,
    ) -> None:
        current_trading_day: date | None = None
        last_pnl_log_ts: datetime | None = None
        log_interval_secs = 5

        def _on_tick(tick) -> None:
            nonlocal current_trading_day, last_pnl_log_ts
            self.last_prices[tick.symbol] = tick.price

            tick_ts = tick.ts or datetime.now(timezone.utc)
            current_trading_day = self._maybe_roll_day(
                tick_day=tick_ts.date(),
                current_day=current_trading_day,
                broker=broker,
                risk=risk,
                logger=logger,
            )

            filtered_signals = prepare_signals(
                tick=tick,
                strategy=strat,
                broker=broker,
                risk=risk,
                sizing_cfg=sizing_cfg,
                equity_base=equity_base,
                last_prices=self.last_prices,
                logger=logger,
            )

            for sig in filtered_signals:
                res = broker.execute(sig)
                logger.info("Order result: %s", res)

            last_pnl_log_ts = self._log_and_update_pnl(
                broker=broker,
                risk=risk,
                equity_base=equity_base,
                last_prices=self.last_prices,
                symbol=tick.symbol,
                price=float(tick.price),
                now=tick_ts,
                last_pnl_log_ts=last_pnl_log_ts,
                log_interval_secs=log_interval_secs,
                logger=logger,
            )

        source = MarketEventSource(market_client=market_client, symbol=cfg.symbol, logger=logger)
        self.run_loop(source=source, on_tick=_on_tick, max_events=self._max_ticks, logger=logger)

    @staticmethod
    def _maybe_roll_day(
        *,
        tick_day: date,
        current_day: date | None,
        broker: Broker,
        risk: RiskManager,
        logger,
    ) -> date:
        if current_day is None:
            return tick_day
        if tick_day == current_day:
            return current_day
        broker.realized_pnl_today = 0.0
        risk.reset_daily_state()
        logger.info("Trading day changed to %s, reset daily PnL.", tick_day.isoformat())
        return tick_day

    @staticmethod
    def _log_and_update_pnl(
        *,
        broker: Broker,
        risk: RiskManager,
        equity_base: float,
        last_prices: dict[str, float],
        symbol: str,
        price: float,
        now: datetime,
        last_pnl_log_ts: datetime | None,
        log_interval_secs: int,
        logger,
    ) -> datetime | None:
        unrealized_pnl = compute_unrealized_pnl(broker.positions, last_prices)
        broker.unrealized_pnl = unrealized_pnl
        total_pnl = broker.realized_pnl_today + unrealized_pnl
        total_pct = (total_pnl / equity_base) * 100 if equity_base else 0.0
        risk.set_daily_pnl(total_pnl / equity_base if equity_base else 0.0)

        should_log = (last_pnl_log_ts is None) or ((now - last_pnl_log_ts).total_seconds() >= log_interval_secs)
        if should_log:
            # 保持 runner 时期的日志格式，便于对比
            logger.info(
                "Tick %s %.2f | PnL(realized_today=%.2f, unrealized=%.2f, total=%.2f, %+.4f%%)",
                symbol,
                price,
                broker.realized_pnl_today,
                unrealized_pnl,
                total_pnl,
                total_pct,
            )
            return now
        return last_pnl_log_ts

    @staticmethod
    def _build_summary(broker: Broker) -> dict[str, Any]:
        return {
            "positions": broker.positions,
            "realized_pnl_today": broker.realized_pnl_today,
            "realized_pnl_all": broker.realized_pnl_all,
            "unrealized_pnl": broker.unrealized_pnl,
        }
