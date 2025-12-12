# 仓库工作指南（AGENTS）

本文件用于约束和提示在本仓库中实现/修改代码时应遵循的约定。

## 语言

- 默认使用简体中文回复与沟通。

## 总体目标与范围

- 本项目是单交易所、事件驱动、以现货为基础语义的量化交易系统（V1 ~ V2.1）。
- 优先保证实时与回测复用同一套接口（Strategy / Risk / Broker），差异只在数据源与时间推进。

## 目录结构与模块边界

- 现有结构以仓库为准：
  - `engine/`：`runner.py`（实时/纸面）、`backtest_runner.py`、`batch_backtest.py`、`walkforward.py`
  - `market/`：行情客户端与数据模型
  - `strategy/`：策略基类与具体策略
  - `risk/`：风控过滤与日内状态
  - `broker/`：执行层（mock/binance/backtest）
  - `utils/`：配置/数据/指标/参数搜索/sizing/日志等通用工具
  - `config/`：YAML 配置
  - `tests/`：pytest 测试
- 新增模块请遵守同样分层；避免跨层直接耦合（例如策略不要直接触网或写文件）。

## 交易语义与接口约定

- 当前按现货语义运行：不做空；`sell` 仅用于平掉已有持仓；禁止产生负仓位。
- `Strategy.on_tick` 只表达方向与理由：
  - `qty <= 0`：方向信号，由 `utils/sizer.size_signals` 统一计算真实下单数量。
  - `qty > 0`：策略希望的目标数量，但仍会被 sizing/risk 裁剪到上限。
- sizing 配置来源：
  - runner/paper/live 优先读取顶层 `sizing`；若缺省则回退到 `backtest.sizing`。
- `Broker.execute(signal, **kwargs)` 允许不同实现接收额外参数（如回测的 `tick_price/ts`）。
- 若未来需要做空，优先采用合约（Futures/Perps）方案：新增独立 Futures 交易路径（FuturesBroker/FuturesMarketClient/对应风控与 PnL 口径），不要在现货 Broker 上硬加做空逻辑。

## 运行、测试与开发命令

- 依赖管理使用 uv + `.venv`：
  - 安装：`uv pip install -e .`（或在 venv 中 `pip install -e .`）
  - 统一运行入口：`python main.py [runner|backtest|sweep|walkforward] --config config/config.yml`
  - 测试：`uv run pytest` 或 `.venv/bin/pytest`
- 任何需要联网/真实交易所的测试必须使用 `@pytest.mark.live` 标记，默认跳过。

## 编码规范与风格

- 遵循 PEP8，4 空格缩进；公共函数尽量加类型标注；简单数据结构使用 dataclass。
- 命名：模块/包 `snake_case`，类 `CamelCase`，函数/变量 `snake_case`。
- 日志使用 `utils.logging.setup_logger`，避免 `print`；单行结构化信息优先包含 `symbol`、订单 id 等。
- 配置键名小写、无连字符；修改实现时同步维护 `README.md` 与 `ROADMAP.md`。

## 测试规范

- pytest 风格 `test_*.py`；测试类 `Test*`；避免依赖外部副作用。
- 优先写离线可复现的单元/集成测试；对外部 API 访问要么 mock，要么 live 标记。

## 提交与 PR 规范

- commit 小而聚焦、动词开头；重构与行为变更分开提交。
- PR 描述应包含：目的、关键改动、pytest/lint 结果、配置/数据变化、已知限制与后续计划。

## 安全与配置建议

- 不要提交 API Key；使用环境变量或 `config/config.local.yml`（并加入 `.gitignore`）。
- 对外部数据与下单数量做校验；默认保守（`allow_live=false`、白名单、最小名义/步进）。
