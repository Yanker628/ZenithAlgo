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

- 统一产物目录至 `results/`，不再使用 `data/experiments`。
- 目录结构规范化：`results/{task}/{symbol}/{interval}/{range}/{run_id}/`。
- `equity.csv` 新增 `drawdown` 和 `drawdown_pct` 字段。
- `research/experiment.py`：统一落盘 `meta.json/summary.json/results.json/report.md/summary.md` 等产物。
- 初步引入 `research/schemas.py` 用于定义结果/元信息结构（目前尚未在 engine 全面“强类型化”使用）。

### 1.6 数据模块命名收敛 (M5 Done)

- 官方命名统一为 `market_data/`（行情 client + 历史 loader）。
- 开发阶段不保留 `data/` 兼容层（避免歧义与入口分裂）。
- 文档路径已同步到 `market_data/`；模型导入推荐使用 `market_data/models.py` 作为稳定入口。

## 2. 近期里程碑（按优先级）

### M3：事件循环抽象（已完成）

目标已通过 `engine/base_engine.py` + `engine/sources/*` 达成（不强制单独拆 `engine/event_loop.py`）。

- 同步迭代器 + 生命周期 hook（无需完整 pub/sub）
- backtest/live 共用同一 `run_loop`，事件源差异集中在 `EventSource`

### M4：更丰富的数据/产物 Schema 校验（中优先级）

- 完善 `research/schemas.py`：覆盖更多配置快照、metrics、diagnostics、policy、artifacts 字段。
- 从“弱约束 dict”逐步迁移到 dataclass（不强依赖 Pydantic）：先在 `research/experiment.py` 统一输出结构，再逐步收敛 engine 返回值。
- 为 schema/约束补齐最小测试：给 `summary.json`/`meta.json` 关键字段做离线校验（防止接口漂移）。

## 3. 暂缓（明确不做/后做）

以下模块只有在需求出现时才启动（避免平台化过早）：

- `portfolio/`：多资产配置/再平衡（目前单品种现货不需要）
- `signals/`：多策略/多因子信号组合（当前 `signal_pipeline` 足够）
- `interfaces/api/web`：等研究链路稳定后再上
- 多数据源 adapters：先把现有 `market_data/loader.py` 打磨好再扩展

## 4. 开发规范（简版）

- 不提交真实 API Key；使用环境变量或 `config/config.local.yml`（gitignore）。
- 测试默认离线；联网/实盘测试必须 `@pytest.mark.live`。
- 一次改动一个主题；每个 PR/commit 必须可运行/可测试。
