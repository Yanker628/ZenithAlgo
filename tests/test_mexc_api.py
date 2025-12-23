#!/usr/bin/env python3
"""测试MEXC API连接"""
import os
import sys
from dotenv import load_dotenv
import ccxt

# 加载环境变量
env_path = os.path.abspath("config/.env")
load_dotenv(env_path)

api_key = os.getenv("MEXC_API_KEY")
secret = os.getenv("MEXC_API_SECRET")

print("🔍 测试MEXC API连接...")
print(f"API Key: {api_key[:10]}..." if api_key else "❌ 未找到API Key")

if not api_key or not secret:
    print("❌ 错误: API密钥未配置")
    print("请在 config/.env 中配置 MEXC_API_KEY 和 MEXC_API_SECRET")
    sys.exit(1)

try:
    # 创建交易所实例
    exchange = ccxt.mexc({
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    
    print("✅ 交易所实例创建成功")
    
    # 测试：获取余额
    print("📡 测试账户余额查询...")
    balance = exchange.fetch_balance()
    
    usdt = balance.get('USDT', {}).get('free', 0)
    print(f"✅ USDT余额: {usdt}")
    
    # 测试：获取市场数据
    print("📡 测试市场数据...")
    ticker = exchange.fetch_ticker('SOL/USDT')
    print(f"✅ SOL/USDT 价格: {ticker['last']}")
    
    print("\n🎉 所有测试通过！API连接正常")
    
except ccxt.AuthenticationError as e:
    print(f"❌ 认证错误: {e}")
    print("可能原因：")
    print("  1. API Key或Secret错误")
    print("  2. API权限不足")
    print("  3. IP白名单限制")
    
except ccxt.NetworkError as e:
    print(f"❌ 网络错误: {e}")
    print("可能原因：")
    print("  1. 网络连接问题")
    print("  2. MEXC API服务器故障")
    print("  3. 防火墙/代理问题")
    
except Exception as e:
    print(f"❌ 未知错误: {e}")
    import traceback
    traceback.print_exc()
