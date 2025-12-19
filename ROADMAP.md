# ZenithAlgo Roadmap（开发中）

> 最后核对：2025-12-19（以仓库代码现状为准；用于对齐方向，不作为“承诺交付”）

## 0. 北极星（工程优先级）

- 不乱交易：重启不重复下单，对账失败不交易。
- 可复现：同一配置 + 同一数据 = 同一结果，产物落盘可回归。
- 可审计：关键行为有账本与日志，能解释“为什么这样交易/这样盈利亏损”。
- 入口统一：短期保留 `main.py`，长期迁移到 API/任务中心，但口径必须一致。

## 1. 规模与边界（Scale）

- 目标：从单机 CLI 工具演进为多策略并发、前后端分离、多语言混合执行的平台。
- 语言定位：
  - Python：高层逻辑、策略研究、AI 因子生成、可视化分析。
  - Go：后端 API 总线、多路 WebSocket 行情接入、高并发订单状态管理。
  - Rust/C++：底层算子（逐笔数据解码等）、高性能向量化回测引擎。
- 边界原则：
  - 策略与研究层不直接依赖 I/O 细节，只依赖统一数据接口。
  - 计算层对外只暴露稳定算子接口，禁止跨层直接调用实现细节。
  - 服务层负责调度、权限、状态与队列，不侵入策略代码。

## 2. 目录约定（输入 / 输出 / 状态）

- 输入数据：`dataset/history/`（历史行情 CSV；未来可导入到列式缓存/数据库）。
- 进程状态：`dataset/state/`（SQLite ledger，跨进程幂等与恢复）。
- 研究产物：`results/`（复现契约，统一落盘）。
- 文档：`documents/`（方法论、架构与协作流程）。
- 提示词：`prompts/`（提示词资产与维护脚本）。

## 3. 平台化分层（Component）

### The Core：计算层下沉

- Factor-Lib（Rust/C++）：将 `algo/factors/` 基础指标改写为高性能算子。
- Vector-Engine：提供不依赖事件循环的向量化回测接口，专供 sweep 使用。
- DoD：同一数据集下核心因子计算耗时显著下降，且结果与 Python 版本一致。

### The Pipe：数据总线化

- Arrow-Data-Server：使用 Apache Arrow 作为内存交换标准，Python/Rust 共享行情数据。
- DatasetStore：以 `data_hash` 为索引的 Parquet/Feather 存储层（承接 M6）。
- DoD：数据加载耗时可量化下降，`data_hash` 可复现且与路径无关。

### The Brain：后端服务化

- Task-Center（Go）：处理 Web 请求、调度 Worker、健康检查与资源隔离。
- State-Service：将 sqlite_ledger 升级为带 API 访问的状态服务。
- DoD：`main.py` 解析职责迁出，回测任务以异步方式排队执行。

### The Face：前端可视化

- Strategy-Dashboard：支持参数一键回测与曲线对比（React/Vue/Streamlit 任选其一）。
- 实时反馈：WebSocket 推送进度与权益曲线。
- DoD：研究与回测可通过 GUI 完成，并可快速对比多组参数结果。

## 4. 里程碑（按“价值/风险”排序；每个里程碑只出现一次）

### M1：algo 命名空间收敛（已完成）

- 范围：`strategy/factors/risk/sizing` 统一归并到 `algo/*`，接口口径统一。

### M2：研究产物落盘（已完成）

- 范围：统一写入 `results/{task}/{symbol}/{interval}/{range}/{run_id}/`。
- 产物：
  - `config.yml`、`effective_config.json`、`meta.json`
  - `summary.json`、`results.json`、`trades.csv`、`equity.csv`
- 说明：sweep 默认只输出 `best_params + best_metrics`；是否额外跑一次最佳回测由
  `backtest.sweep.run_best_backtest` 控制。

### M3：事件循环抽象（已完成）

- 范围：`engine/base_engine.py` 提供统一 `run_loop(...)`，回测/纸面/实盘复用事件循环。
- 事件源：回测 `engine/sources/event_source.py`；实盘 `engine/sources/market_event_source.py`。

### M4：全面强类型化（Schema Enforcement，已完成）

- 配置：`shared/config/schema.py` + `shared/config/config_loader.py`（Pydantic，未知 key 直接失败）。
- 结果：回测 summary 使用强类型（`research/schemas.py`），避免深层 dict 索引。
- 复现契约：`meta.json/summary.json/results.json` 强制 `schema_version` + 复现骨钉
  （`git_sha/config_hash/data_hash/created_at` 等）。
- 测试：写入时校验 + 读取再校验，防止历史产物被“悄悄改坏”。

### M5：状态管理与灾难恢复（State Recovery，已完成）

- M5-1 幂等：确定性 `client_order_id` + broker 层去重（跨重放不重复下单）。
- M5-2 账本：SQLite 本地事件账本（orders/fills），重启恢复 `_seen_client_order_ids`，
  实现跨进程幂等。
- M5-3 对账：启动对账 `startup_reconcile(...)` + 安全保险丝（`recovery.enabled/mode`；
  对账未完成或异常自动降级 `observe_only` 并禁止下单）。
- 工程保障（已补齐）：价格/数量步进与精度按交易所规则约束，
  避免 `0.13893 -> 0.14` 这种误差。
- 关键计算使用 `Decimal`，避免浮点尾巴。

### M6：数据层升级（Data as First-Class Citizen，进行中）

目标：数据“可索引、可追溯、可复现”，并减少 CSV I/O 瓶颈。

- M6-1 数据集元信息：生成 `meta.json` + 稳定 hash，并写入研究运行的 `data_hash`。
- M6-2 列式缓存：引入 Parquet/Feather 缓存（优先读缓存，CSV 仅作导入/交换）。
- M6-3 激活 `database/`：提供统一 DatasetStore 接口与索引层（用于管理数据资产与加速读取）。

验收（DoD）：

- 同区间重复回测，数据加载耗时可量化下降。
- 任一结果可明确回答“我用了哪份数据（hash）”，且与路径无关。

### M7：执行一致性验证（Backtest vs Paper，待做）

目标：研究路径与执行路径一致，避免“回测盈利 ≠ 实盘盈利”。

- 固定：同一份历史 candles、同一策略与参数、同一费用/滑点口径。
- 对比：signals、`client_order_id`、fills、最终持仓与 PnL。

验收（DoD）：

- 差异可解释（例如手续费、撮合模型差异），不允许系统性漂移。

### M8：混合计算算子库（规划中）

- 引入 PyO3/pybind11 环境，沉淀 Rust/C++ 算子。
- `experiment.py` 优先调用高性能算子，无则回退 Python 逻辑。
- 目标对齐：The Core（计算层下沉）。

### M9：数据总线化与 DatasetStore（规划中）

- Arrow 作为跨语言内存交换标准，保障 Python/Rust 数据共享。
- DatasetStore 按 `data_hash` 组织 Parquet 数据资产。
- 目标对齐：The Pipe（数据总线化）。

### M10：任务中心与状态服务（规划中）

- Go/服务化后端接管任务解析与调度，提供异步接口与任务 ID。
- 引入任务状态存储（Redis）与 Worker 生命周期管理。
- 目标对齐：The Brain（后端服务化）。

### M11：策略可视化工作台（规划中）

- GUI 支持参数回测、曲线对比、进度展示。
- WebSocket 实时推送权益与日志摘要。
- 目标对齐：The Face（前端可视化）。

## 5. 行动计划（Action，Month 1-3）

### Month 1：建立混合计算算子库

- 引入 PyO3（Rust）或 pybind11（C++）构建环境。
- 把 `algo/factors/` 核心算法下沉为高性能算子。
- 重构 `experiment.py`，优先调用编译算子，失败时回退 Python 逻辑。

### Month 2：后端 API 封装与异步化

- 采用 Go（Gin）或 FastAPI 接管 `main.py` 的解析与入口职责。
- 实现 `/api/v1/backtest` 异步接口：立即返回任务 ID、后台排队执行。
- 引入 Redis 存储任务状态（Pending/Running/Finished）。

### Month 3：存储层升级与监控接入

- 数据自动转 Parquet，优先读取列式缓存。
- 在 `engine/base_engine.py` 的 `run_loop` 增加 WebSocket 推送 hook。
- 提供最小可用前端，展示回测进度与实时权益曲线。

## 6. Flow（数据与逻辑流向）

- 指令流：前端 Dashboard → Go 后端（任务验证/鉴权）→ 任务队列 → Python/Rust Worker（计算层）。
- 数据流：历史行情（Parquet）→ Arrow 内存映射 → Rust 因子计算 → Python 策略决策 → 结果库。
- 反馈流：Worker 实时权益 → Go 后端（WebSocket）→ 前端曲线绘制。

## 7. Feedback（反馈与持续优化）

- 性能监控：每次回测 `summary.json` 记录加载耗时、计算耗时、I/O 占比。
- 一致性校验：定期运行 `test_experiment_reproducibility.py`，Rust 与 Python 结果一致。
- 因子有效性：前端“多图对比”定位表现下降原因（手续费模型或策略漂移）。

## 8. 远期（AI Agent）

原则：LLM 放在研究与开发提效链路，不污染交易内核稳定性；所有输出可复现、可落盘、可回归。

- A1 智能投研 Agent：自然语言问题 → 生成/执行分析代码 → 产出图表与结论落盘到 `results/`。
- A2 策略代码生成器：输入策略描述，生成符合 `algo/strategy/base.py` 接口的策略文件 + 最小单测。
- A3 语义情绪因子：新增 `NewsEventSource`，将情绪分数作为 `Tick.features`，优先离线回放验证。

## 9. 长期原则（不写空话）

- 先消灭工程事故，再追求策略 alpha。
- 所有新模块必须满足：可复现、可回归、可审计。
- 目录结构服务于“已存在的行为”，不要为未来幻想提前拆分。

## 10. 暂缓清单（明确不做/后做）

- 多交易所/跨交易所：先把单交易所的实盘稳定性打穿。
- 高频专用 DB（TimescaleDB/KDB+）：在 Parquet 路线验证瓶颈后再决策。
- 过度复杂的策略市场：先让核心回测与数据链路稳定，再谈“量化平台化”扩展。

## 11. 贡献与约束（简版）

- 不提交真实 API Key；使用环境变量或 `config/config.local.yml`（gitignore）。
- 测试默认离线；联网/实盘测试必须标记 `@pytest.mark.live`。
- 一次改动一个主题；每个 PR/commit 必须可运行、可测试、可回滚。
