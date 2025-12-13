# ZenithAlgo Roadmap（开发中）

> 最后核对：2025-12-13（以仓库代码现状为准；路线图用于对齐方向，不作为“承诺交付”）

## 0. 总原则

- 单交易所、事件驱动、现货语义（不做空；`sell` 仅平仓）。
- 实盘/回测尽量复用同一套接口（Strategy / Risk / Broker / Sizing）。
- 差异只允许出现在数据源与时间推进层。
- 唯一运行入口：`main.py`（避免入口分裂与口径不一致）。

## 1. 目录约定（输入 / 输出 / 状态）

- `dataset/history/`：历史行情输入（可下载/可替换）。
- `dataset/state/`：本地状态（SQLite ledger 等），用于跨进程幂等与恢复。
- `results/`：研究与回测产物（复现契约）。
- `documents/`：方法论、架构与协作流程。
- `prompts/`：提示词资产与脚本。

说明：研究与回测产物统一写入 `results/`。

## 2. 已完成里程碑（以代码现状为准）

### M1：algo 命名空间收敛（已完成）

- `strategy/` → `algo/strategy/`，`factors/` → `algo/factors/`，`risk/` → `algo/risk/`，`sizing/` → `algo/sizing/`。

### M2：产物目录与实验落盘（已完成）

- 统一产物目录至 `results/`，结构：`results/{task}/{symbol}/{interval}/{range}/{run_id}/`。
- `research/experiment.py` 统一落盘 `meta.json/summary.json/results.json` 与报告类产物。

### M3：事件循环抽象（已完成）

- `engine/base_engine.py` 提供统一 `run_loop(...)`，回测/实盘复用同一事件循环。
- 事件源集中在 `engine/sources/*`（回测 `EventSource`，实盘 `MarketEventSource`）。

### M4：Schema Enforcement（已完成）

- 配置强类型化：`shared/config/schema.py` + `shared/config/config_loader.py`（Pydantic；未知 key 直接失败）。
- 实验产物结构版本化：`meta.json/summary.json/results.json` 写入 `schema_version`；
  同时包含复现骨钉（如 `git_sha/config_hash/data_hash/created_at`）。
- 回测总结强类型化：`engine/backtest_engine.py` 返回 `research/schemas.py:BacktestSummary`，避免深层字典索引。
- 配套测试覆盖“写入 + 读取再校验”的复现契约。

### M5：State Recovery（已完成：M5-1 ~ M5-3）

- M5-1：`client_order_id` 幂等键（可预测生成）+ broker 去重；实盘透传 Binance `newClientOrderId`。
- M5-2：SQLite 本地事件账本（orders/fills），重启恢复 `_seen_client_order_ids`，实现跨进程幂等。
- M5-3：启动对账 + 安全保险丝：
  - `config.recovery.enabled/mode`（`observe_only|trade`）。
  - 启动对账 `startup_reconcile(...)` 未完成或异常自动降级 `observe_only` 并禁止下单。

## 3. 下一步（建议顺序；每步都应可独立 PR 验收）

### M6：数据层升级（进行中）

目标：让数据成为“可索引、可追溯、可复现”的一等公民，减少 CSV I/O 瓶颈。

- M6-1：数据集元信息（`meta.json`）与 hash：
  - 记录来源、时间范围、字段列表、hash；与实验 `data_hash` 打通。
- M6-2：Parquet/Feather 缓存层（回测读取优先走列式缓存，CSV 仅作导入/交换）。
- M6-3：激活 `database/` 模块，抽象统一的读写与索引接口。

验收（DoD）：

- 同区间回测读取耗时可量化下降。
- 数据集具备可追溯元信息与 hash，实验可复现不依赖“当前目录状态”。

### M4+：协议与强类型深化（不破坏主流程）

目标：在保持开发速度的同时，让系统边界“可演进、可迁移、可验证”。

- M4-1：配置/回测总结已模型化；下一步是把 sizing/policy 等“开放 dict”逐步收敛为版本化 schema。
- M4-2：收敛 `research/schemas.py`：
  - 统一定义 `meta/summary/results` schema；
  - 提供离线校验入口（用于历史结果巡检与迁移脚本）。
- M4-3：统一信号协议：
  - 在保留 `OrderSignal` 的同时引入 `SignalPacket`（`signal + meta`）用于研究落盘与回放。

### M5+：更强对账（逐步增强）

目标：把“只读观测”升级为“可控恢复”，但仍以安全为先。

- M5-4：对账差异分类更细（OPEN/NEW/SUBMITTED 等映射），补齐更多“交易所存在但本地缺失”的写回。
- M5-5：恢复完成的显式解锁机制（人工确认/手动解锁后才进入 `trade`）。

## 4. 远期（AI Agent 与高级交易特性）

原则：LLM 放在研究与开发提效链路，不污染交易内核稳定性。

### A1：智能投研 Agent

- 自然语言问题 → 生成/执行分析代码 → 产出图表与结论落盘到 `results/`。
- 重点：执行隔离、可复现、输出结构化。

### A2：策略代码生成器

- 输入策略描述，生成符合 `algo/strategy/base.py` 接口的策略文件。
- 自动生成最小单测与示例配置段，至少能跑通烟囱测试（smoke test）。

### A3：语义级情绪因子

- 新增 `NewsEventSource`，将事件转为 `Tick.features`（-1~+1 或分桶）。
- 重点：离线回放优先；实盘接入需限流与降级策略。

### E1：算法执行（TWAP / Iceberg）

- 在 `broker/execution/` 实现拆单与节奏控制，并补齐回测撮合口径。

### E2：多策略与组合管理

- 从“单策略单品种”演进到“多策略/多品种”，引入组合级风控与资金分配。

## 5. 暂缓（明确不做/后做）

- 多交易所/跨交易所：先把单交易所实盘稳定性打穿，再考虑扩展。
- Web/API 界面：研究链路与数据协议稳定后再上。
- 高频专用数据库（TimescaleDB/KDB+）：在 Parquet 路线验证瓶颈后再决策。

## 6. 开发规范（简版）

- 不提交真实 API Key；使用环境变量或 `config/config.local.yml`（gitignore）。
- 测试默认离线；联网/实盘测试必须 `@pytest.mark.live`。
- 一次改动一个主题；每个 PR/commit 必须可运行、可测试、可回滚。
