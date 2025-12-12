"""风险管理与信号过滤。"""

from market.models import OrderSignal, Position
from utils.logging import setup_logger
from utils.config_loader import RiskConfig


class RiskManager:
    """风险管理器。

    Parameters
    ----------
    risk_cfg:
        风控配置（max_position_pct/max_daily_loss_pct）。
    suppress_warnings:
        是否抑制 warning 日志（回测常用）。
    equity_base:
        基准权益，用于按名义比例裁剪仓位。
    """

    def __init__(self, risk_cfg: RiskConfig, suppress_warnings: bool = False, equity_base: float | None = None):
        self.cfg = risk_cfg
        self.logger = setup_logger("risk")
        self.suppress_warnings = suppress_warnings
        self.equity_base = equity_base  # 用于名义比例裁剪

        # 当前日 PnL（你在 backtest 里是传 daily_pnl_pct，所以这里就是“百分比”）
        self.daily_pnl = 0.0

        # 持仓快照（目前你只用到 max_position_pct，先保留）
        self.positions: dict[str, Position] = {}

        # 日损风控状态
        self._daily_blocked = False        # 今天还允不允许开新仓
        self._daily_block_logged = False   # 避免重复刷 warning

    def update_position(self, pos: Position):
        """更新内部持仓快照。"""
        self.positions[pos.symbol] = pos

    def set_daily_pnl(self, pnl: float):
        """设置当日 PnL（按比例）。

        Parameters
        ----------
        pnl:
            当日 PnL 百分比，例如 -0.03 表示亏损 3%。
        """
        self.daily_pnl = pnl
        # 有配置 max_daily_loss_pct 才生效
        max_loss = getattr(self.cfg, "max_daily_loss_pct", None)
        if max_loss is not None and pnl <= -max_loss:
            if not self._daily_blocked:
                self._daily_blocked = True
                if not self._daily_block_logged and not self.suppress_warnings:
                    self.logger.warning("Daily loss limit reached, block all new signals.")
                    self._daily_block_logged = True

    def reset_daily_state(self, log: bool = True):
        """跨日重置风控状态。"""
        self.daily_pnl = 0.0
        self._daily_blocked = False
        self._daily_block_logged = False
        if log and not self.suppress_warnings:
            self.logger.info("[RISK] Daily state reset.")

    def filter_signals(self, signals: list[OrderSignal]) -> list[OrderSignal]:
        """过滤并裁剪策略信号。

        Notes
        -----
        本方法会**原地修改**传入信号的 qty（如做仓位裁剪）。
        """
        # 如果今日已经触发日损，直接静默丢弃，不再刷 warning
        if self._daily_blocked:
            return []

        result: list[OrderSignal] = []
        for sig in signals:
            max_pct = getattr(self.cfg, "max_position_pct", None)
            if max_pct is not None:
                price = getattr(sig, "price", None)
                # 优先按名义比例裁剪；若价格或基准资金缺失，则回退按数量裁剪（兼容测试）
                if price is not None and self.equity_base:
                    max_notional = self.equity_base * max_pct
                    target_notional = price * sig.qty
                    if target_notional > max_notional and price > 0:
                        clipped_qty = max_notional / price
                        self.logger.info(
                            f"Signal notional {target_notional:.4f} > {max_notional:.4f}, clip qty to {clipped_qty:.6f}"
                        )
                        sig.qty = clipped_qty
                else:
                    if sig.qty > max_pct:
                        self.logger.info(
                            f"Signal qty {sig.qty} > max_position_pct, clip to {max_pct}"
                        )
                        sig.qty = max_pct
            result.append(sig)
        return result
