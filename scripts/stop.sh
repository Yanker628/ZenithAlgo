#!/bin/bash

# stop.sh - 一键停止 ZenithAlgo RaaS 系统
# 用法: ./scripts/stop.sh

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo -e "${BLUE}>>> Stopping ZenithAlgo System...${NC}"

# Helper function to kill process by pid file
kill_process() {
    local name=$1
    local pid_file="$PROJECT_ROOT/logs/$name.pid"
    
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p $pid > /dev/null; then
            echo "Stopping $name (PID: $pid)..."
            kill $pid || kill -9 $pid
        else
            echo "$name process (PID: $pid) not found, maybe already stopped."
        fi
        rm "$pid_file"
    else
        echo "No PID file found for $name, attempting pkill..."
        # Fallback to pkill if pid file missing
        if [ "$name" == "backend" ]; then
             pkill -f "go run cmd/server/main.go" || true
        elif [ "$name" == "worker" ]; then
             pkill -f "python main.py worker" || true
        elif [ "$name" == "frontend" ]; then
             # Next.js dev server usually runs `next-server` or `next`
             pkill -f "next-server" || pkill -f "next dev" || true
        fi
    fi
}

# 1. Stop Frontend
kill_process "frontend"

# 2. Stop Worker
kill_process "worker"

# 3. Stop Backend
kill_process "backend"

# 4. Stop Infrastructure
echo -e "${GREEN}Stopping Docker Containers...${NC}"
cd "$PROJECT_ROOT/backend"
# 尝试停止并移除相关容器，防止端口占用
docker-compose down --remove-orphans || true
# 额外清理可能残留的重名容器
docker rm -f backend-postgres-1 backend-redis-1 zenith-pg-persist zenith-redis-persist 2>/dev/null || true

echo -e "${BLUE}>>> System Stopped.${NC}"
