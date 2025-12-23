#!/usr/bin/env python3
"""
简单实盘测试 - 不使用Dashboard，直接在控制台输出
用于调试数据流问题
"""
import asyncio
import logging
import sys
from strategies.market_maker.main import MarketMakerEngine

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

async def main():
    print("="*60)
    print("🚀 ZenithAlgo做市策略 - 简单实盘测试")
    print("="*60)
    print()
    
    # 创建引擎(实盘模式)
    symbols = ['SOL/USDT']
    engine = MarketMakerEngine(symbols, dry_run=False)
    
    # 启动引擎
    try:
        # 不使用 engine.start()，手动启动各个组件
        print("📡 初始化中...")
        await engine.executor.initialize()
        
        print("💰 获取初始余额...")
        await engine.inventory_manager.update_from_exchange()
        stats = engine.inventory_manager.get_statistics()
        print(f"   USDT: {stats['usdt_balance']}")
        print(f"   SOL: {stats['positions'].get('SOL/USDT', {}).get('quantity', 0)}")
        print()
        
        print("🔍 连接数据源...")
        # 启动Oracle
        oracle_task = asyncio.create_task(engine.oracle.start())
        
        # 等待数据
        print("⏳等待数据...")
        await asyncio.sleep(5)
        
        # 尝试获取一次报价
        print("📊 获取市场数据...")
        symbol = 'SOL/USDT'
        
        # 检查Oracle数据
        ref_price = engine.oracle.get_reference_price(symbol)
        print(f"   Oracle价格: {ref_price}")
        
        # 检查MEXC WebSocket数据
        if symbol in engine.mexc_ws.latest_data:
            mexc_data = engine.mexc_ws.latest_data[symbol]
            print(f"   MEXC最新价: {mexc_data.get('last', 'N/A')}")
        else:
            print("   ⚠️ MEXC WebSocket无数据")
        
        print()
        print("✅ 测试完成")
        print("如果以上数据正常，说明API和数据流都OK")
        print("问题可能出在Dashboard的数据同步上")
        
    except KeyboardInterrupt:
        print("\n⏹️ 已停止")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        engine.stop()

if __name__ == "__main__":
    asyncio.run(main())
