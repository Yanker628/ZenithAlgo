import ccxt
import time
import requests

def check_network():
    print("🌍 Network Diagnosis Tool for ZenithAlgo")
    print("-" * 50)
    
    # 1. 检查公网 IP 和地理位置
    try:
        ip_info = requests.get('http://ip-api.com/json/', timeout=5).json()
        print(f"📍 Server Location: {ip_info.get('country')} ({ip_info.get('regionName')})")
        print(f"🌐 IP: {ip_info.get('query')}")
    except:
        print("⚠️ Could not fetch IP info")
    
    print("-" * 50)

    # 2. 检查 Binance Spot API
    print("Testing Binance Spot API...")
    try:
        binance = ccxt.binance()
        ticker = binance.fetch_ticker('BTC/USDT')
        print(f"✅ Binance Connect: OK (BTC Price: {ticker['last']})")
    except Exception as e:
        print(f"❌ Binance Connect: FAILED")

    print("-" * 50)

    # 3. 检查 OKX API (作为备用 Oracle)
    print("Testing OKX Spot API...")
    try:
        okx = ccxt.okx()
        ticker = okx.fetch_ticker('BTC/USDT')
        print(f"✅ OKX Connect: OK (BTC Price: {ticker['last']})")
    except Exception as e:
        print(f"❌ OKX Connect: FAILED")

    print("-" * 50)
    
    # 4. 检查 Bybit API (作为备用 Oracle)
    print("Testing Bybit Spot API...")
    try:
        bybit = ccxt.bybit()
        ticker = bybit.fetch_ticker('BTC/USDT')
        print(f"✅ Bybit Connect: OK (BTC Price: {ticker['last']})")
    except Exception as e:
        print(f"❌ Bybit Connect: FAILED")

    print("-" * 50)

    # 5. 检查 MEXC Spot API
    print("Testing MEXC Spot API...")
    try:
        mexc = ccxt.mexc()
        # 即使没有 API Key 也可以获取公开时间
        time_res = mexc.fetch_time()
        print(f"✅ MEXC Rest API: OK (Ping success)")
        
        # 尝试获取行情
        ticker = mexc.fetch_ticker('BTC/USDT')
        print(f"✅ MEXC Ticker: OK (BTC Price: {ticker['last']})")
        
    except Exception as e:
        print(f"❌ MEXC Connect: FAILED")
        print(f"   Error: {e}")
        
    print("-" * 50)
    
    # 6. 检查 WebSocket 连通性
    print("Testing WebSocket Connectivity...")
    import asyncio
    import websockets
    
    async def test_ws(url, name):
        try:
            async with websockets.connect(url, close_timeout=2) as ws:
                print(f"✅ {name} WebSocket: OK (Connected)")
        except Exception as e:
            print(f"❌ {name} WebSocket: FAILED ({e})")

    async def run_ws_tests():
        # MEXC WS
        await test_ws("wss://wbs.mexc.com/ws", "MEXC")
        # OKX WS
        await test_ws("wss://ws.okx.com:8443/ws/v5/public", "OKX")
        # Binance WS (Likely to fail)
        await test_ws("wss://stream.binance.com:9443/ws", "Binance")

    # 运行异步测试
    asyncio.run(run_ws_tests())

if __name__ == "__main__":
    check_network()
