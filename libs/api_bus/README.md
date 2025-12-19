# api_bus

Go 版 API 总线（最小可用实现），用于触发回测与扫参。

## 启动

```bash
cd libs/api_bus
go run . -addr :8000 -repo /Users/you/Code/ZenithAlgo -db /Users/you/Code/ZenithAlgo/results/api_bus.sqlite3
```

默认会优先使用项目根目录的 `.venv/bin/python`，如果没有再回退到 `python3`。
需要指定时可传：

```bash
go run . -python /Users/you/Code/ZenithAlgo/.venv/bin/python
```

可选参数（重试控制）：

```bash
go run . -max-retries 1 -retry-backoff-ms 1000
```

## 接口（异步队列）

- `GET /health`：健康检查
- `POST /api/v1/backtest`：触发回测（返回 task_id）
- `POST /api/v1/sweep`：触发扫参（返回 task_id）
- `GET /api/v1/tasks/{task_id}`：查询任务状态与结果
- `GET /api/v1/runs?limit=20`：查询最近结果索引（支持过滤）
- `GET /ws`：WebSocket 推送任务状态变化与日志

请求示例：

```bash
curl -X POST http://localhost:8000/api/v1/backtest \
  -H "Content-Type: application/json" \
  -d '{"config":"config/config.yml"}'
```

```bash
curl -X POST http://localhost:8000/api/v1/sweep \
  -H "Content-Type: application/json" \
  -d '{"config":"config/config.yml","top_n":5}'
```

查询任务：

```bash
curl http://localhost:8000/api/v1/tasks/你的_task_id
```

任务提交返回 `task_id` 与 `status=pending`，查询接口返回最终结果与 stdout/stderr。

WebSocket 示例：

```bash
# 使用 websocat 连接（如果没有可自行安装）
websocat ws://localhost:8000/ws
```

消息类型：

- `task_update`：任务状态变化（pending/running/succeeded/failed）
- `task_log`：任务运行日志（stdout/stderr 按行推送）

## 持久化说明

- 任务与结果索引落在 SQLite 中（默认 `results/api_bus.sqlite3`）。
- `runs` 表会记录 run_id、结果目录与 summary.json（便于后续查询）。

过滤示例：

```bash
curl "http://localhost:8000/api/v1/runs?symbol=BTCUSDT&limit=10"
curl "http://localhost:8000/api/v1/runs?task_id=20250101123000-1"
curl "http://localhost:8000/api/v1/runs?from=2025-01-01T00:00:00Z&to=2025-01-31T23:59:59Z"
```
