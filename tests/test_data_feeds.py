#!/usr/bin/env python
"""
验证脚本 - 测试所有数据源是否正常工作
"""
import asyncio
import logging
from strategies.market_maker.core.oracle import MultiSourceOracle
from strategies.market_maker.gateways.mexc_ws import MexcWebsocketClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_oracle():
    """测试 Oracle 数据源"""
    print("\n" + "="*50)
    print("测试 1: Oracle 数据源")
    print("="*50)
    
    symbols = ['BTC/USDT', 'ETH/USDT']
    oracle = MultiSourceOracle(symbols)
    
    # 启动 Oracle
    oracle_task = asyncio.create_task(oracle.start())
    
    # 等待数据
    await asyncio.sleep(5)
    
    # 检查数据
    for sym in symbols:
        price_data = oracle.get_price(sym)
        if price_data:
            print(f"✅ {sym}: ${price_data['mid']:.2f} (Bid: {price_data['bid']:.2f}, Ask: {price_data['ask']:.2f})")
        else:
            print(f"❌ {sym}: No data")
    
    # 停止
    oracle.running = False
    await oracle.close()
    oracle_task.cancel()
    try:
        await oracle_task
    except asyncio.CancelledError:
        pass
    
    return True

async def test_mexc_ws():
    """测试 MEXC WebSocket/REST 数据源"""
    print("\n" + "="*50)
    print("测试 2: MEXC 数据源")
    print("="*50)
    
    symbols = ['BTC/USDT', 'ETH/USDT']
    mexc_ws = MexcWebsocketClient(symbols)
    
    # 启动连接
    ws_task = asyncio.create_task(mexc_ws.connect())
    
    # 等待数据
    await asyncio.sleep(5)
    
    # 检查数据
    for sym in symbols:
        ob = mexc_ws.get_orderbook(sym)
        if ob and ob.get('bids') and ob.get('asks'):
            bid = ob['bids'][0][0]
            ask = ob['asks'][0][0]
            spread = (ask - bid) / bid * 100
            print(f"✅ {sym}: Bid={bid:.2f}, Ask={ask:.2f}, Spread={spread:.3f}%")
        else:
            print(f"❌ {sym}: No orderbook data")
    
    # 停止
    mexc_ws.running = False
    ws_task.cancel()
    try:
        await ws_task
    except asyncio.CancelledError:
        pass
    
    return True

async def main():
    """运行所有测试"""
    print("\n🚀 ZenithAlgo 数据源验证测试")
    print("="*50)
    
    try:
        # 测试 Oracle
        oracle_ok = await test_oracle()
        
        # 测试 MEXC
        mexc_ok = await test_mexc_ws()
        
        # 总结
        print("\n" + "="*50)
        print("📊 测试总结")
        print("="*50)
        print(f"Oracle 数据源: {'✅ 通过' if oracle_ok else '❌ 失败'}")
        print(f"MEXC 数据源: {'✅ 通过' if mexc_ok else '❌ 失败'}")
        
        if oracle_ok and mexc_ok:
            print("\n🎉 所有测试通过!数据获取正常!")
            return 0
        else:
            print("\n⚠️ 部分测试失败,请检查日志")
            return 1
            
    except Exception as e:
        print(f"\n❌ 测试过程出错: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
