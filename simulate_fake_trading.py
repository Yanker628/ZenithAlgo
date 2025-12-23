import argparse
import asyncio
import json

from strategies.market_maker.sim.harness import build_default_scenarios, run_scenario


async def main():
    parser = argparse.ArgumentParser(description="Offline fake trading simulation (no network, no real orders).")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--scenario", default="normal_with_fills")
    parser.add_argument("--all", action="store_true", help="Run all built-in scenarios")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    scenarios = build_default_scenarios(args.symbol)
    scenario_names = list(scenarios.keys())

    to_run = scenario_names if args.all else [args.scenario]
    for name in to_run:
        if name not in scenarios:
            raise SystemExit(f"Unknown scenario: {name}. Available: {', '.join(scenario_names)}")

        kwargs = {}
        if name == "min_cost_blocks_order":
            kwargs = {"initial_usdt": 1.0}

        _, report = await run_scenario(args.symbol, scenarios[name], **kwargs)
        if args.json:
            payload = {"scenario": name, **report.__dict__}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"\n=== {name} ===")
            print(f"Symbol: {report.symbol}")
            print(f"Steps: {report.steps}")
            print(f"Placed orders: {report.placed_orders}")
            print(f"Cancels: {report.cancels}")
            print(f"Fills: {report.fills}")
            print(f"Executor errors: {report.executor_errors}")


if __name__ == "__main__":
    asyncio.run(main())
