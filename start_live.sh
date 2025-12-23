#!/bin/bash

# MEXC做市策略实盘启动脚本
# 使用方法：chmod +x start_live.sh && ./start_live.sh

echo "=========================================="
echo "🚨 MEXC做市策略 - 实盘模式"
echo "=========================================="
echo ""

# 检查API密钥
if [ ! -f "config/.env" ]; then
    echo "❌ 错误：未找到 config/.env 文件"
    echo "请先配置MEXC API密钥"
    exit 1
fi

# 显示配置
echo "📋 当前配置："
echo "  - 币种：SOL/USDT（单个币种测试）"
echo "  - 价差范围：0.005% - 0.03%"
echo "  - 订单大小：5% USDT余额"
echo ""

# 安全确认
echo "⚠️  实盘风险提示："
echo "  1. 这是真实交易，会产生盈亏"
echo "  2. 建议初始资金 < $100"
echo "  3. 请密切监控运行状态"
echo "  4. 随时可以 Ctrl+C 停止"
echo ""

read -p "确认开始实盘？(输入 YES 继续): " confirm

if [ "$confirm" != "YES" ]; then
    echo "❌ 已取消"
    exit 0
fi

echo ""
echo "🚀 启动中..."
echo ""

# 启动实盘（指定SOL/USDT单个币种）
uv run python -m strategies.market_maker.dashboard --live --symbol "XRP/USDT"

echo ""
echo "✅ 已停止"
