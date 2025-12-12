"""单次回测引擎。

读取历史 K 线/ Tick，驱动策略→sizing→风控→回测 broker，
输出 summary 与指标，并可生成图表。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from broker.backtest import BacktestBroker
from market.models import OrderSignal, Tick
from factors.registry import apply_factors, build_factors
from risk.manager import RiskManager
from strategy.registry import build_strategy
from utils.config_loader import load_config, StrategyConfig
from utils.data_loader import HistoricalDataLoader
from utils.logging import setup_logger
from utils.pnl import compute_unrealized_pnl
from utils.sizer import resolve_sizing_cfg, size_signals
from utils.metrics import compute_metrics
from utils.plotter import plot_drawdown, plot_equity_curve, plot_return_hist


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


def _candles_to_frame(candles) -> pd.DataFrame:
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
    df = pd.DataFrame(
        [{"ts": ts.isoformat(), "equity": eq} for ts, eq in sorted(equity_curve, key=lambda x: x[0])]
    )
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
    if isinstance(bt_cfg, dict) and key in bt_cfg and bt_cfg.get(key) is not None:
        return bt_cfg.get(key)
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


def run_backtest(
    cfg_path: str = "config/config.yml",
    cfg_obj=None,
    artifacts_dir: str | Path | None = None,
    return_broker: bool = False,
):
    """运行一次回测。

    Parameters
    ----------
    cfg_path:
        配置文件路径，需包含 backtest 配置段。
    cfg_obj:
        已加载的配置对象；提供时会忽略 cfg_path。

    Returns
    -------
    dict
        回测 summary，包含 `metrics` 字段。

    Raises
    ------
    ValueError
        当 backtest 配置缺失时抛出。
    """
    # 回测不依赖私密 Key，缺省不加载/展开 env（避免占位符报错）
    cfg = cfg_obj or load_config(cfg_path, load_env=False, expand_env=False)
    bt_cfg = getattr(cfg, "backtest", None)
    if bt_cfg is None:
        raise ValueError("backtest config not found")
    logger = setup_logger("backtest")

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
    # factors 配置：优先 backtest.factors；否则用 MA short/long 生成默认因子列
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
    base_cols = {"ts", "symbol", "open", "high", "low", "close", "volume"}
    feature_cols = [c for c in candles_df.columns if c not in base_cols]

    # 策略配置：合并 top-level strategy 与 backtest.strategy，并兼容 sweep 直接写在 backtest 顶层的覆盖项
    strategy_obj = getattr(cfg, "strategy", None)
    base_type = strategy_obj.type if strategy_obj else "simple_ma"
    base_params = dict(strategy_obj.params) if strategy_obj else {}
    bt_strategy_dict = bt_cfg.get("strategy", {}) if isinstance(bt_cfg, dict) else {}
    bt_type = str(bt_strategy_dict.get("type") or base_type)
    bt_params = dict(bt_strategy_dict) if isinstance(bt_strategy_dict, dict) else {}
    bt_params.pop("type", None)

    merged_params = {**base_params, **bt_params}
    # sweep 兼容：允许 short_window/long_window/... 出现在 backtest 顶层
    for k in ["short_window", "long_window", "min_ma_diff", "cooldown_secs"]:
        v = _resolve_strategy_param(bt_cfg, cfg, k, None)
        if v is not None:
            merged_params[k] = v
    merged_params.setdefault("short_feature", short_feature)
    merged_params.setdefault("long_feature", long_feature)
    merged_params["require_features"] = True

    strat = build_strategy(StrategyConfig(type=bt_type, params=merged_params))
    suppress_risk_logs = bool(bt_cfg.get("quiet_risk_logs", True)) if isinstance(bt_cfg, dict) else False
    # 回测可在 backtest.risk 中覆盖风控参数（如调高 max_daily_loss_pct）
    risk_cfg = deepcopy(cfg.risk)
    if isinstance(bt_cfg, dict) and "risk" in bt_cfg and isinstance(bt_cfg["risk"], dict):
        for k, v in bt_cfg["risk"].items():
            if hasattr(risk_cfg, k):
                setattr(risk_cfg, k, v)
    risk = RiskManager(risk_cfg, suppress_warnings=suppress_risk_logs, equity_base=float(bt_cfg.get("initial_equity", getattr(cfg, "equity_base", 0) or 0)))
    fees = bt_cfg.get("fees", {}) if isinstance(bt_cfg, dict) else {}
    broker = BacktestBroker(
        initial_equity=float(bt_cfg.get("initial_equity", getattr(cfg, "equity_base", 0) or 0)),
        maker_fee=float(fees.get("maker", 0.0)),
        taker_fee=float(fees.get("taker", 0.0004)),
        slippage_bp=float(fees.get("slippage_bp", 0.0)),
    )

    last_prices: dict[str, float] = {}
    equity_base = float(bt_cfg.get("initial_equity", getattr(cfg, "equity_base", 0) or 0))
    sizing_cfg = resolve_sizing_cfg(cfg)

    last_ts = None
    current_day = None
    day_start_equity = equity_base
    for _, row in candles_df.iterrows():
        tick_ts = row["ts"]
        tick_price = float(row["close"])
        tick_symbol = str(row["symbol"])
        features = {c: float(row[c]) for c in feature_cols if pd.notna(row[c])}
        tick = Tick(symbol=tick_symbol, price=tick_price, ts=tick_ts, features=features or None)
        last_ts = tick.ts
        # 1) 跨日重置
        day = tick.ts.date()
        if current_day is None:
            current_day = day
        elif day != current_day:
            current_day = day
            broker.realized_pnl_today = 0.0
            risk.reset_daily_state(log=False)
            # 以跨日时点的权益作为新一天基数
            day_start_equity = broker.cash + compute_unrealized_pnl(broker.positions, last_prices)
            if day_start_equity <= 0:
                day_start_equity = equity_base
        # 2) 正常回测逻辑
        last_prices[tick.symbol] = tick.price

        # 更新 PnL（与实盘类似）
        unrealized = compute_unrealized_pnl(broker.positions, last_prices)
        broker.unrealized_pnl = unrealized
        total_pnl = broker.realized_pnl_today + unrealized
        base_for_day = day_start_equity if day_start_equity else equity_base
        daily_pnl_pct = total_pnl / base_for_day if base_for_day else 0.0
        risk.set_daily_pnl(daily_pnl_pct)

        # 策略
        signals = strat.on_tick(tick)
        if not signals:
            continue

        for sig in signals:
            sig.price = tick.price
        sized_signals = size_signals(signals, broker, sizing_cfg, equity_base, logger=logger)

        filtered = risk.filter_signals(sized_signals)
        if not filtered:
            continue

        for sig in filtered:
            res = broker.execute(sig, tick_price=tick.price, ts=tick.ts)
            logger.debug(f"Backtest order: {res}")

    # 可选：回测结束强制平仓，避免未实现收益影响胜率/统计
    flatten_on_end = bool(bt_cfg.get("flatten_on_end", False)) if isinstance(bt_cfg, dict) else False
    if flatten_on_end and last_ts is not None and last_prices:
        for sym, pos in list(broker.positions.items()):
            if pos.qty == 0:
                continue
            mkt_price = last_prices.get(sym)
            if mkt_price is None:
                continue
            side = "sell" if pos.qty > 0 else "buy"
            qty = abs(pos.qty)
            sig = OrderSignal(symbol=sym, side=side, qty=qty, reason="flatten")
            broker.execute(sig, tick_price=mkt_price, ts=last_ts)

    # 确保最终权益曲线记录最新价格（即使末尾无成交）
    if last_ts is not None and last_prices:
        broker.last_prices.update(last_prices)
        final_unrealized = broker._compute_unrealized_pnl()
        broker.unrealized_pnl = final_unrealized
        final_equity = broker.cash + sum(
            p.qty * broker.last_prices.get(sym, p.avg_price) for sym, p in broker.positions.items()
        )
        broker.equity_curve.append((last_ts, final_equity))

    summary = build_backtest_summary(broker, last_prices)
    summary["metrics"] = compute_metrics(broker.equity_curve, broker.trades)
    # 实验产物（可选）
    if artifacts_dir is not None:
        out_dir = Path(artifacts_dir)
        _export_trades_csv(broker.trades, out_dir / "trades.csv")
        _export_equity_csv(broker.equity_curve, out_dir / "equity.csv")
        skip_plots = bool(bt_cfg.get("skip_plots", False)) if isinstance(bt_cfg, dict) else False
        if not skip_plots:
            try:
                plot_equity_curve(broker.equity_curve, str(out_dir / "equity.png"))
                plot_drawdown(broker.equity_curve, str(out_dir / "drawdown.png"))
                plot_return_hist(broker.equity_curve, str(out_dir / "return_hist.png"))
            except Exception as exc:  # pragma: no cover
                logger.warning(f"Plotting failed: {exc}")

    logger.info(f"Backtest summary: {summary}")
    if return_broker:
        return summary, broker
    return summary


if __name__ == "__main__":
    run_backtest()
