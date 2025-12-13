from datetime import datetime, timezone

from shared.models.models import OrderSignal, Tick
from algo.risk.manager import RiskManager
from algo.strategy.simple_ma import SimpleMAStrategy
from shared.config.config_loader import RiskConfig


def test_simple_ma_generates_signals_when_crossing():
    strat = SimpleMAStrategy(short_window=2, long_window=3, min_ma_diff=0.0, cooldown_secs=0)
    prices = [10, 11, 12, 11, 9]  # 短上穿后下穿
    signals = []
    for p in prices:
        signals.extend(
            strat.on_tick(
                Tick(symbol="BTCUSDT", price=p, ts=datetime.now(timezone.utc))
            )
        )

    sides = [s.side for s in signals]
    assert "buy" in sides
    assert "sell" in sides


def test_risk_manager_clips_and_blocks():
    risk = RiskManager(RiskConfig(max_position_pct=0.3, max_daily_loss_pct=0.05))

    original = OrderSignal(symbol="BTCUSDT", side="buy", qty=0.5, reason="test")
    oversized = [original]
    result = risk.filter_signals(oversized)
    assert result[0].qty == 0.3
    # 不应修改原对象
    assert original.qty == 0.5

    risk.set_daily_pnl(-0.1)
    blocked = risk.filter_signals(oversized)
    assert blocked == []
