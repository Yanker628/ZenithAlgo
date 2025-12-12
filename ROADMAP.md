# V1 量化交易系统开发 Roadmap

> 目标：在本地用 **Python** 实现一个**单交易所、单策略、事件驱动、带风控但可以先只做模拟下单** 的 V1 系统。  
> 不依赖服务器、不强制真实 API Key 就能跑通主流程。

---

## 0. 项目范围与设计原则

### 0.1 V1 范围（Scope）

- ✅ 单交易所（例如：Binance / 某券商 / 模拟数据）
- ✅ 单品种或少量品种（例：BTCUSDT）
- ✅ 单策略（例如：MA 交叉 / 突破）
- ✅ 本地运行（无服务器要求）
- ✅ **事件驱动**：Tick/K 线 → 策略 → 风控 → “下单”（模拟可）
- ✅ 支持简单配置（YAML/JSON）
- ✅ 有基础日志

- ❌ 不做：多交易所、多账户、多策略组合调度
- ❌ 不做：AI 决策 / LLM
- ❌ 不做：复杂回测引擎（只预留结构）
- ❌ 不做：GUI 前端 / Web Dashboard

### 0.2 代码结构（建议）

```text
ZenithAlgo/
  config/
    config.example.yaml
  data/
    # 存放历史数据、下载脚本等（后面再补）
  engine/
    runner.py          # 主事件循环入口
  market/
    client.py          # 行情客户端
    models.py          # Tick / Candle 等数据结构
  strategy/
    base.py            # Strategy 抽象类
    simple_ma.py       # 示例策略
  risk/
    manager.py         # 风控模块
  broker/
    base.py            # Broker 抽象类
    mock.py            # 模拟 Broker（V1 必做）
    binance.py         # 真实交易所实现（V1.1 再做）
  utils/
    logging.py         # 日志工具封装
    config_loader.py   # 读取配置
  main.py              # 程序启动入口
  README.md
  ROADMAP_V1.md        # 当前文件
```

# V1.1 量化交易系统开发 Roadmap

> 目标：在 **V1 本地事件驱动框架** 的基础上，把系统从“假行情 + Mock 下单”升级为  
> **真实交易所行情 + 可配置的模拟/真实下单（优先纸面交易）**。
>
> 依然在本地运行，不强制迁移到服务器。

---

## 0. V1.1 范围（Scope）

在现有 V1 的结构基础上，V1.1 做这些升级：

- ✅ 用 **真实交易所行情** 替换 `fake_tick_stream`（REST + WebSocket 二选一或都要）
- ✅ 引入 **RealBroker**，对接真实交易所 API
  - 初期仍可做「伪下单 / 纸面交易」，但走真实风控 & 实盘流程
- ✅ 补上 **基础 PnL 计算**，让 `RiskManager` 的 `daily_pnl` 有真实来源
- ✅ 增加 **运行模式：dry-run / paper / live** 三种模式
- ✅ 强化 **安全与配置管理**（API Key、权限、环境变量）
  - Live 保护开关：`allow_live=false` 默认阻断真下单
  - 交易对白名单与精度约束：支持配置 `symbols_allowlist`、`min_notional/min_qty/qty_step/price_step`，live 下单前校验/剪裁数量
  - 建议从 exchangeInfo 拉取精度与最小量，或在配置中填入
  - 交易日志：按日切 CSV 记录执行细节（mode/price/qty/PnL）

不在 V1.1 做的事：

- ❌ 不做多交易所、多市场
- ❌ 不做多策略调度
- ❌ 不做 AI / LLM
- ❌ 不做 Web 前端 / Dashboard

---

## 1. 设计决策

### 1.1 选定一个交易所 / 券商（示例用 Binance）

你可以根据自己实际情况选择：

- 加密：Binance / OKX / Bybit 等
- 股票：券商 API、聚宽、掘金等（如果有）

**Roadmap 中以 Binance 现货/合约为示例**，你可以按同样思路换成自己的交易所。

### 1.2 运行模式设计（很关键）

在 `config/config.yaml` 增加：

```yaml
mode: "dry-run" # dry-run / paper / live
```

# V1.2 量化交易系统开发 Roadmap

> 目标：在 V1.1 的基础上，把系统从“能跑的 demo”升级成  
> **稳定、可观察、适合长时间 paper-trade 的交易引擎**。

---

## 0. V1.2 范围（Scope）

重点只做四件事：

1. **策略去抖动**：避免在极小价差来回开平仓
2. **交易记录持久化**：每笔交易都有可回溯的记录（CSV/SQLite）
3. **PnL 结构清晰化**：区分已实现/未实现/当日累计，日志可读
4. **日内重置（可选）**：为日级风控和绩效统计打基础

不做的事情：

- ❌ 不上新交易所、不加新资产
- ❌ 不加 AI / 预测模型
- ❌ 不做复杂组合管理（多策略/多品种留到 V2）

### V1.2 进展（已实现）

- 简单去抖动（最小 MA 差值 + 冷却时间）
- 交易日志持久化（日切 CSV，含价/量/模式/PnL）
- PnL 结构：已实现（历史/当日）+ 未实现，定期日志输出，总体百分比
- 日切重置：跨日重置当日已实现 PnL 与风控日内计数
- 交易所精度与规则同步：启动时自动拉取 exchangeInfo，更新 minQty/minNotional/stepSize，并在下单前校验。
- 持仓/余额同步：live 模式周期性与交易所对账，修正本地持仓。
- 观察性：增加指标/日志聚合（PnL、订单状态、重连次数），可选 Prometheus/简易 CSV。
- 订单保护：白名单、最小/最大下单额、滑点/价格偏离检查（保护性拒单）。
- 配置与策略扩展：保持策略工厂模式，支持注入自定义参数（不强加新策略）。

### 1. 策略去抖动示例代码

```python
class SimpleMAStrategy(Strategy):
    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        min_ma_diff: float = 0.5,    # 最小 MA 差值（单位：价格）
        cooldown_secs: int = 10,     # 信号冷却时间（秒）
    ):
        ...
        self.min_ma_diff = min_ma_diff
        self.cooldown_secs = cooldown_secs
        self.last_trade_ts: datetime | None = None
```

# V2.0 量化交易系统开发 Roadmap

> 目标：在不破坏现有实盘结构的前提下，  
> 用 **同一套 Strategy / Risk / Broker 接口**，
> 跑出一个 **离线回测引擎 + 基础研究工具**。

---

## 0. 范围（Scope）

V2 只专注几件事：

1. ✅ **BacktestRunner**：离线回测主程序
2. ✅ **历史数据加载 & Tick/Candle 回放**
3. ✅ **回测绩效指标**（收益、回撤、Sharpe 粗略等）
4. ✅ **参数扫描（Grid/Random Search）**
5. ✅ 保证：**实时引擎和回测引擎用同一套 Strategy / Risk / Broker 逻辑**

不做的：

- ❌ 不引入新交易所
- ❌ 不接 AI 模型
- ❌ 不做多策略组合管理（留到 V2.1）
- ❌ 不做复杂图形可视化（可以先用简单 CSV + Notebook）

### V2.0 进展（已实现）

- `engine/backtest_runner.py` + `broker/backtest.py` 复用策略/风控接口，纯本地下单
- `utils/data_loader.py` 支持自动下载 Binance K 线（回测缺失自动补齐）并转 Tick
- `utils/metrics.py` 提供收益、回撤、Sharpe、胜率、盈亏均值等指标
- `utils/param_search.py` 支持网格搜索，输出 CSV
- TradeLogger/持仓/PnL 复用，权益曲线驱动指标计算

# V2.4-0 研究框架补全（Sprint 0）

> 目标：让研究产物结构化、可复现、可读（不再“能跑但抓不住重点”）。

验收点（已实现）：
- sweep（任意策略/任意参数维度>=1）必产出 `summary.md` 与至少 1 张图（2D heatmap / 1D 曲线 / 参数重要性兜底）
- `report.md` 首页固定输出：data health / trade health / 核心绩效 / 稳定性结论
- walk-forward overall 额外输出：`profitable_segments_ratio` / `worst_segment_return` / `median_return`

---

## 1. 目录与模块规划

新增/调整文件结构建议：

```text
engine/
  runner.py            # 实盘/实时引擎（已有）
  backtest_runner.py   # ★ 新：回测引擎入口
data/
  history/             # 存放历史行情数据（k线/成交）
  trades/              # 实盘/回测交易记录（已有）
utils/
  data_loader.py       # ★ 新：统一历史数据读入
  metrics.py           # ★ 新：回测指标计算
  param_search.py      # ★ 新：参数扫描（可选）
```

# ZenithAlgo V2.1 Roadmap — 策略研究增强版

> 目标：在 V2.0 回测引擎基础上，强化“研究能力”：
>
> - 能系统地做参数搜索（Grid Search）
> - 支持手续费与滑点模拟，更接近真实
> - 可以快速对比不同参数 / 不同品种的表现
> - 为后续 V2.2 的策略组合、多因子、AI 辅助决策打基础

---

## 0. 范围（Scope）

V2.1 聚焦这 4 件事：

1. **参数搜索引擎（Grid Search / Random Search 简版）**
2. **手续费 & 滑点模拟**
3. **多品种回测支持（同一策略，不同 symbol 测试）**

不做的：

- ❌ 不改实盘引擎（仍然是 V1.x 范围）
- ❌ 不做多策略组合（多个策略权重管理）——留给 V2.2+
- ❌ 不引入新策略类型（还是 SimpleMA），但要为扩展预留空间

---

## 1. 目录与模块规划

在现有基础上扩展：

```text
engine/
  runner.py
  backtest_runner.py         # V2.0 已有：单参数回测
  batch_backtest.py          # ★ 新：批量回测 / 参数搜索入口

utils/
  data_loader.py
  metrics.py
  param_search.py            # ★ 新：参数搜索逻辑（Grid / Random）
  plotter.py                 # ★ 新：简单可视化（资金曲线 / 回撤）

config/
  config.yml                 # backtest 增加多品种与参数网格设置
  param_sweeps.yml           # ★ 可选：单独保存参数搜索配置
```

# V2.2 量化交易系统开发 Roadmap

> 目标：在现有 V2.x 基础上，把系统从“能跑回测”升级为  
> **“能系统研究策略表现（可视化、参数搜索、Walk-Forward 验证）”**。  
> 重点是研究体验 & 结果解释性，不是再加新策略。

---

## 0. 项目范围与设计原则

### 0.1 V2.2 范围（Scope）

- ✅ 继续聚焦 **单交易所 / 单账户 / 少数几个品种（BTCUSDT 为主）**
- ✅ 只在已有 **事件驱动 + 回测引擎** 上增强能力
- ✅ 强化：
  - 回测结果 **可视化**
  - 参数搜索（Sweep）结果 **分析 & 热力图**
  - **自动选择最佳参数** 并生成新的 config
  - 简易 **Walk-Forward / 时间分段回测**
- ✅ 以命令行 + Markdown 文档为主，不做 UI

- ❌ 不做：新交易所、新资产类别（例如股票、期权）
- ❌ 不做：多策略组合 / 投资组合优化
- ❌ 不做：复杂订单系统（撮合模拟、委托簿细节）
- ❌ 不做：Web 前端 / DashBoard

### 0.2 代码结构（在现有基础上新增/调整）

```text
ZenithAlgo/
  config/
    config.yml
    config_best_BTCUSDT_1h.yml      # ★ V2.2: 由工具生成的最优参数配置

  data/
    history/                        # 历史K线
    ma_sweep_BTCUSDT_1h.csv         # Sweep 结果（已有）
    ...                             # 其他品种 Sweep 结果

  plots/                            # ★ V2.2: 自动输出图表
    BTCUSDT_1h_equity.png
    BTCUSDT_1h_drawdown.png
    BTCUSDT_1h_returns.png
    BTCUSDT_1h_sweep_heatmap.png

  engine/
    runner.py
    backtest_runner.py
    batch_backtest.py
    walkforward.py                  # ★ V2.2: Walk-Forward 回测入口

  market/
    client.py
    models.py

  strategy/
    base.py
    simple_ma.py

  risk/
    manager.py                      # ★ V2.2: 降噪日志/小优化

  broker/
    base.py
    backtest.py                     # 回测 Broker
    binance.py
    ...

  utils/
    logging.py
    config_loader.py
    pnl.py
    metrics.py
    data_loader.py
    plotter.py                      # ★ V2.2: 图表绘制工具
    sweep_analyzer.py               # ★ V2.2: Sweep 结果分析/可视化
    best_params.py                  # ★ V2.2: 选最佳参数 + 生成配置
    param_search.py                 # V2.1 已有

  docs/
    V1_Roadmap.md
    V2.1_Roadmap.md
    V2.2.md                         # ★ V2.2: 用户文档/使用指南

  main.py
  README.md
  ROADMAP_V2.2.md                   # 本文件
```

# ZenithAlgo V2.3 开发 Roadmap

> 版本定位：把现有的 **“单策略脚本式回测/实盘”** 推进到 **“可复用的因子(Feature)/信号(Signal)/组合(Portfolio)实验框架”**。  
> 核心目标是 **解耦 + 可重复实验 + 更可信的回测**，让你后面做策略优化不再“改一处炸全身”。

---

## 0. V2.3 目标与非目标

### 0.1 目标（你下一步最该干什么）

1. **因子层/特征层抽象**：把 MA、RSI、ATR… 这类“指标计算”从策略里拆出来，形成 `factors/`（或 `features/`）库。
2. **信号层标准化**：策略只做 “基于因子 → 生成信号”，不负责数据读取、仓位、成交仿真细节。
3. **实验可复现**：每一次 sweep / walk-forward 都能落盘：配置、代码版本、数据区间、结果、图。
4. **更靠谱的回测引擎**：至少把 **成交/费用/滑点/仓位** 的语义统一起来，避免“指标很好看但不可信”。
5. **评估体系升级**：除了你已有的 `total_return/max_drawdown/sharpe/win_rate`，补上策略研究常用的关键指标和诊断输出。

### 0.2 非目标（V2.3 先不碰）

- 多交易所撮合、订单簿级撮合、延迟/部分成交建模（太重）
- 多策略组合调度器（先把单策略实验框架打牢）
- Web Dashboard（先保证 CLI + 报告产出）

---

## 1. 现状复盘（基于你仓库里已实现的 V2.2 能力）

你现在已经有：

- `engine/batch_backtest.py`：支持 sweep、输出 CSV、并尝试画热力图
- `engine/walkforward.py`：支持分段 train(sweep)+test(backtest) 的 walk-forward
- `risk/manager.py`：已加入“日损触发后不再刷 warning”、支持名义裁剪等细节
- `main.py`：统一 CLI 子命令 runner/backtest/sweep/walkforward

**最大短板**：策略/指标/回测耦合仍偏紧，导致：

- 做新指标要改策略文件
- 做多指标组合实验不优雅
- 研究结果难以“复现实验”和比较

---

## 2. V2.3 设计原则：把系统拆成 4 个层

> 你问“是不是没解耦？别人做因子库组合实验”——是的，V2.3 就把这块补齐。

### 2.1 数据层（Data）

- 负责：加载、对齐、清洗、重采样、缓存
- 输出：统一的 `CandleFrame`（pandas DataFrame 或你自定义轻量结构）

### 2.2 因子层（Factors / Features）

- 负责：给 `CandleFrame` 添加列（feature columns）
- 例：`ma_5`, `ma_20`, `rsi_14`, `atr_14`, `vol_zscore_60` …
- 关键：**纯函数化**，不依赖 broker/risk，不产生交易动作

### 2.3 信号层（Signals / Strategy）

- 输入：带 features 的数据
- 输出：标准化 `OrderSignal`（buy/sell/flat + reason + strength 可选）
- 策略只关心“何时进出”，不关心“怎么成交/怎么计费”

### 2.4 执行层（Execution: Broker + Risk + Sizer）

- Broker：成交仿真、费用/滑点、持仓/现金、equity curve、trade log
- Risk：风控过滤（你已有基础）
- Sizer：仓位与下单量（从策略/风险里再拆出来）

---

## 3. 目录结构调整（建议）

在不大改你当前结构的前提下新增：

```text
ZenithAlgo/
  factors/
    base.py            # Factor 抽象/协议
    ma.py              # MA 因子
    rsi.py             # RSI 因子（V2.3 新增示例）
    atr.py             # ATR 因子（用于止损/仓位）
    registry.py        # 因子注册表（字符串 -> 实现）
  research/
    experiment.py      # 统一实验入口（run_experiment）
    report.py          # 生成 markdown/html 报告（先 md）
    schemas.py         # ExperimentConfig / Result schema
  sizing/
    base.py
    fixed_notional.py  # 固定名义（用你 yml 里的 trade_notional）
    pct_equity.py      # 按权益比例（position_pct）
  engine/
    backtest_runner.py # 只做 orchestration，少掺策略细节
    batch_backtest.py
    walkforward.py
```

---

## 4. 里程碑拆解（按优先级从“必须”到“加分”）

### M1（必须）：因子库 & 注册机制

**工作项**

- 新增 `factors/base.py`：定义 `Factor` 协议：`name`, `params`, `compute(df)->df`
- 新增 `factors/registry.py`：`register_factor(name, cls)` + `build_factors(cfg)`
- 把 `SimpleMAStrategy` 用到的均线计算迁移到因子层：`factors/ma.py`
- 策略改成：只读取 `df['ma_short']`/`df['ma_long']` 或类似命名

**验收（必须全部满足）**

- [ ] `python -m main backtest --config ...` 能跑通（结果不要求更好，但一致/可解释）
- [ ] 在配置里改 factor 参数，不改策略代码也能生效
- [ ] 因子输出列名稳定且可在日志中打印（debug）

---

### M2（必须）：Sizer 解耦（让 qty 不再到处“顺手改”）

**工作项**

- 新增 `sizing/`：把 yml 的 `backtest.sizing.position_pct/trade_notional` 落地成可切换实现
- `RiskManager.filter_signals` 只做过滤/裁剪，不负责“计算应该下多少”
- `BacktestBroker.execute` 仍负责成交，但 **signal.qty 的来源统一由 sizer 产生**

**验收**

- [ ] 固定名义模式下：`trade_notional=200` 能稳定控制每笔下单名义接近 200（允许因最小步进/裁剪有误差）
- [ ] 按权益比例模式下：持仓名义不超过 `position_pct * equity_base`
- [ ] 风控触发时不刷屏 warning；跨“日”后可 reset 恢复交易

---

### M3（必须）：实验可复现（Experiment Runner）

**工作项**

- 新增 `research/experiment.py`：一个入口 `run_experiment(cfg_path)`，统一产出：
  - `results.json`（含 metrics、params、时间区间、代码版本 hash）
  - `trades.csv`（每笔成交）
  - `equity.csv`（权益曲线）
  - `report.md`（关键图+关键指标）
- sweep/walk-forward 调用 experiment runner，而不是直接散落在不同脚本里
- 在输出目录结构里包含：symbol/interval/start_end/timestamp

**验收**

- [ ] 任意一次 backtest/sweep/walkforward 都会在 `data/experiments/...` 下生成一套完整产物
- [ ] `report.md` 至少包含：参数、总收益、最大回撤、Sharpe、交易次数、权益曲线图路径
- [ ] 结果里记录配置快照（把最终生效的 cfg dump 出来）

---

### M4（加分但强烈建议）：指标体系升级 + 回测诊断

**工作项**

- 在 metrics 里新增：
  - `profit_factor`（总盈利/总亏损绝对值）
  - `expectancy`（单笔期望）
  - `avg_trade_return`、`std_trade_return`
  - `exposure`（持仓时间占比）
  - `turnover`（换手/交易频率）
- 输出基本诊断图：
  - equity、drawdown（你已有）
  - trade PnL 分布
  - rolling sharpe（可选）
- 统一 max_drawdown 的符号约定（建议输出 **正数**，表示 “回撤幅度”）

**验收**

- [ ] `metrics` 字段包含上述新增项（允许部分为 0，但不能缺失 key）
- [ ] `max_drawdown` 不再出现“有时正有时负”的混乱（统一口径）

---

### M5（加分）：更好用的热力图/研究输出（解决“只有 16 个格子很简陋”）

热力图格子少，常见原因：

- sweep 维度太少（只画 short x long 两维）
- 过滤条件把大量组合过滤掉（min_trades/max_dd/min_sharpe）

**工作项**

- `plot_sweep_heatmap` 支持：
  - 选择 metric（score/return/sharpe/dd）
  - 对其它维度做固定值切片（例如固定 min_ma_diff=0.5）
  - 自动生成多张图（对每个 min_ma_diff / cooldown 生成一张）
- 在 sweep 输出中保存 “被过滤原因统计”（多少组合因为 min_trades 被丢）

**验收**

- [ ] 对同一份 sweep CSV，可以输出 ≥3 张不同切片热力图
- [ ] report.md 中能看到“过滤统计”和“最佳参数在哪张图/哪个格子”

---

## 5. 测试计划（你接下来要测哪些功能）

### 5.1 单元测试（建议用 pytest）

- factors：
  - MA/RSI/ATR 对一段固定数据输出列长度正确、无 NaN 爆炸
- sizing：
  - fixed_notional：名义误差范围
  - pct_equity：不超过上限
- risk：
  - 日损触发后：`filter_signals` 永远返回空；跨日 reset 后恢复
- metrics：
  - max_drawdown 口径一致；profit_factor 在全亏损时不崩

### 5.2 集成测试（CLI）

- [ ] `python -m main backtest --config config/config.yml`
- [ ] `python -m main sweep --config config/config.yml --top-n 5`
- [ ] `python -m main walkforward --config config/config.yml --n-segments 3`
- [ ] 每个命令都能产出 experiment artifacts（M3）

---

## 6. 交付物清单（V2.3 Done 的标准）

- [ ] `factors/` 因子库 + registry + 至少 3 个因子（MA/RSI/ATR）
- [ ] `sizing/` 两种仓位方法可切换
- [ ] `research/experiment.py` + 统一落盘结构 + `report.md`
- [ ] metrics 扩展 + drawdown 口径统一
- [ ] sweep 热力图增强（多切片/多指标/过滤统计）
- [ ] 最少 10 个 pytest 用例覆盖关键路径

---

## 7. 你现在立刻可以按顺序做的 ToDo（实操版）

1. 先建 `factors/`：把 MA 计算从策略里拔出来（M1）
2. 把 “下单量” 从 strategy/risk 里拔出来：实现 `FixedNotionalSizer`（M2）
3. 做 `research/experiment.py`：把 backtest 结果完整落盘（M3）
4. 把 metrics 补齐 + drawdown 统一（M4）
5. 最后搞热力图增强（M5）

> 先解耦，再优化策略，效率会陡增；否则就是在“泥地里装涡轮增压”。
