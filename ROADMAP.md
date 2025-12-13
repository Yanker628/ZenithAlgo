# ZenithAlgo Roadmap（开发中）

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

### 1.2 行情命名与包冲突规避

- `market/` 已更名为 `market_data/`（避免未来与数据目录 `data/` 混淆）。

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
- 初步引入 `research/schemas.py` 用于定义产物元数据结构。

## 2. 近期里程碑（按优先级）

### M3（中优先级）：事件循环抽象（可选）

目标：把 backtest/live 的“事件推进”抽到 `engine/event_loop.py`，但避免过度设计。

- 先做最小版：同步迭代器 + hook（无需完整 pub/sub）
- 仅当 backtest/live 出现明显逻辑漂移时再推进

### M4: 更丰富的数据/产物 Schema 校验（中优先级）

- 完善 `research/schemas.py`，覆盖更多配置和结果字段。
- 在 `backtest_engine` 和 `experiment` 中全面使用 dataclass/Pydantic 对象而非裸 dict。

## 3. 暂缓（明确不做/后做）

以下模块只有在需求出现时才启动（避免平台化过早）：

- `portfolio/`：多资产配置/再平衡（目前单品种现货不需要）
- `signals/`：多策略/多因子信号组合（当前 `signal_pipeline` 足够）
- `interfaces/api/web`：等研究链路稳定后再上
- 多数据源 adapters：先把现有 `utils/data_loader.py` 打磨好再扩展

## 4. 开发规范（简版）

- 不提交真实 API Key；使用环境变量或 `config/config.local.yml`（gitignore）。
- 测试默认离线；联网/实盘测试必须 `@pytest.mark.live`。
- 一次改动一个主题；每个 PR/commit 必须可运行/可测试。
