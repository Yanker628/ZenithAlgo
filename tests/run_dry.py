import asyncio
import sys
import os
import logging

# Add project root to path
sys.path.append(os.getcwd())

from strategies.market_maker.main import MarketMakerEngine

async def main():
    print("🚀 Starting Dry Run Test (15s)...")
    target_symbols = ['ETH/USDT', 'SOL/USDT']
    engine = MarketMakerEngine(target_symbols, dry_run=True)
    
    # Start engine in a task
    task = asyncio.create_task(engine.start())
    
    # Wait 15s
    await asyncio.sleep(15)
    
    print("🛑 Stopping Engine...")
    engine.stop()
    
    try:
        await asyncio.wait_for(task, timeout=5)
    except asyncio.TimeoutError:
        print("⚠️ Engine stop timed out")
    except Exception as e:
        print(f"⚠️ Engine task error: {e}")
        
    print("✅ Dry Run Completed")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
