#!/bin/bash

# test_full.sh - 全量功能验证脚本
# 该脚本会自动：
# 1. 启动完整的 RaaS 环境
# 2. 运行 M7 数据一致性检查 (verify_alignment.py)
# 3. 运行 RaaS 端到端集成测试 (test_raas_integration.py)
# 4. 报告由于和停止环境

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}     ZenithAlgo Full System Verification      ${NC}"
echo -e "${BLUE}==============================================${NC}"

# 0. 预清理
echo -e "\n${GREEN}[Step 0] Cleaning up previous state...${NC}"
"$PROJECT_ROOT/scripts/stop.sh"
sleep 2

# 1. 启动环境
echo -e "\n${GREEN}[Step 1] Booting up System...${NC}"
"$PROJECT_ROOT/scripts/start.sh"

# 给一点时间让服务完全就绪
sleep 5

TEST_FAILED=0

# 2. 运行 M7 验证
echo -e "\n${GREEN}[Step 2] Running M7 Data Alignment Verification...${NC}"
cd "$PROJECT_ROOT/backend/app/engine"
if uv run python ../../scripts/verify_alignment.py; then
    echo -e "${GREEN}>>> M7 Verification PASSED${NC}"
else
    echo -e "${RED}>>> M7 Verification FAILED${NC}"
    TEST_FAILED=1
fi

# 3. 运行 RaaS 集成测试
echo -e "\n${GREEN}[Step 3] Running RaaS E2E Integration Test...${NC}"
# 注意：集成测试会模拟客户端 WebSocket 连接
if uv run python ../../scripts/test_raas_integration.py; then
    echo -e "${GREEN}>>> RaaS Integration Test PASSED${NC}"
else
    echo -e "${RED}>>> RaaS Integration Test FAILED${NC}"
    TEST_FAILED=1
fi

# 4. 停止环境
echo -e "\n${GREEN}[Step 4] Shutting down...${NC}"
"$PROJECT_ROOT/scripts/stop.sh"

echo -e "\n${BLUE}==============================================${NC}"
if [ $TEST_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ ALL TESTS PASSED! System is ready for shipping.${NC}"
    exit 0
else
    echo -e "${RED}❌ SOME TESTS FAILED. Please check logs.${NC}"
    exit 1
fi
