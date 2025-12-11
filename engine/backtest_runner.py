from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from broker.backtest import BacktestBroker
from market.models import OrderSignal
from risk.manager import RiskManager
from strategy.simple_ma import SimpleMAStrategy
from utils.config_loader import load_config
from utils.data_loader import HistoricalDataLoader
from utils.logging import setup_logger
from utils.pnl import compute_unrealized_pnl
from utils.metrics import compute_metrics
from utils.plotter import plot_drawdown, plot_equity_curve, plot_return_hist


def parse_iso(val: str) -> datetime:
    return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_backtest_summary(broker: BacktestBroker, last_prices: Dict[str, float]) -> dict:
    unrealized = compute_unrealized_pnl(broker.positions, last_prices)
    return {
        "realized_pnl": broker.realized_pnl_all,
        "final_unrealized": unrealized,
        "cash": broker.cash,
        "positions": {s: {"qty": p.qty, "avg_price": p.avg_price} for s, p in broker.positions.items()},
    }


def run_backtest(cfg_path: str = "config/config.yml", cfg_obj=None):
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
    ticks = loader.candle_to_ticks(candles)

    strat = SimpleMAStrategy(
        short_window=int(
            bt_cfg.get("short_window")
            or bt_cfg.get("strategy", {}).get("short_window")
            or getattr(cfg.strategy, "short_window", 0)
        ),
        long_window=int(
            bt_cfg.get("long_window")
            or bt_cfg.get("strategy", {}).get("long_window")
            or getattr(cfg.strategy, "long_window", 0)
        ),
        min_ma_diff=float(
            bt_cfg.get("min_ma_diff")
            or bt_cfg.get("strategy", {}).get("min_ma_diff", 0.0)
            or getattr(cfg.strategy, "min_ma_diff", 0.0)
        ),
        cooldown_secs=int(
            bt_cfg.get("cooldown_secs")
            or bt_cfg.get("strategy", {}).get("cooldown_secs", 0)
            or getattr(cfg.strategy, "cooldown_secs", 0)
        ),
    )
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

    last_ts = None
    current_day = None
    day_start_equity = equity_base
    for tick in ticks:
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

        # 当前持仓信息，用于仓位约束
        pos = broker.get_position(tick.symbol)

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

        filtered = risk.filter_signals(signals)
        if not filtered:
            continue

        for sig in filtered:
            sig.price = tick.price
            # 仓位/下单规模约束：按 position_pct 或 trade_notional 限制下单数量
            price = tick.price
            if price <= 0:
                continue
            sizing_cfg = bt_cfg.get("sizing", {}) if isinstance(bt_cfg, dict) else {}
            max_position_pct = sizing_cfg.get("position_pct")
            trade_notional = sizing_cfg.get("trade_notional")

            max_qty_by_pos = None
            if max_position_pct is not None and sig.side == "buy":
                max_notional = equity_base * float(max_position_pct)
                current_notional = abs(pos.qty * price) if pos else 0.0
                remaining_notional = max(0.0, max_notional - current_notional)
                max_qty_by_pos = remaining_notional / price if price > 0 else 0.0

            max_qty_by_trade = None
            if trade_notional is not None:
                max_qty_by_trade = float(trade_notional) / price if price > 0 else 0.0

            target_qty = sig.qty
            # 卖单优先确保能平仓：如果有持仓，按持仓数量上限
            if sig.side == "sell" and pos and pos.qty > 0:
                target_qty = min(target_qty, pos.qty)
            if max_qty_by_pos is not None:
                target_qty = min(target_qty, max_qty_by_pos)
            if max_qty_by_trade is not None:
                target_qty = min(target_qty, max_qty_by_trade)

            if target_qty <= 0:
                continue

            sig.qty = target_qty
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
    # 绘图输出，允许跳过（用于批量/扫描）
    skip_plots = bool(bt_cfg.get("skip_plots", False)) if isinstance(bt_cfg, dict) else False
    if not skip_plots:
        symbol = bt_cfg.get("symbol", cfg.symbol)
        interval = bt_cfg.get("interval", cfg.timeframe)
        run_ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        plots_dir = Path("plots")
        equity_path = plots_dir / f"{symbol}_{interval}_{run_ts}_equity.png"
        drawdown_path = plots_dir / f"{symbol}_{interval}_{run_ts}_drawdown.png"
        hist_path = plots_dir / f"{symbol}_{interval}_{run_ts}_return_hist.png"
        try:
            plot_equity_curve(broker.equity_curve, str(equity_path))
            plot_drawdown(broker.equity_curve, str(drawdown_path))
            plot_return_hist(broker.equity_curve, str(hist_path))
            logger.info(
                f"Saved plots: equity={equity_path}, drawdown={drawdown_path}, return_hist={hist_path}"
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Plotting failed: {exc}")

    logger.info(f"Backtest summary: {summary}")
    return summary


if __name__ == "__main__":
    run_backtest()
