#!/usr/bin/env python3
"""直接测试MEXC REST API"""
import asyncio
import ccxt.async_support as ccxt

async def main():
    print("测试MEXC REST API订单簿获取")
    
    exchange = ccxt.mexc({'enableRateLimit': True})
    
    try:
        print("获取 SOL/USDT 订单簿...")
        ob = await exchange.fetch_order_book('SOL/USDT', limit=5)
        
        print(f"✅ 成功!")
        print(f"Bid: {ob['bids'][0]}")
        print(f"Ask: {ob['asks'][0]}")
        
    except Exception as e:
        print(f"❌ 失败: {e}")
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
