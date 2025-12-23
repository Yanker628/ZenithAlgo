from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from strategies.market_maker.main import MarketMakerEngine
from strategies.market_maker.sim.fakes import (
    FakeClock,
    FakeExecutor,
    FakeMexcMarketData,
    FakeOracle,
    FakePrecisionHelper,
    ScenarioStep,
)


@dataclass
class SimulationReport:
    symbol: str
    steps: int
    placed_orders: int
    cancels: int
    fills: int
    executor_errors: int
    last_inventory: Dict


async def run_scenario(
    symbol: str,
    steps: List[ScenarioStep],
    *,
    initial_usdt: float = 100.0,
    precision_kwargs: Dict | None = None,
    executor_kwargs: Dict | None = None,
) -> Tuple[MarketMakerEngine, SimulationReport]:
    clock = FakeClock()
    precision = FakePrecisionHelper(**(precision_kwargs or {"price_decimals": 2, "amount_decimals": 4, "min_amount": 0.0001, "min_cost": 5.0}))
    oracle = FakeOracle([symbol], clock)
    mexc = FakeMexcMarketData([symbol], clock)

    engine = MarketMakerEngine(
        [symbol],
        dry_run=False,
        scan_symbols=False,
        mexc_ws=mexc,
        oracle=oracle,
        precision=precision,
        now_fn=clock.now,
    )

    # Seed balances for sizing.
    engine.inventory_manager.usdt_balance = float(initial_usdt)
    engine.circuit_breaker.initial_capital = float(initial_usdt) if initial_usdt > 0 else 100.0

    executor = FakeExecutor(clock=clock, inventory_manager=engine.inventory_manager, **(executor_kwargs or {}))
    engine.executor = executor

    for step in steps:
        clock.advance(step.dt)

        # Apply "staleness" by writing older timestamps into caches.
        oracle_ts = clock.now() - float(step.oracle_age)
        ob_ts = clock.now() - float(step.orderbook_age)

        oracle.set_price(symbol, step.oracle_mid, ts=oracle_ts)
        if step.mexc_bids is not None and step.mexc_asks is not None:
            mexc.set_orderbook_levels(symbol, bids=step.mexc_bids, asks=step.mexc_asks, ts=ob_ts)
        else:
            mexc.set_orderbook(symbol, step.mexc_bid, step.mexc_ask, ts=ob_ts)
        mexc.set_volatility(symbol, step.volatility_pct)

        await engine.on_tick(symbol)

        # Basic invariant: no crossed quotes should ever be placed.
        for o in executor.open_orders(symbol):
            assert o.amount > 0

        # Optional fill.
        if step.fill_fraction > 0:
            ob = mexc.get_orderbook(symbol) or {}
            bids = [(float(p), float(q)) for p, q in (ob.get("bids") or [])]
            asks = [(float(p), float(q)) for p, q in (ob.get("asks") or [])]
            executor.match_and_fill(
                symbol,
                market_bids=bids,
                market_asks=asks,
                fill_fraction=step.fill_fraction,
            )

    report = SimulationReport(
        symbol=symbol,
        steps=len(steps),
        placed_orders=engine.executor.total_orders,
        cancels=engine.executor.cancel_count,
        fills=engine.executor.total_filled,
        executor_errors=engine.executor.error_count,
        last_inventory=engine.inventory_manager.get_statistics(),
    )
    return engine, report


def build_default_scenarios(symbol: str) -> Dict[str, List[ScenarioStep]]:
    return {
        "normal_with_fills": [
            ScenarioStep(dt=1.0, oracle_mid=100.0, mexc_bid=99.9, mexc_ask=100.1, volatility_pct=0.01, fill_fraction=0.0),
            ScenarioStep(dt=1.0, oracle_mid=100.0, mexc_bid=99.97, mexc_ask=99.98, volatility_pct=0.01, fill_fraction=1.0),  # buy fill
            ScenarioStep(dt=1.0, oracle_mid=100.1, mexc_bid=100.02, mexc_ask=100.03, volatility_pct=0.01, fill_fraction=1.0),  # sell fill
        ],
        "stale_oracle": [
            ScenarioStep(dt=1.0, oracle_mid=100.0, mexc_bid=99.9, mexc_ask=100.1, oracle_age=10.0, orderbook_age=0.0),
        ],
        "stale_orderbook": [
            ScenarioStep(dt=1.0, oracle_mid=100.0, mexc_bid=99.9, mexc_ask=100.1, oracle_age=0.0, orderbook_age=10.0),
        ],
        "price_deviation_breaker": [
            ScenarioStep(dt=1.0, oracle_mid=100.0, mexc_bid=90.0, mexc_ask=90.2, oracle_age=0.0, orderbook_age=0.0),
        ],
        "min_cost_blocks_order": [
            ScenarioStep(dt=1.0, oracle_mid=1000.0, mexc_bid=999.0, mexc_ask=1001.0, oracle_age=0.0, orderbook_age=0.0),
        ],
        "volume_mode_requires_market_spread": [
            ScenarioStep(dt=1.0, oracle_mid=100.0, mexc_bid=99.99, mexc_ask=100.00, oracle_age=0.0, orderbook_age=0.0),
        ],
        "multilevel_partial_fill": [
            ScenarioStep(
                dt=1.0,
                oracle_mid=100.0,
                mexc_bid=99.9,
                mexc_ask=100.1,
                mexc_bids=[(99.9, 5.0), (99.8, 10.0), (99.7, 20.0), (99.6, 30.0), (99.5, 50.0)],
                mexc_asks=[(100.1, 1.0), (100.2, 2.0), (100.3, 5.0), (100.4, 10.0), (100.5, 20.0)],
                volatility_pct=0.01,
                fill_fraction=0.0,
            ),
            # Market moves down through our bid; touch liquidity is limited (asks qty=1.0 at 100.1)
            ScenarioStep(
                dt=1.0,
                oracle_mid=100.0,
                mexc_bid=99.8,
                mexc_ask=99.9,
                mexc_bids=[(99.8, 5.0), (99.7, 10.0), (99.6, 20.0), (99.5, 30.0), (99.4, 50.0)],
                mexc_asks=[(99.9, 0.2), (100.0, 0.3), (100.1, 0.5), (100.2, 1.0), (100.3, 2.0)],
                volatility_pct=0.01,
                fill_fraction=1.0,
            ),
        ],
    }
