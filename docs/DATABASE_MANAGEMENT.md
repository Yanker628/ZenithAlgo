# 数据库管理指南

## 📊 数据库管理命令

### 查看数据库状态

```bash
./scripts/db_status.sh
```

显示：

- 各表记录数和大小
- 数据库总大小
- 最新的回测记录

### 清理废数据（保留结构）

```bash
./scripts/clean_data.sh
```

作用：

- 删除所有 backtests、equity_curves、trades
- 保留表结构和索引
- 重置 ID 序列

**适用场景**：开发测试后清理，但想保留数据库结构

### 完全重置数据库

```bash
./scripts/reset_database.sh
```

作用：

- 停止并删除 Docker 容器
- 删除所有数据（包括数据卷）
- 重新创建干净的数据库

**适用场景**：数据库损坏、schema 变更、彻底重来

---

## 🗄️ 开发阶段最佳实践

### 1. 分离开发和生产数据

**方案 A：使用不同数据库**

```bash
# 开发数据库
DATABASE_URL=postgresql://zenith:pass@localhost:5432/zenithalgo_dev

# 生产数据库（未来）
DATABASE_URL=postgresql://zenith:pass@server:5432/zenithalgo_prod
```

**方案 B：使用 schema 隔离**

```sql
-- 开发 schema
CREATE SCHEMA dev;
-- 生产 schema
CREATE SCHEMA prod;
```

### 2. 定期备份重要数据

**备份命令**：

```bash
# 备份整个数据库
docker-compose exec -T postgres pg_dump -U zenith zenithalgo > backups/backup_$(date +%Y%m%d).sql

# 仅备份 schema
docker-compose exec -T postgres pg_dump -U zenith --schema-only zenithalgo > backups/schema.sql

# 仅备份数据
docker-compose exec -T postgres pg_dump -U zenith --data-only zenithalgo > backups/data.sql
```

**恢复命令**：

```bash
# 从备份恢复
docker-compose exec -T postgres psql -U zenith zenithalgo < backups/backup_20251220.sql
```

### 3. 标记测试数据

在 `backtests` 表添加标记：

```sql
-- 给测试数据添加标记
UPDATE backtests
SET run_id = 'test_' || run_id
WHERE created_at > '2025-12-19';

-- 清理所有测试数据
DELETE FROM backtests WHERE run_id LIKE 'test_%';
```

### 4. 使用数据库迁移工具

未来可以考虑使用：

- **Alembic** (Python) - 数据库版本管理
- **golang-migrate** (Go) - schema 迁移

---

## 🔧 快速命令参考

```bash
# 查看状态
./scripts/db_status.sh

# 清理数据（快速，保留结构）
./scripts/clean_data.sh

# 完全重置（慢，全新开始）
./scripts/reset_database.sh

# 手动连接数据库
docker-compose exec postgres psql -U zenith -d zenithalgo

# 删除特定日期的数据
docker-compose exec -T postgres psql -U zenith -d zenithalgo -c \
  "DELETE FROM backtests WHERE created_at::date = '2025-12-20';"

# 查看数据库大小
docker-compose exec -T postgres psql -U zenith -d zenithalgo -c \
  "SELECT pg_size_pretty(pg_database_size('zenithalgo'));"
```

---

## ⚠️ 注意事项

1. **重置前备份**：`reset_database.sh` 会永久删除数据
2. **开发环境使用**：这些脚本仅用于开发，生产环境需要更严格的流程
3. **定期清理**：建议每周清理一次测试数据

---

## 📝 废数据识别规则

**当前数据分类**：

1. **有用数据** ✅

   - 完整的 sweep 结果（带参数和指标）
   - 有 equity_curve 的回测（Top 10-20）
   - 实际运行产生的数据

2. **废数据** ❌
   - 创建于今天的测试数据
   - run_id 包含 "test" 的数据
   - 无 equity_curve 的旧回测
   - 重复的迁移数据

**清理策略**：

```sql
-- 删除今天的测试数据
DELETE FROM backtests
WHERE created_at::date = CURRENT_DATE;

-- 删除无 equity 的旧数据（保留最近7天）
DELETE FROM backtests
WHERE created_at < NOW() - INTERVAL '7 days'
  AND id NOT IN (SELECT DISTINCT backtest_id FROM equity_curves);
```
