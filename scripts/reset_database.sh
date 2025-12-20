#!/bin/bash
# 数据库完全重置脚本
# 用于开发阶段清理所有数据并重建

echo "🔄 重置 PostgreSQL 数据库..."

# 1. 停止并删除容器
docker-compose down

# 2. 删除数据卷（这会删除所有数据）
docker volume rm zenithalgo_postgres_data 2>/dev/null || true

# 3. 重新启动
docker-compose up -d postgres

# 4. 等待数据库启动
echo "⏳ 等待数据库启动..."
sleep 3

# 5. 创建数据库结构
echo "📊 创建数据库表..."
docker-compose exec -T postgres psql -U zenith -d zenithalgo < backend/database/schema.sql

echo "✅ 数据库已重置！"
echo "💡 提示：现在可以重新导入数据"
