import sys
import logging
import time
from engine.optimization_engine import OptimizationEngine

# Setup basic logging to stdout
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s [%(levelname)s] %(name)s - %(message)s')

def main():
    print("Starting Volatility Sweep (Ferrari Mode)...")
    start_time = time.time()
    
    engine = OptimizationEngine(cfg_path="config/config_volatility_sweep.yml")
    result = engine.run()
    
    elapsed = time.time() - start_time
    print(f"Sweep Finished in {elapsed:.2f} seconds.")
    
    summary = result.summary
    if summary and "results" in summary:
        symbols = summary["results"].keys()
        for sym in symbols:
            count = len(summary["results"][sym])
            print(f"Symbol: {sym}, Top {count} results found.")
            if count > 0:
                best = summary["results"][sym][0]
                print(f"Best Params: {best['params']}")
                print(f"Best Score: {best['score']:.4f}")
                print(f"Best Metrics: {best['metrics']}")

if __name__ == "__main__":
    main()
