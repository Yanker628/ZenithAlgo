#!/usr/bin/env python3
"""测试完整的engine数据流到dashboard回调"""
import asyncio
import logging
from strategies.market_maker.main import MarketMakerEngine

logging.basicConfig(level=logging.INFO)

callback_count = 0

def test_callback(data):
    global callback_count
    callback_count += 1
    if callback_count <= 3:  # 只打印前3次
        print(f"\n✅ 回调被触发 #{callback_count}:")
        print(f"   Symbol: {data['symbol']}")
        print(f"   Oracle Price: {data['ref_price']}")
        print(f"   My Bid/Ask: {data['bid']:.4f} / {data['ask']:.4f}")
        print(f"   Spread: {data['spread_pct']:.3f}%")

async def main():
    print("="*60)
    print("测试Engine数据流到回调")
    print("="*60)
    
    symbols = ['SOL/USDT']
    engine = MarketMakerEngine(symbols, dry_run=True)
    
    # 设置回调
    engine.suppress_logs = True
    engine.on_tick_callback = test_callback
    
    print("\n启动引擎...")
    engine_task = asyncio.create_task(engine.start())
    
    # 等待20秒让数据流稳定
    print("等待20秒让数据流稳定...\n")
    await asyncio.sleep(20)
    
    print(f"\n总共收到 {callback_count} 次回调")
    
    if callback_count > 0:
        print("✅ 测试成功！数据流正常")
    else:
        print("❌ 测试失败！没有收到回调")
    
    # 清理
    engine.stop()
    engine_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
