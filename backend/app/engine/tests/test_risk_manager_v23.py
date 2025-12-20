from __future__ import annotations

from zenith.common.models.models import OrderSignal
from zenith.strategies.risk.manager import RiskManager
from zenith.common.config.config_loader import RiskConfig


def test_risk_manager_not_mutate_input_signal_when_clipping_pct_fallback():
    risk = RiskManager(RiskConfig(max_position_pct=0.3, max_daily_loss_pct=0.05), suppress_warnings=True)
    original = OrderSignal(symbol="BTCUSDT", side="buy", qty=0.5, reason="t")
    out = risk.filter_signals([original])
    assert out[0].qty == 0.3
    assert original.qty == 0.5


def test_risk_manager_not_mutate_input_signal_when_clipping_notional():
    risk = RiskManager(
        RiskConfig(max_position_pct=0.2, max_daily_loss_pct=0.05),
        suppress_warnings=True,
        equity_base=1000.0,
    )
    original = OrderSignal(symbol="BTCUSDT", side="buy", qty=5.0, reason="t", price=100.0)
    out = risk.filter_signals([original])
    assert abs(out[0].qty - 2.0) < 1e-9
    assert abs(original.qty - 5.0) < 1e-9


def test_risk_manager_daily_block_and_reset():
    risk = RiskManager(RiskConfig(max_position_pct=0.3, max_daily_loss_pct=0.05), suppress_warnings=True)
    sig = OrderSignal(symbol="BTCUSDT", side="buy", qty=0.1, reason="t")
    assert risk.filter_signals([sig])
    risk.set_daily_pnl(-0.1)
    assert risk.filter_signals([sig]) == []
    risk.reset_daily_state(log=False)
    assert risk.filter_signals([sig])
