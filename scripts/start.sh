#!/bin/bash

# start.sh - 一键启动 ZenithAlgo RaaS 系统
# 用法: ./scripts/start.sh

set -e

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}>>> ZenithAlgo RaaS System Startup Initiated...${NC}"

# 0. 检查依赖
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed.${NC}"
    exit 1
fi
if ! command -v go &> /dev/null; then
    echo -e "${RED}Error: Go is not installed.${NC}"
    exit 1
fi
if ! command -v uv &> /dev/null; then
    echo -e "${RED}Error: uv (Python) is not installed.${NC}"
    exit 1
fi
if ! command -v npm &> /dev/null; then
    echo -e "${RED}Error: npm is not installed.${NC}"
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 1. 启动基础设施 (Docker: Redis + Postgres)
echo -e "${GREEN}[1/4] Starting Infrastructure (Docker)...${NC}"
cd backend
docker-compose up -d redis postgres
# 等待 DB 就绪
echo "Waiting for database to be ready..."
sleep 5
cd ..

# 2. 启动 Go Backend
echo -e "${GREEN}[2/4] Starting Go API Server...${NC}"
cd backend/app/server
# 使用 nohup 后台启动，日志重定向到 files
mkdir -p "$PROJECT_ROOT/logs"
DB_HOST=localhost DB_PORT=5432 DB_USER=user DB_PASSWORD=password DB_NAME=zenith_db REDIS_ADDR=localhost:6379 \
nohup go run cmd/server/main.go > "$PROJECT_ROOT/logs/backend.log" 2>&1 &
BACKEND_PID=$!
echo "Backend running (PID: $BACKEND_PID). Logs: logs/backend.log"
cd ../../..

# 3. 启动 Python Worker
echo -e "${GREEN}[3/4] Starting Python Worker...${NC}"
cd backend/app/engine
# 确保 venv 存在
if [ ! -d ".venv" ]; then
    uv sync
fi
REDIS_URL=redis://localhost:6379/0 \
nohup uv run python main.py worker --redis-url redis://localhost:6379/0 > "$PROJECT_ROOT/logs/worker.log" 2>&1 &
WORKER_PID=$!
echo "Worker running (PID: $WORKER_PID). Logs: logs/worker.log"
cd ../../..

# 4. 启动 Frontend
echo -e "${GREEN}[4/4] Starting Frontend (Next.js)...${NC}"
cd frontend
# 检查 node_modules
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi
nohup npm run dev > "$PROJECT_ROOT/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "Frontend running (PID: $FRONTEND_PID). Logs: logs/frontend.log"
cd ..

# 保存 PIDs 以便停止
echo "$BACKEND_PID" > "$PROJECT_ROOT/logs/backend.pid"
echo "$WORKER_PID" > "$PROJECT_ROOT/logs/worker.pid"
echo "$FRONTEND_PID" > "$PROJECT_ROOT/logs/frontend.pid"

echo -e "${BLUE}>>> System Started Successfully!${NC}"
echo -e "Frontend:  http://localhost:3000"
echo -e "Backend:   http://localhost:8080"
echo -e "Logs dir:  $PROJECT_ROOT/logs"
echo -e "(Run ./scripts/stop.sh to stop the system)"
