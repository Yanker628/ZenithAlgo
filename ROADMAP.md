# ZenithAlgo Roadmap（开发中）

> 最后核对：2025-12-14（以仓库代码现状为准；用于对齐方向，不作为“承诺交付”）

## 0. 北极星（工程优先级）

- 不乱交易：重启不重复下单，对账失败不交易。
- 可复现：同一配置 + 同一数据 = 同一结果，产物落盘可回归。
- 可审计：关键行为有账本与日志，能解释“为什么这样交易/这样盈利亏损”。
- 单入口：只保留 `main.py` 为运行入口，避免口径分裂。

## 1. 目录约定（输入 / 输出 / 状态）

- 输入数据：`dataset/history/`（历史行情 CSV；未来可导入到列式缓存/数据库）。
- 进程状态：`dataset/state/`（SQLite ledger，跨进程幂等与恢复）。
- 研究产物：`results/`（复现契约，统一落盘）。
- 文档：`documents/`（方法论、架构与协作流程）。
- 提示词：`prompts/`（提示词资产与维护脚本）。

## 2. 里程碑（按“价值/风险”排序；每个里程碑只出现一次）

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

### M8：平台化扩展（按需生长，暂不做）

- 组合/多策略（portfolio、allocation、rebalance）。
- 执行算法（TWAP/Iceberg）与回测撮合口径补齐。
- Workflows（optimize / WF / backtest / paper / live）一键化编排。
- Interfaces（CLI/API/Web），等核心契约稳定后再上。

## 3. 下一步行动（只列“最值钱”的 3 件事）

- M6-1：补齐数据集 `meta.json` 与稳定 `data_hash`（路径无关，支持复现/缓存/对账）。
- M6-2：引入列式缓存并记录命中率与耗时（让性能优化可度量）。
- M7：加一套“同数据回放”一致性测试（把执行口径锁死，避免未来回归）。

## 4. 远期（AI Agent）

原则：LLM 放在研究与开发提效链路，不污染交易内核稳定性；所有输出可复现、可落盘、可回归。

- A1 智能投研 Agent：自然语言问题 → 生成/执行分析代码 → 产出图表与结论落盘到 `results/`。
- A2 策略代码生成器：输入策略描述，生成符合 `algo/strategy/base.py` 接口的策略文件 + 最小单测。
- A3 语义情绪因子：新增 `NewsEventSource`，将情绪分数作为 `Tick.features`，优先离线回放验证。

## 5. 长期原则（不写空话）

- 先消灭工程事故，再追求策略 alpha。
- 所有新模块必须满足：可复现、可回归、可审计。
- 目录结构服务于“已存在的行为”，不要为未来幻想提前拆分。

## 6. 暂缓清单（明确不做/后做）

- 多交易所/跨交易所：先把单交易所的实盘稳定性打穿。
- Web/API：研究链路与数据协议稳定后再上。
- 高频专用 DB（TimescaleDB/KDB+）：在 Parquet 路线验证瓶颈后再决策。

## 7. 贡献与约束（简版）

- 不提交真实 API Key；使用环境变量或 `config/config.local.yml`（gitignore）。
- 测试默认离线；联网/实盘测试必须标记 `@pytest.mark.live`。
- 一次改动一个主题；每个 PR/commit 必须可运行、可测试、可回滚。
