#!/bin/bash
# 查看数据库当前状态

echo "📊 ZenithAlgo 数据库状态"
echo "=" 

# 统计各表数据量
docker-compose exec -T postgres psql -U zenith -d zenithalgo << 'EOF'
\echo '=== 表统计 ==='
SELECT 
  'backtests' as "表名",
  COUNT(*) as "记录数",
  pg_size_pretty(pg_total_relation_size('backtests')) as "大小"
FROM backtests
UNION ALL
SELECT 
  'equity_curves',
  COUNT(*),
  pg_size_pretty(pg_total_relation_size('equity_curves'))
FROM equity_curves
UNION ALL
SELECT 
  'trades',
  COUNT(*),
  pg_size_pretty(pg_total_relation_size('trades'))
FROM trades;

\echo ''
\echo '=== 数据库总大小 ==='
SELECT pg_size_pretty(pg_database_size('zenithalgo')) as "总大小";

\echo ''
\echo '=== 最新回测记录 (Top 5) ==='
SELECT 
  id,
  symbol,
  strategy_name,
  score,
  created_at
FROM backtests
ORDER BY created_at DESC
LIMIT 5;
EOF
