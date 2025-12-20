#!/bin/bash
# 清理废数据但保留数据库结构

echo "🧹 清理数据库废数据..."

# 删除所有 trades
echo "  - 清理 trades 表..."
docker-compose exec -T postgres psql -U zenith -d zenithalgo -c "DELETE FROM trades;"

# 删除所有 equity_curves
echo "  - 清理 equity_curves 表..."
docker-compose exec -T postgres psql -U zenith -d zenithalgo -c "DELETE FROM equity_curves;"

# 删除所有 backtests
echo "  - 清理 backtests 表..."
docker-compose exec -T postgres psql -U zenith -d zenithalgo -c "DELETE FROM backtests;"

# 重置序列
echo "  - 重置 ID 序列..."
docker-compose exec -T postgres psql -U zenith -d zenithalgo -c "ALTER SEQUENCE backtests_id_seq RESTART WITH 1;"

echo "✅ 数据已清理！"
echo "📊 当前数据："
docker-compose exec -T postgres psql -U zenith -d zenithalgo -c "
  SELECT 'backtests' as table, COUNT(*) as count FROM backtests
  UNION ALL
  SELECT 'equity_curves', COUNT(*) FROM equity_curves
  UNION ALL
  SELECT 'trades', COUNT(*) FROM trades;
"
