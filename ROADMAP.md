# ZenithAlgo Roadmap（开发中）

> 最后核对：2025-12-13（以仓库代码现状为准；路线图用于对齐方向，不作为“承诺交付”）

## 0. 总原则（不变）

- 单交易所、事件驱动、现货语义（不做空；`sell` 仅平仓）。
- 实盘/回测尽量复用同一套接口（Strategy / Risk / Broker / Sizing），差异只在数据源与时间推进。
- **唯一运行入口：`main.py`**（避免入口分裂与口径不一致）。

## 1. 当前状态（已完成）

### 1.1 入口与执行层

- `main.py` 作为唯一 CLI。
- `engine/trading_engine.py`：实盘/纸面/干跑（`TradingEngine`）。
- `engine/backtest_engine.py`：单次回测（`BacktestEngine`）。
- `engine/signal_pipeline.py`：策略→sizing→风控→执行的共享管线，减少 backtest/live 漂移。

### 1.2 事件推进/事件源抽象（已落地）

- `engine/base_engine.py`：统一 `run_loop(...)`（回测/实盘复用同一事件循环）。
- `engine/sources/event_source.py`：`EventSource` + `PandasFrameEventSource`（回测数据源）。
- `engine/sources/market_event_source.py`：`MarketEventSource`（实时行情源；含重试/退避）。

### 1.3 协作与工程化（开发阶段）

- 文档统一放在 `documents/`，提交前可运行 `make lint` 做 Markdown 校验。
- 常用命令用 `Makefile` 统一封装（`make help/test/lint`）。

### 1.4 algo 层命名空间收敛 (M1 Done)

- `strategy/` → `algo/strategy/`
- `factors/` → `algo/factors/`
- `risk/` → `algo/risk/`
- `sizing/` → `algo/sizing/`
- 更新 import 与测试

### 1.5 分析/产物目录统一 (M2 Done)

- 统一产物目录至 `results/`。
- 目录结构规范化：`results/{task}/{symbol}/{interval}/{range}/{run_id}/`。
- `equity.csv` 新增 `drawdown` 和 `drawdown_pct` 字段。
- `research/experiment.py`：统一落盘 `meta.json/summary.json/results.json/report.md/summary.md` 等产物。
- 初步引入 `research/schemas.py` 用于定义结果/元信息结构（目前尚未在 engine 全面“强类型化”使用）。

### 1.6 数据模块命名收敛（已完成）

- 官方命名统一为 `market_data/`（行情 client + 历史 loader）。
- 文档路径已同步到 `market_data/`；模型导入推荐使用 `market_data/models.py` 作为稳定入口。

## 2. 路线图（阶段化）

目标：先把系统做到“敢上实盘，能复现，不丢单”，再逐步引入 AI 与高级交易能力。

### 阶段一：稳固内核与工程化（The Foundation）

#### M3：事件循环抽象（已完成）

目标已通过 `engine/base_engine.py` + `engine/sources/*` 达成（不强制单独拆 `engine/event_loop.py`）。

- 同步迭代器 + 生命周期 hook（无需完整 pub/sub）
- backtest/live 共用同一 `run_loop`，事件源差异集中在 `EventSource`

#### M4：全面强类型化（Schema Enforcement）

痛点：配置与结果主要是 `dict`，key 拼写错误会在实盘/回测中造成隐蔽灾难。

原则（结合当前代码现状的务实路径）：

- “边界强类型，内部渐进”：优先把配置解析、broker/engine 输出等边界层强类型化；
  内部计算保持 dataclass/简单对象，避免过度设计与性能损耗。
- “协议先行”：先定义稳定的数据交换协议，再去替换实现细节。

行动（建议顺序）：

- 引入 Pydantic（或等价方案）：将 `config.yml` 的关键段落建模为 `BaseModel`，
  作为唯一配置入口（校验、默认值、字段弃用策略）。
- 收敛回测/实验输出：把 `meta.json` / `summary.json` / `results.json` 的结构
  固化为版本化 schema（例如 `schema_version`），并提供离线校验。
- 统一信号协议：在保留 `OrderSignal` 的同时，引入 `SignalPacket`（或同名结构），
  形如 `{signal: OrderSignal, meta: {...}}`，meta 可包含：
  - 触发因子值快照（factor snapshot）
  - 置信度/打分（confidence/score）
  - 归因信息（why/how）
  - 版本信息（strategy_version/features_version）
- 为协议与关键校验补齐最小测试：覆盖“错误字段/缺字段/类型错误”场景，
  防止未来重构引入静默行为变更。

验收（Definition of Done）：

- 错误配置在启动阶段失败（而不是跑到中途报错）。
- 实验产物可离线校验通过，并具备明确的 schema version。
- `SignalPacket` 能贯穿 backtest 与 runner 的记录链路（至少落盘/日志可见）。

#### M5：状态管理与灾难恢复（State Recovery）

痛点：实盘进程崩溃/断网重启后，内存状态（positions/orders）丢失会导致：
重复下单、无法平仓、PnL 口径漂移。

行动（建议顺序）：

- LiveBroker Reconciliation（对账）：启动时从交易所拉取真实持仓/挂单/成交，
  与本地状态比对并同步，明确“交易所为最终真相源”。
- 本地持久化（SQLite）：将订单生命周期与成交事件写入 SQLite（append-only + 索引），
  并能在重启时恢复内存状态。
- 幂等与去重：为下单请求引入 `client_order_id`（或等价字段）与重放保护，
  防止重启后重复提交相同意图。
- 风控与保险丝接入恢复流程：重启后先进入“只读/观测”阶段，完成对账后再允许下单。

验收（Definition of Done）：

- 模拟崩溃重启后，不会产生重复下单（在相同输入流下结果可预测）。
- 重启后能恢复持仓/挂单/已成交的视图，并与交易所一致。
- SQLite 文件可迁移/备份，且具备基本的查询能力（按 symbol/time/order_id）。

#### M6：数据层升级（Data Layer）

痛点：CSV 在多品种/高频场景下读写慢、管理散；研究与回测的 I/O 成为瓶颈。

行动（建议顺序）：

- 激活 `database/` 模块：定义统一的数据存储接口（读写/索引/元信息）。
- 历史数据落盘格式升级：优先支持 Parquet/Feather（列式存储 + 压缩 + 随机读取）。
- 数据目录与元信息：为每个数据集生成 `meta.json`（来源、时间范围、hash、字段），
  与实验的 `data_hash` 打通，保证复现。
- 保留 CSV 作为“交换/导入格式”，但回测读取优先走 Parquet 缓存。
- 若未来走高频：再评估 TimescaleDB / KDB+（作为后续扩展，而非当前必做）。

验收（Definition of Done）：

- 在相同回测区间下，数据读取耗时显著下降（至少可量化对比）。
- 数据集具备可追溯元信息与 hash，实验可复现不依赖“当前目录状态”。

### 阶段二：AI Agent 与策略深度（The Edge）

目标：把 LLM 能力放在“研究/开发提效”与“特征增强”，避免污染交易内核的稳定性。

#### A1：智能投研 Agent（Research Agent）

- 基于 `prompts/` 与现有研究工具，提供一个离线优先的研究入口：
  输入自然语言问题 → 生成/执行 Python 分析 → 产出图表与结论落盘到 `results/`。
- 重点：执行环境隔离、代码可复现、输出结构化（便于回溯与对比）。

#### A2：策略代码生成器（Strategy Coder）

- 输入自然语言策略描述，生成符合 `algo/strategy/base.py` 接口的策略文件，
  并自动生成最小单测与示例配置段，确保“可运行/可回测”。
- 重点：生成结果必须通过静态检查与最小回测烟囱测试（smoke test）。

#### A3：语义级情绪因子（Sentiment Factor）

- 新增 `NewsEventSource`：把新闻/社媒事件转成 Feature（-1~+1 或分桶），写入 `Tick.features`。
- 重点：先做离线回放与可控数据源；实盘抓取/调用 LLM 需严格限流与降级策略。

### 阶段三：高级交易特性（Sophistication）

#### E1：算法执行（Algorithmic Execution）

- 在 `broker/execution/` 实现 TWAP / Iceberg 等执行算法，支持拆单、节奏控制与滑点评估。
- 同步补齐回测撮合对这些执行算法的模拟口径，避免“实盘很好/回测很差”的错觉。

#### E2：多策略与组合管理（Portfolio Management）

- 从“单策略单品种”演进到“多策略/多品种”，引入统一资金分配与组合级风控。
- 逐步引入 Risk Parity / 马科维茨等组合权重方法（先做可解释、可复现版本）。

## 3. 暂缓（明确不做/后做）

- 多交易所/跨交易所：先把单交易所实盘稳定性打穿，再考虑扩展。
- Web/API 界面：研究链路与数据协议稳定后再上（避免提前平台化）。
- 高频专用数据库（TimescaleDB/KDB+）：在 Parquet 路线验证瓶颈后再决策。

## 4. 开发规范（简版）

- 不提交真实 API Key；使用环境变量或 `config/config.local.yml`（gitignore）。
- 测试默认离线；联网/实盘测试必须 `@pytest.mark.live`。
- 一次改动一个主题；每个 PR/commit 必须可运行/可测试。
