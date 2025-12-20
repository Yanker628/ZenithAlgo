from __future__ import annotations
import logging
from typing import List

from zenith.common.config.schema import RiskConfig
from zenith.common.models.models import OrderSignal

class RiskManager:
    """策略层风控管理器。
    
    职责：
    1. 信号过滤与修剪 (Signal Filtration & Clipping)
    2. 每日亏损限制 (Daily Loss Limit)
    3. 仓位大小限制 (Position Sizing Limit)
    """

    def __init__(self, cfg: RiskConfig, suppress_warnings: bool = False, equity_base: float = 0.0):
        self.cfg = cfg
        self.suppress_warnings = suppress_warnings
        self.equity_base = float(equity_base)
        self.logger = logging.getLogger("RiskManager")
        
        # State
        self._daily_pnl = 0.0

    def set_daily_pnl(self, pnl: float):
        """外部注入当前累计日内 PnL (通常由 Engine/Broker 计算后传入)。"""
        self._daily_pnl = pnl

    def reset_daily_state(self, log: bool = True):
        if log and not self.suppress_warnings:
             self.logger.info("Resetting daily risk state.")
        self._daily_pnl = 0.0

    def filter_signals(self, signals: List[OrderSignal]) -> List[OrderSignal]:
        """对生成的信号进行风控检查。
        
        规则：
        1. 如果日内亏损 > max_daily_loss_pct，阻断所有开仓信号。
        2. 检查单笔仓位大小，超过 max_position_pct 则进行裁剪 (Clipping)。
        """
        if not signals:
            return []
            
        # 1. Check Daily Loss
        current_loss_pct = 0.0
        if self.equity_base > 0:
            current_loss_pct = -self._daily_pnl / self.equity_base
        else:
            # Fallback: treat pnl as raw ratio if base is 0
            current_loss_pct = -self._daily_pnl

        if current_loss_pct > self.cfg.max_daily_loss_pct:
            if not self.suppress_warnings:
                self.logger.warning(f"Daily loss limit hit: {current_loss_pct:.2%} > {self.cfg.max_daily_loss_pct:.2%}. Blocking signals.")
            return []

        # 2. Check & Clip Position Size
        filtered = []
        for sig in signals:
            max_qty = float('inf')
            
            if self.equity_base > 0 and sig.price and sig.price > 0:
                # Value based limit
                max_val = self.equity_base * self.cfg.max_position_pct
                max_qty = max_val / sig.price
            else:
                # Fallback: Clip qty directly against max_position_pct
                max_qty = self.cfg.max_position_pct
            
            final_qty = sig.qty
            if final_qty > max_qty:
                if not self.suppress_warnings:
                    self.logger.warning(f"Signal qty {sig.qty} clipped to {max_qty} by risk limit.")
                final_qty = max_qty
                
            if abs(final_qty - sig.qty) > 1e-9:
                # OrderSignal is a dataclass, use dataclasses.replace
                from dataclasses import replace
                new_sig = replace(sig, qty=final_qty)
                filtered.append(new_sig)
            else:
                filtered.append(sig)

        return filtered
