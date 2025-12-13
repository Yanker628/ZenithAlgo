"""单次回测引擎（BacktestEngine）。

目标是“一眼能看懂”：配置 → 数据 → 特征 → 策略/风控/撮合 → 指标/产物。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

import pandas as pd

from broker.backtest_broker import BacktestBroker
from engine.base_engine import BaseEngine, EngineResult
from engine.signal_pipeline import prepare_signals
from shared.models.models import OrderSignal, Tick
from algo.factors.registry import apply_factors, build_factors
from algo.risk.manager import RiskManager
from algo.strategy.registry import build_strategy
from shared.config.config_loader import load_config, StrategyConfig
from data.loader import HistoricalDataLoader
from shared.utils.logging import setup_logger
from utils.pnl import compute_unrealized_pnl
from utils.sizer import resolve_sizing_cfg
from analysis.metrics.metrics import compute_metrics
from analysis.visualizations.plotter import plot_drawdown, plot_equity_curve, plot_return_hist


BASE_CANDLE_COLS = {"ts", "symbol", "open", "high", "low", "close", "volume"}


def parse_iso(val: str) -> datetime:
    """解析 ISO 时间字符串为 UTC datetime。"""
    return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_backtest_summary(broker: BacktestBroker, last_prices: Dict[str, float]) -> dict:
    """根据 broker 状态生成回测总结。

    Parameters
    ----------
    broker:
        回测 broker。
    last_prices:
        每个 symbol 的最后价格。

    Returns
    -------
    dict
        包含 realized/unrealized/cash/positions 等字段。
    """
    unrealized = compute_unrealized_pnl(broker.positions, last_prices)
    return {
        "realized_pnl": broker.realized_pnl_all,
        "final_unrealized": unrealized,
        "cash": broker.cash,
        "positions": {s: {"qty": p.qty, "avg_price": p.avg_price} for s, p in broker.positions.items()},
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


def _resolve_strategy_param(bt_cfg: dict, cfg, key: str, default: Any = None) -> Any:
    strat = bt_cfg.get("strategy", {}) if isinstance(bt_cfg, dict) else {}
    if isinstance(strat, dict) and key in strat and strat.get(key) is not None:
        return strat.get(key)
    try:
        params = getattr(cfg, "strategy", None).params  # type: ignore[union-attr]
    except Exception:
        params = {}
    if isinstance(params, dict) and key in params and params.get(key) is not None:
        return params.get(key)
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


def _row_to_tick(row: Any, *, feature_cols: list[str]) -> Tick:
    tick_ts = row["ts"]
    tick_price = float(row["close"])
    tick_symbol = str(row["symbol"])
    features = {c: float(row[c]) for c in feature_cols if pd.notna(row[c])}
    return Tick(symbol=tick_symbol, price=tick_price, ts=tick_ts, features=features or None)


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
        bt_cfg = self._load_bt_cfg(cfg)
        logger = setup_logger("backtest")

        record_equity_each_bar = bool(bt_cfg.get("record_equity_each_bar", False))
        equity_base = float(bt_cfg.get("initial_equity", getattr(cfg, "equity_base", 0) or 0))

        candles_df, feature_cols, data_health = self._load_candles_and_features(cfg, bt_cfg)

        strat = self._build_strategy(cfg, bt_cfg)
        risk = self._build_risk(cfg, bt_cfg, equity_base=equity_base)
        broker = self._build_broker(bt_cfg, equity_base=equity_base)
        self.broker = broker

        sizing_cfg = resolve_sizing_cfg(cfg)
        last_prices: dict[str, float] = {}

        last_ts: datetime | None = None
        current_day: date | None = None
        day_start_equity = equity_base

        for _, row in candles_df.iterrows():
            tick = _row_to_tick(row, feature_cols=feature_cols)
            last_ts = tick.ts

            current_day, day_start_equity = self._maybe_roll_day(
                tick_day=tick.ts.date(),
                current_day=current_day,
                broker=broker,
                risk=risk,
                last_prices=last_prices,
                equity_base=equity_base,
                day_start_equity=day_start_equity,
            )

            last_prices[tick.symbol] = tick.price
            self._update_daily_pnl_pct(
                broker=broker,
                risk=risk,
                last_prices=last_prices,
                equity_base=equity_base,
                day_start_equity=day_start_equity,
            )

            filtered = prepare_signals(
                tick=tick,
                strategy=strat,
                broker=broker,
                risk=risk,
                sizing_cfg=sizing_cfg,
                equity_base=equity_base,
                last_prices=last_prices,
                logger=logger,
            )

            if filtered:
                for sig in filtered:
                    broker.execute(
                        sig,
                        tick_price=tick.price,
                        ts=tick.ts,
                        record_equity=(not record_equity_each_bar),
                    )

            if record_equity_each_bar:
                self._record_mtm_equity(broker=broker, last_prices=last_prices, ts=tick.ts)

        # 结束处理：强制平仓与最终权益点
        self._maybe_flatten_on_end(bt_cfg, broker=broker, last_prices=last_prices, last_ts=last_ts)
        self._record_final_equity_point(
            broker=broker,
            last_prices=last_prices,
            last_ts=last_ts,
            record_equity_each_bar=record_equity_each_bar,
        )

        self.last_prices = last_prices
        summary = build_backtest_summary(broker, last_prices)
        summary["metrics"] = compute_metrics(broker.equity_curve, broker.trades)
        summary["data_health"] = data_health

        artifacts = self._export_artifacts(cfg, bt_cfg, broker=broker, summary=summary)
        logger.info("Backtest summary: %s", summary)
        return EngineResult(summary=summary, artifacts=artifacts)

    def _load_cfg(self):
        return self._cfg_obj or load_config(self._cfg_path, load_env=False, expand_env=False)

    @staticmethod
    def _load_bt_cfg(cfg) -> dict:
        bt_cfg = getattr(cfg, "backtest", None)
        if not isinstance(bt_cfg, dict):
            raise ValueError("backtest config not found")
        return bt_cfg

    @staticmethod
    def _build_strategy(cfg, bt_cfg: dict) -> Any:
        strat_cfg = bt_cfg.get("strategy", {}) if isinstance(bt_cfg, dict) else {}
        short_feature = str(strat_cfg.get("short_feature", "ma_short"))
        long_feature = str(strat_cfg.get("long_feature", "ma_long"))

        strategy_obj = getattr(cfg, "strategy", None)
        base_type = strategy_obj.type if strategy_obj else "simple_ma"
        base_params = dict(strategy_obj.params) if strategy_obj else {}

        bt_strategy_dict = bt_cfg.get("strategy", {}) if isinstance(bt_cfg, dict) else {}
        bt_type = str(bt_strategy_dict.get("type") or base_type)
        bt_params = dict(bt_strategy_dict) if isinstance(bt_strategy_dict, dict) else {}
        bt_params.pop("type", None)

        merged_params = {**base_params, **bt_params}
        merged_params.setdefault("short_feature", short_feature)
        merged_params.setdefault("long_feature", long_feature)
        merged_params["require_features"] = True

        return build_strategy(StrategyConfig(type=bt_type, params=merged_params))

    @staticmethod
    def _build_risk(cfg, bt_cfg: dict, *, equity_base: float) -> RiskManager:
        suppress_risk_logs = bool(bt_cfg.get("quiet_risk_logs", True)) if isinstance(bt_cfg, dict) else False
        risk_cfg = deepcopy(cfg.risk)
        if isinstance(bt_cfg, dict) and "risk" in bt_cfg and isinstance(bt_cfg["risk"], dict):
            for k, v in bt_cfg["risk"].items():
                if hasattr(risk_cfg, k):
                    setattr(risk_cfg, k, v)
        return RiskManager(risk_cfg, suppress_warnings=suppress_risk_logs, equity_base=equity_base)

    @staticmethod
    def _build_broker(bt_cfg: dict, *, equity_base: float) -> BacktestBroker:
        fees = bt_cfg.get("fees", {}) if isinstance(bt_cfg, dict) else {}
        return BacktestBroker(
            initial_equity=equity_base,
            maker_fee=float(fees.get("maker", 0.0)),
            taker_fee=float(fees.get("taker", 0.0004)),
            slippage_bp=float(fees.get("slippage_bp", 0.0)),
        )

    @staticmethod
    def _load_candles_and_features(cfg, bt_cfg: dict) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
        loader = HistoricalDataLoader(bt_cfg["data_dir"])
        candles = loader.load_klines_for_backtest(
            symbol=bt_cfg["symbol"],
            interval=bt_cfg["interval"],
            start=parse_iso(bt_cfg["start"]),
            end=parse_iso(bt_cfg["end"]),
            auto_download=bool(bt_cfg.get("auto_download", False)),
        )
        candles_df = _candles_to_frame(candles)

        strat_cfg = bt_cfg.get("strategy", {}) if isinstance(bt_cfg, dict) else {}
        short_feature = str(strat_cfg.get("short_feature", "ma_short"))
        long_feature = str(strat_cfg.get("long_feature", "ma_long"))

        factors_cfg = bt_cfg.get("factors")
        if not factors_cfg:
            short_w = int(_resolve_strategy_param(bt_cfg, cfg, "short_window", 0) or 0)
            long_w = int(_resolve_strategy_param(bt_cfg, cfg, "long_window", 0) or 0)
            factors_cfg = [
                {"name": "ma", "params": {"window": short_w, "price_col": "close", "out_col": short_feature}},
                {"name": "ma", "params": {"window": long_w, "price_col": "close", "out_col": long_feature}},
            ]

        factors = build_factors(factors_cfg)
        candles_df = apply_factors(candles_df, factors) if not candles_df.empty else candles_df

        feature_cols = [c for c in candles_df.columns if c not in BASE_CANDLE_COLS]
        data_health: dict[str, Any] = {
            "n_bars": int(len(candles_df)),
            "symbol": str(bt_cfg.get("symbol", "")),
            "interval": str(bt_cfg.get("interval", "")),
            "start": str(bt_cfg.get("start", "")),
            "end": str(bt_cfg.get("end", "")),
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
        bt_cfg: dict,
        *,
        broker: BacktestBroker,
        last_prices: dict[str, float],
        last_ts: datetime | None,
    ) -> None:
        flatten_on_end = bool(bt_cfg.get("flatten_on_end", False)) if isinstance(bt_cfg, dict) else False
        if not flatten_on_end or last_ts is None or not last_prices:
            return

        record_equity_each_bar = bool(bt_cfg.get("record_equity_each_bar", False))
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
        bt_cfg: dict,
        *,
        broker: BacktestBroker,
        summary: dict,
    ) -> dict[str, Any] | None:
        if self._artifacts_dir is None:
            return None

        out_dir = Path(self._artifacts_dir)
        _export_trades_csv(broker.trades, out_dir / "trades.csv")
        _export_equity_csv(broker.equity_curve, out_dir / "equity.csv")

        skip_plots = bool(bt_cfg.get("skip_plots", False)) if isinstance(bt_cfg, dict) else False
        if not skip_plots:
            logger = setup_logger("backtest")
            try:
                plot_equity_curve(broker.equity_curve, str(out_dir / "equity.png"))
                plot_drawdown(broker.equity_curve, str(out_dir / "drawdown.png"))
                plot_return_hist(broker.equity_curve, str(out_dir / "return_hist.png"))
            except Exception as exc:  # pragma: no cover
                logger.warning("Plotting failed: %s", exc)

        return {"dir": str(out_dir)}
