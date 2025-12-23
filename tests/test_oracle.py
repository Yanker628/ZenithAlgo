#!/usr/bin/env python3
"""直接测试Oracle获取数据"""
import asyncio
import logging
from strategies.market_maker.core.oracle import MultiSourceOracle

logging.basicConfig(level=logging.INFO)

async def main():
    print("="*60)
    print("测试Oracle数据获取")
    print("="*60)
    
    symbols = ['SOL/USDT']
    oracle = MultiSourceOracle(symbols)
    
    print("\n1. 启动Oracle...")
    oracle_task = asyncio.create_task(oracle.start())
    
    print("2. 等待5秒...")
    await asyncio.sleep(5)
    
    print("\n3. 尝试获取数据...")
    for symbol in symbols:
        data = oracle.get_price(symbol)
        if data:
            print(f"   ✅ {symbol}: {data}")
        else:
            print(f"   ❌ {symbol}: 无数据")
    
    print("\n4. 再等5秒后再次尝试...")
    await asyncio.sleep(5)
    
    for symbol in symbols:
        data = oracle.get_price(symbol)
        if data:
            print(f"   ✅ {symbol}: {data}")
        else:
            print(f"   ❌ {symbol}: 无数据")
    
    # 清理
    oracle_task.cancel()
    await oracle.close()
    print("\n完成")

if __name__ == "__main__":
    asyncio.run(main())
