import asyncio

from strategies.market_maker.sim.harness import build_default_scenarios, run_scenario


def test_fake_trading_normal_with_fills():
    scenarios = build_default_scenarios("BTC/USDT")
    _, report = asyncio.run(run_scenario("BTC/USDT", scenarios["normal_with_fills"]))
    assert report.placed_orders > 0
    assert report.fills >= 1


def test_fake_trading_stale_oracle_blocks_orders():
    scenarios = build_default_scenarios("BTC/USDT")
    _, report = asyncio.run(run_scenario("BTC/USDT", scenarios["stale_oracle"]))
    assert report.placed_orders == 0


def test_fake_trading_stale_orderbook_blocks_orders():
    scenarios = build_default_scenarios("BTC/USDT")
    _, report = asyncio.run(run_scenario("BTC/USDT", scenarios["stale_orderbook"]))
    assert report.placed_orders == 0


def test_fake_trading_price_deviation_breaker_blocks_orders():
    scenarios = build_default_scenarios("BTC/USDT")
    _, report = asyncio.run(run_scenario("BTC/USDT", scenarios["price_deviation_breaker"]))
    assert report.placed_orders == 0


def test_fake_trading_min_cost_blocks_orders_when_balance_too_small():
    scenarios = build_default_scenarios("BTC/USDT")
    _, report = asyncio.run(
        run_scenario(
            "BTC/USDT",
            scenarios["min_cost_blocks_order"],
            initial_usdt=1.0,
            precision_kwargs={"price_decimals": 2, "amount_decimals": 4, "min_amount": 0.0001, "min_cost": 5.0},
        )
    )
    assert report.placed_orders == 0


def test_fake_trading_volume_mode_market_spread_gate():
    import os

    scenarios = build_default_scenarios("BTC/USDT")
    os.environ["MM_MODE"] = "volume"
    os.environ["MM_MIN_MARKET_SPREAD_PCT"] = "0.05"
    try:
        _, report = asyncio.run(run_scenario("BTC/USDT", scenarios["volume_mode_requires_market_spread"]))
        assert report.placed_orders == 0
    finally:
        os.environ.pop("MM_MODE", None)
        os.environ.pop("MM_MIN_MARKET_SPREAD_PCT", None)


def test_fake_trading_multilevel_depth_partial_fill_updates_inventory():
    scenarios = build_default_scenarios("BTC/USDT")
    engine, report = asyncio.run(run_scenario("BTC/USDT", scenarios["multilevel_partial_fill"]))
    stats = engine.inventory_manager.get_statistics()
    qty = stats["positions"]["BTC/USDT"]["quantity"]
    # With depth-limited fill model, we should get a small positive fill (partial)
    assert qty > 0


def test_fake_trading_cancel_storm_triggers_rate_limit_errors():
    import os

    # Force frequent refresh and tight loop to surface cancel storms early.
    os.environ["MM_REFRESH_THRESHOLD"] = "0.0"
    try:
        steps = []
        mid = 100.0
        from strategies.market_maker.sim.fakes import ScenarioStep
        for i in range(50):
            # Small oscillation causes bid/ask to change and refresh every tick
            px = mid + (0.01 if i % 2 == 0 else -0.01)
            steps.append(
                # dt=0.1s -> 10 ticks/s; cancel limit below that will reject
                ScenarioStep(
                    dt=0.1,
                    oracle_mid=px,
                    mexc_bid=px - 0.05,
                    mexc_ask=px + 0.05,
                    volatility_pct=0.01,
                    fill_fraction=0.0,
                )
            )

        _, report = asyncio.run(
            run_scenario(
                "BTC/USDT",
                steps,
                executor_kwargs={
                    "max_cancel_per_sec": 2,   # low cancel capacity
                    "max_create_per_sec": 4,   # low create capacity
                    "cancel_latency_s": 0.2,
                    "place_latency_s": 0.2,
                },
            )
        )
        assert report.executor_errors > 0
    finally:
        os.environ.pop("MM_REFRESH_THRESHOLD", None)
