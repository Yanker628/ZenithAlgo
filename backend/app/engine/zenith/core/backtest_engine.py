"""单次回测引擎（BacktestEngine）。

目标是“一眼能看懂”：配置 → 数据 → 特征 → 策略/风控/撮合 → 指标/产物。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

import pandas as pd

from zenith.execution.backtest_broker import BacktestBroker
from zenith.core.base_engine import BaseEngine, EngineResult
from zenith.core.sources.event_source import PandasFrameEventSource
from zenith.core.signal_pipeline import SignalTrace, prepare_signals
from zenith.common.models.models import OrderSignal, Tick
from zenith.strategies.factors.registry import apply_factors, build_factors
from zenith.strategies.risk.manager import RiskManager
from zenith.strategies.registry import build_strategy
from zenith.common.config.config_loader import BacktestConfig, StrategyConfig, load_config
from zenith.data.loader import HistoricalDataLoader
from zenith.common.utils.logging import setup_logger
from zenith.common.utils.pnl import compute_unrealized_pnl
from zenith.common.utils.sizer import resolve_sizing_cfg
from zenith.analysis.metrics.metrics import compute_metrics
from zenith.analysis.metrics.metrics_canon import canonicalize_metrics
from zenith.analysis.visualizations.plotter import plot_drawdown, plot_equity_curve, plot_return_hist
from zenith.analysis.research.schemas import BacktestSummary, CanonicalMetrics, DataHealth, PositionSnapshot


BASE_CANDLE_COLS = {"ts", "symbol", "open", "high", "low", "close", "volume"}


def parse_iso(val: str | datetime | date) -> datetime:
    """解析 ISO 时间字符串（或 datetime/date）为 UTC datetime。"""
    if isinstance(val, datetime):
        dt = val
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(val, date) and not isinstance(val, datetime):
        return datetime(val.year, val.month, val.day, tzinfo=timezone.utc)
    s = str(val)
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_backtest_summary(broker: BacktestBroker, last_prices: Dict[str, float]) -> dict[str, Any]:
    unrealized = compute_unrealized_pnl(broker.positions, last_prices)
    return {
        "realized_pnl": float(broker.realized_pnl_all),
        "final_unrealized": float(unrealized),
        "cash": float(broker.cash),
        "positions": {s: {"qty": float(p.qty), "avg_price": float(p.avg_price)} for s, p in broker.positions.items()},
    }


def _candles_to_frame(candles: Iterable) -> pd.DataFrame:
    rows = []
    for c in candles:
        rows.append(
            {
                "ts": c.end_ts,
                "symbol": c.symbol,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("ts").reset_index(drop=True)


def _export_equity_csv(equity_curve: list[tuple[datetime, float]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not equity_curve:
        return

    # M2: Standardized Equity Curve Output
    # Columns: ts, equity, drawdown, drawdown_pct
    data = []
    peak = -1e9
    for ts, eq in sorted(equity_curve, key=lambda x: x[0]):
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = dd / peak if peak > 0 else 0.0
        data.append({
            "ts": ts.isoformat(),
            "equity": eq,
            "drawdown": dd,
            "drawdown_pct": dd_pct
        })
    
    df = pd.DataFrame(data)
    df.to_csv(path, index=False)


def _export_trades_csv(trades: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in trades:
        row = dict(t)
        ts = row.get("ts")
        if isinstance(ts, datetime):
            row["ts"] = ts.isoformat()
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)


def _resolve_strategy_param(bt_cfg: BacktestConfig, cfg, key: str, default: Any = None) -> Any:
    if bt_cfg.strategy and isinstance(bt_cfg.strategy.params, dict):
        v = bt_cfg.strategy.params.get(key)
        if v is not None:
            return v
    try:
        params = getattr(cfg, "strategy", None).params  # type: ignore[union-attr]
    except Exception:
        params = {}
    if isinstance(params, dict):
        v = params.get(key)
        if v is not None:
            return v
    return default


def _append_equity_point(equity_curve: list[tuple[datetime, float]], ts: datetime, equity: float) -> None:
    """
    追加（或覆盖）权益曲线点：
    - 同一 ts 重复写入时，覆盖最后一个点，避免重复 ts 造成指标波动。
    """
    if equity_curve and equity_curve[-1][0] == ts:
        equity_curve[-1] = (ts, equity)
    else:
        equity_curve.append((ts, equity))


def _compute_equity(broker: BacktestBroker) -> float:
    """按 broker 当前视图估算权益。"""
    return broker.cash + sum(
        p.qty * broker.last_prices.get(sym, p.avg_price) for sym, p in broker.positions.items()
    )





class BacktestEngine(BaseEngine):
    """单次回测引擎。

    Notes
    -----
    - 仅保留类接口，不再提供 `python -m ...` 的模块级入口；
    - CLI 统一由仓库根目录 `main.py` 承担。
    """

    def __init__(
        self,
        *,
        cfg_path: str = "config/config.yml",
        cfg_obj=None,
        artifacts_dir: str | Path | None = None,
    ):
        self._cfg_path = cfg_path
        self._cfg_obj = cfg_obj
        self._artifacts_dir = artifacts_dir

        self.cfg = None
        self.broker: BacktestBroker | None = None
        self.last_prices: dict[str, float] = {}

    def run(self) -> EngineResult:
        cfg = self._load_cfg()
        backtest_config = self._load_bt_cfg(cfg)  # 重命名 bt_cfg -> backtest_config 以提高可读性
        logger = setup_logger("backtest")

        record_equity_each_bar = bool(backtest_config.record_equity_each_bar)
        # 初始化权益基数 (Initial Equity)
        equity_base = float(backtest_config.initial_equity or getattr(cfg, "equity_base", 0) or 0)
        if equity_base <= 0:
            equity_base = 10000.0

        # 加载数据与特征 (Data Loading)
        candles_df, feature_cols, data_health_raw = self._load_candles_and_features(cfg, backtest_config)
        data_health = DataHealth.model_validate(data_health_raw)

        # 构建核心组件 (Build Core Components)
        strategy = self._build_strategy(cfg, backtest_config)
        risk = self._build_risk(cfg, backtest_config, equity_base=equity_base)
        broker = self._build_broker(backtest_config, equity_base=equity_base)
        self.broker = broker

        sizing_cfg = resolve_sizing_cfg(cfg)
        last_prices: dict[str, float] = {}

        last_ts: datetime | None = None
        current_day: date | None = None
        day_start_equity = equity_base
        signal_trace = SignalTrace()

        # 定义逐 Tick 处理逻辑 (Event Handler)
        def _on_tick(tick: Tick) -> None:
            nonlocal last_ts, current_day, day_start_equity
            last_ts = tick.ts

            # 1. 每日结算检查 (Daily Roll)
            # 如果日期变更，重置当日 PnL 统计，并更新当日起始权益，用于风控计算（如日内最大亏损）
            current_day, day_start_equity = self._maybe_roll_day(
                tick_day=tick.ts.date(),
                current_day=current_day,
                broker=broker,
                risk=risk,
                last_prices=last_prices,
                equity_base=equity_base,
                day_start_equity=day_start_equity,
            )

            # 2. 更新最新价格 (Market Data Update)
            last_prices[tick.symbol] = tick.price
            # 更新 Broker 内部的未结盈亏，用于风控模块监控实时净值
            self._update_daily_pnl_pct(
                broker=broker,
                risk=risk,
                last_prices=last_prices,
                equity_base=equity_base,
                day_start_equity=day_start_equity,
            )

            # 3. 信号生成与筛选 (Signal Pipeline)
            # 包含：策略生成 -> 仓位管理(Sizing) -> 风控拦截(Risk) 的全流程
            filtered = prepare_signals(
                tick=tick,
                strategy=strategy,
                broker=broker,
                risk=risk,
                sizing_cfg=sizing_cfg,
                equity_base=equity_base,
                last_prices=last_prices,
                logger=logger,
                trace=signal_trace,
            )

            # 4. 信号执行 (Execution)
            if filtered:
                for sig in filtered:
                    broker.execute(
                        sig,
                        tick_price=tick.price,
                        ts=tick.ts,
                        record_equity=(not record_equity_each_bar),
                    )

            # 5. 权益曲线记录 (Equity Recording)
            if record_equity_each_bar:
                self._record_mtm_equity(broker=broker, last_prices=last_prices, ts=tick.ts)

        # 启动事件循环
        logger.info("Engine loop start: source=PandasFrameEventSource")
        source = PandasFrameEventSource(candles_df, feature_cols=feature_cols)
        self.run_loop(source=source, on_tick=_on_tick, logger=logger)
        logger.info("Engine loop end.")

        # 结束处理：强制平仓与最终权益点
        self._maybe_flatten_on_end(backtest_config, broker=broker, last_prices=last_prices, last_ts=last_ts)
        self._record_final_equity_point(
            broker=broker,
            last_prices=last_prices,
            last_ts=last_ts,
            record_equity_each_bar=record_equity_each_bar,
        )

        self.last_prices = last_prices
        metrics_raw = compute_metrics(broker.equity_curve, broker.trades)
        metrics = CanonicalMetrics.model_validate(canonicalize_metrics(metrics_raw))

        summary_raw = build_backtest_summary(broker, last_prices)
        summary = BacktestSummary(
            realized_pnl=float(summary_raw["realized_pnl"]),
            final_unrealized=float(summary_raw["final_unrealized"]),
            cash=float(summary_raw["cash"]),
            positions={
                s: PositionSnapshot(qty=float(v["qty"]), avg_price=float(v["avg_price"]))
                for s, v in (summary_raw.get("positions") or {}).items()
            },
            metrics=metrics,
            data_health=data_health,
            signal_trace=signal_trace.to_dict(),
        )

        artifacts = self._export_artifacts(cfg, backtest_config, broker=broker)
        logger.info("Backtest summary: %s", summary.model_dump())
        return EngineResult(summary=summary, artifacts=artifacts)

    def _load_cfg(self):
        return self._cfg_obj or load_config(self._cfg_path, load_env=False, expand_env=False)

    @staticmethod
    def _load_bt_cfg(cfg) -> BacktestConfig:
        bt_cfg = getattr(cfg, "backtest", None)
        if not isinstance(bt_cfg, BacktestConfig):
            raise ValueError("backtest config not found")
        return bt_cfg

    @staticmethod
    def _build_strategy(cfg, bt_cfg: BacktestConfig) -> Any:
        strategy_obj = getattr(cfg, "strategy", None)
        base_type = str(getattr(strategy_obj, "type", None) or "simple_ma")
        base_params = dict(getattr(strategy_obj, "params", {}) or {})

        bt_strategy = bt_cfg.strategy
        bt_type = str(getattr(bt_strategy, "type", None) or base_type)
        bt_params = dict(getattr(bt_strategy, "params", {}) or {})

        short_feature = str(bt_params.get("short_feature", "ma_short"))
        long_feature = str(bt_params.get("long_feature", "ma_long"))

        merged_params = {**base_params, **bt_params}
        merged_params.setdefault("short_feature", short_feature)
        merged_params.setdefault("long_feature", long_feature)
        merged_params["require_features"] = True

        return build_strategy(StrategyConfig(type=bt_type, params=merged_params))

    @staticmethod
    def _build_risk(cfg, bt_cfg: BacktestConfig, *, equity_base: float) -> RiskManager:
        suppress_risk_logs = bool(bt_cfg.quiet_risk_logs)
        risk_cfg = deepcopy(cfg.risk)
        if isinstance(bt_cfg.risk, dict):
            for k, v in bt_cfg.risk.items():
                if hasattr(risk_cfg, k):
                    setattr(risk_cfg, k, v)
        return RiskManager(risk_cfg, suppress_warnings=suppress_risk_logs, equity_base=equity_base)

    @staticmethod
    def _build_broker(bt_cfg: BacktestConfig, *, equity_base: float) -> BacktestBroker:
        fees = bt_cfg.fees
        return BacktestBroker(
            initial_equity=equity_base,
            maker_fee=float(fees.maker),
            taker_fee=float(fees.taker),
            slippage_bp=float(fees.slippage_bp),
        )

    @staticmethod
    def _load_candles_and_features(cfg, bt_cfg: BacktestConfig) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
        loader = HistoricalDataLoader(bt_cfg.data_dir)
        candles = loader.load_klines_for_backtest(
            symbol=bt_cfg.symbol,
            interval=bt_cfg.interval,
            start=parse_iso(bt_cfg.start),
            end=parse_iso(bt_cfg.end),
            auto_download=bool(bt_cfg.auto_download),
        )
        candles_df = _candles_to_frame(candles)

        strategy_obj = getattr(cfg, "strategy", None)
        base_type = str(getattr(strategy_obj, "type", None) or "simple_ma")
        bt_strategy = bt_cfg.strategy
        bt_type = str(getattr(bt_strategy, "type", None) or base_type)

        bt_params = dict(getattr(bt_cfg.strategy, "params", {}) or {})
        short_feature = str(bt_params.get("short_feature", "ma_short"))
        long_feature = str(bt_params.get("long_feature", "ma_long"))

        factors_cfg = bt_cfg.factors
        if not factors_cfg:
            short_w = int(_resolve_strategy_param(bt_cfg, cfg, "short_window", 0) or 0)
            long_w = int(_resolve_strategy_param(bt_cfg, cfg, "long_window", 0) or 0)
            factors_cfg = []
            if short_w > 0:
                factors_cfg.append({"name": "ma", "params": {"window": short_w, "price_col": "close", "out_col": short_feature}})
            if long_w > 0:
                factors_cfg.append({"name": "ma", "params": {"window": long_w, "price_col": "close", "out_col": long_feature}})
            
            if bt_type == "trend_filtered":
                atr_period = int(_resolve_strategy_param(bt_cfg, cfg, "atr_period", 14) or 14)
                atr_feature = str(bt_params.get("atr_feature", "atr_14"))
                factors_cfg.append(
                    {
                        "name": "atr",
                        "params": {
                            "period": atr_period,
                            "high_col": "high",
                            "low_col": "low",
                            "close_col": "close",
                            "out_col": atr_feature,
                        },
                    }
                )

        factors = build_factors(factors_cfg)
        candles_df = apply_factors(candles_df, factors) if not candles_df.empty else candles_df

        feature_cols = [c for c in candles_df.columns if c not in BASE_CANDLE_COLS]
        data_health: dict[str, Any] = {
            "n_bars": int(len(candles_df)),
            "symbol": str(bt_cfg.symbol),
            "interval": str(bt_cfg.interval),
            "start": str(bt_cfg.start),
            "end": str(bt_cfg.end),
            "n_features": int(len(feature_cols)),
        }
        if feature_cols and not candles_df.empty:
            try:
                data_health["feature_nan_ratio"] = float(candles_df[feature_cols].isna().mean().mean())
            except Exception:
                pass

        return candles_df, feature_cols, data_health

    @staticmethod
    def _maybe_roll_day(
        *,
        tick_day: date,
        current_day: date | None,
        broker: BacktestBroker,
        risk: RiskManager,
        last_prices: dict[str, float],
        equity_base: float,
        day_start_equity: float,
    ) -> tuple[date, float]:
        if current_day is None:
            return tick_day, day_start_equity
        if tick_day == current_day:
            return current_day, day_start_equity

        broker.realized_pnl_today = 0.0
        risk.reset_daily_state(log=False)
        new_base = broker.cash + compute_unrealized_pnl(broker.positions, last_prices)
        if new_base <= 0:
            new_base = equity_base
        return tick_day, new_base

    @staticmethod
    def _update_daily_pnl_pct(
        *,
        broker: BacktestBroker,
        risk: RiskManager,
        last_prices: dict[str, float],
        equity_base: float,
        day_start_equity: float,
    ) -> None:
        unrealized = compute_unrealized_pnl(broker.positions, last_prices)
        broker.unrealized_pnl = unrealized
        total_pnl = broker.realized_pnl_today + unrealized
        base_for_day = day_start_equity if day_start_equity else equity_base
        daily_pnl_pct = total_pnl / base_for_day if base_for_day else 0.0
        risk.set_daily_pnl(daily_pnl_pct)

    @staticmethod
    def _record_mtm_equity(*, broker: BacktestBroker, last_prices: dict[str, float], ts: datetime) -> None:
        broker.last_prices.update(last_prices)
        broker.unrealized_pnl = broker._compute_unrealized_pnl()
        _append_equity_point(broker.equity_curve, ts, _compute_equity(broker))

    @staticmethod
    def _maybe_flatten_on_end(
        bt_cfg: BacktestConfig,
        *,
        broker: BacktestBroker,
        last_prices: dict[str, float],
        last_ts: datetime | None,
    ) -> None:
        flatten_on_end = bool(bt_cfg.flatten_on_end)
        if not flatten_on_end or last_ts is None or not last_prices:
            return

        record_equity_each_bar = bool(bt_cfg.record_equity_each_bar)
        for sym, pos in list(broker.positions.items()):
            if pos.qty == 0:
                continue
            mkt_price = last_prices.get(sym)
            if mkt_price is None:
                continue
            side = "sell" if pos.qty > 0 else "buy"
            sig = OrderSignal(symbol=sym, side=side, qty=abs(pos.qty), reason="flatten")
            broker.execute(sig, tick_price=mkt_price, ts=last_ts, record_equity=(not record_equity_each_bar))

    @staticmethod
    def _record_final_equity_point(
        *,
        broker: BacktestBroker,
        last_prices: dict[str, float],
        last_ts: datetime | None,
        record_equity_each_bar: bool,
    ) -> None:
        if last_ts is None or not last_prices:
            return
        broker.last_prices.update(last_prices)
        broker.unrealized_pnl = broker._compute_unrealized_pnl()
        final_equity = _compute_equity(broker)
        if record_equity_each_bar:
            _append_equity_point(broker.equity_curve, last_ts, final_equity)
        else:
            # 保持历史行为：末尾追加最终点（允许与成交点同一 ts 重复）
            broker.equity_curve.append((last_ts, final_equity))

    def _export_artifacts(
        self,
        cfg: Any,
        bt_cfg: BacktestConfig,
        *,
        broker: BacktestBroker,
    ) -> dict[str, Any] | None:
        if self._artifacts_dir is None:
            return None

        out_dir = Path(self._artifacts_dir)
        _export_trades_csv(broker.trades, out_dir / "trades.csv")
        _export_equity_csv(broker.equity_curve, out_dir / "equity.csv")

        skip_plots = bool(bt_cfg.skip_plots)
        if not skip_plots:
            logger = setup_logger("backtest")
            try:
                plot_equity_curve(broker.equity_curve, str(out_dir / "equity.png"))
                plot_drawdown(broker.equity_curve, str(out_dir / "drawdown.png"))
                plot_return_hist(broker.equity_curve, str(out_dir / "return_hist.png"))
            except Exception as exc:  # pragma: no cover
                logger.warning("Plotting failed: %s", exc)

        return {"dir": str(out_dir)}
