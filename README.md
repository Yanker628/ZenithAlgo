# ZenithAlgo

<div align="center">

**一个专业的事件驱动量化交易系统**

[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/Code%20Style-PEP8-orange.svg)](https://pep8.org/)

</div>

## 📖 简介

ZenithAlgo 是一个基于 Python 的事件驱动量化交易系统，专为加密货币交易设计。系统采用模块化架构，支持实时交易、回测、参数优化和 Walk-Forward 验证，同时内置完善的风险管理机制。

### ✨ 核心特性

- **🚀 事件驱动架构**：基于 Tick/K 线事件的高性能交易引擎
- **📊 多模式运行**：支持 dry-run、paper trading、live-testnet、live-mainnet 四种模式
- **🔒 完善风控**：日损限制、仓位控制、白名单机制、价格偏离保护
- **📈 专业回测**：支持手续费、滑点模拟、多品种回测、参数网格搜索
- **🎯 Walk-Forward 验证**：自动时间切片训练/测试，避免过拟合
- **📉 可视化分析**：自动生成资金曲线、回撤图、收益分布、参数热力图
- **🔐 安全设计**：API 密钥环境变量管理、多重保险丝保护、精度校验
- **🧪 完整测试**：单元测试覆盖核心模块，支持离线/在线测试分离

## 🏗️ 系统架构

```text
ZenithAlgo/
├── documents/           # 文档库（架构/流程/实践）
├── engine/              # 交易引擎
│   ├── base_engine.py        # 引擎基类（模板模式）
│   ├── trading_engine.py     # 实盘/纸面/干跑引擎
│   ├── backtest_engine.py    # 单次回测引擎
│   ├── optimization_engine.py # 参数优化/批量回测（研究入口）
│   ├── walkforward_engine.py # Walk-Forward 引擎
│   └── signal_pipeline.py    # 策略→sizing→风控→执行管线
├── algo/                # 核心算法模块
│   ├── factors/         # 因子/特征库
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── ma.py
│   │   ├── rsi.py
│   │   └── atr.py
│   ├── strategy/        # 策略模块
│   │   ├── base.py          # 策略基类
│   │   └── simple_ma.py     # 简单均线策略示例
│   ├── sizing/          # 仓位/下单量
│   │   ├── base.py
│   │   ├── fixed_notional.py
│   │   └── pct_equity.py
│   └── risk/            # 风险管理
│       └── manager.py       # 风控管理器
├── broker/              # 交易接口
│   ├── abstract_broker.py    # 抽象 Broker + 运行模式
│   ├── backtest_broker.py    # 回测 Broker（撮合/手续费/滑点）
│   ├── paper_broker.py       # dry-run / paper（本地记账）
│   ├── live_broker.py        # live-*（真实下单）
│   ├── order_manager.py      # 订单管理器（预留）
│   ├── execution/            # 执行模型（滑点/撮合等）
│   └── accounts/             # 账户模型（预留）
├── market_data/         # 行情数据
│   ├── client.py        # 行情客户端（实时/模拟）
│   ├── loader.py        # 历史数据加载/下载（CSV + REST）
│   └── models.py        # 数据模型
├── prompts/             # 提示词资产（预留）
├── libs/                # 核心实现骨架（预留）
├── common/              # 通用模型（预留）
├── database/            # 存储适配（预留）
├── external/            # 外部依赖登记（预留）
├── backups/             # 备份脚本（预留）
├── utils/               # 工具模块
│   ├── config_loader.py # 配置加载
│   ├── data_loader.py   # 历史数据加载
│   ├── metrics.py       # 绩效指标计算
│   ├── param_search.py  # 参数搜索
│   ├── plotter.py       # 可视化工具
│   └── trade_logger.py  # 交易日志
├── research/            # 实验与报告
│   ├── experiment.py
│   ├── report.py
│   └── schemas.py
├── config/              # 配置文件
│   ├── config.example.yml  # 配置示例
│   └── config.yml       # 实际配置（需自行创建）
└── tests/               # 测试套件
```

## 🚀 快速开始

### 环境要求

- Python 3.13+ (推荐 3.11+)
- pip 或 uv 包管理器

### 安装步骤

1. **克隆仓库**

```bash
git clone <your-repo-url>
cd ZenithAlgo
```

1. **创建虚拟环境**

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

1. **安装依赖**

```bash
pip install -e .
# 或使用 uv
uv pip install -e .
```

1. **配置环境变量**

```bash
# 创建 .env 文件（可选，程序会自动加载）
export BINANCE_API_KEY="your_api_key"
export BINANCE_API_SECRET="your_api_secret"
```

1. **配置系统**

```bash
# 复制示例配置
cp config/config.example.yml config/config.yml
# 编辑 config/config.yml，设置交易对、策略参数等
```

### 运行示例

唯一入口：`main.py`（开发阶段避免入口分裂）。

**实时交易（Paper Trading / Dry-run / Live）**

```bash
python3 main.py runner --config config/config.yml
# 不写子命令时默认 runner:
python3 main.py --config config/config.yml
# dry-run/测试想跑有限 tick:
python3 main.py runner --max-ticks 200
```

**单次回测**

```bash
python3 main.py backtest --config config/config.yml
```

**参数网格搜索**

```bash
python3 main.py sweep --config config/config.yml
```

**Walk-Forward 验证**

```bash
python3 main.py walkforward --config config/config.yml
```

V2.3 起，`backtest/sweep/walkforward` 会把实验产物统一落盘到 `results/`
（含 `results.json`、`report.md`、配置快照，以及回测的 `trades.csv/equity.csv` 等）。

2.4-0 起，实验目录还会包含：

- `summary.md`：快速抓重点（验收点）
- sweep 可视化对任意参数维度（>=1）都能产出至少 1 张图：2D heatmap（>=2 维）/ 1D 曲线（=1 维）/ 参数重要性（兜底）
- `meta.json`：实验元信息（含 `config_hash/data_hash/git.dirty`）
- `summary.json`：标准化总结（`metrics/diagnostics/policy/artifacts`）

运行测试（默认跳过 live）：

```bash
python3 main.py test
```

## 🧰 开发命令

```bash
make help
make test
make lint  # 需要 npm install -g markdownlint-cli
```

## 📚 使用指南

### 运行模式

系统支持四种运行模式，通过 `config.yml` 中的 `mode` 字段配置：

| 模式           | 行情源   | 交易执行     | 适用场景               |
| -------------- | -------- | ------------ | ---------------------- |
| `dry-run`      | 模拟数据 | Mock Broker  | 策略开发、快速测试     |
| `paper`        | 真实行情 | 纸面交易     | 策略验证、实盘前测试   |
| `live-testnet` | 真实行情 | Testnet 下单 | 实盘接口测试           |
| `live-mainnet` | 真实行情 | 真实下单     | **生产环境（需谨慎）** |

说明：

- `dry-run/paper/live-*` 当前按现货语义处理：`sell` 只会平掉已有持仓，不会产生负仓位（默认不做空）。

### 配置说明

#### 基础配置

```yaml
symbol: "BTCUSDT" # 交易对
timeframe: "1h" # 时间周期
mode: "paper" # 运行模式
equity_base: 10000 # 初始资金（用于计算百分比）
```

#### 交易所配置

```yaml
exchange:
  name: "binance"
  base_url: "https://api.binance.com"
  ws_url: "wss://stream.binance.com:9443/ws"
  api_key: "${BINANCE_API_KEY}" # 从环境变量读取
  api_secret: "${BINANCE_API_SECRET}" # 从环境变量读取
  allow_live: false # 安全保险丝
  symbols_allowlist: ["BTCUSDT"] # 交易白名单
```

#### 策略配置

```yaml
strategy:
  type: "simple_ma"
  short_window: 7 # 短期均线周期
  long_window: 120 # 长期均线周期
  min_ma_diff: 0.5 # 最小均线差值（去抖动）
  cooldown_secs: 60 # 信号冷却时间（秒）
```

#### 风控配置

```yaml
risk:
  max_position_pct: 0.3 # 最大仓位比例（30%）
  max_daily_loss_pct: 0.05 # 单日最大亏损（5%）
```

#### 下单规模配置（runner/paper/live）

```yaml
sizing:
  position_pct: 0.2 # 单品种最大持仓占 equity_base 比例
  trade_notional: 200 # 单笔最大名义
# runner/paper 会优先使用该 sizing；若缺省则复用 backtest.sizing
```

#### 回测配置

```yaml
backtest:
  data_dir: "dataset/history"
  # 仓库默认不提交历史 CSV：请自行放入 `{symbol}_{interval}.csv`，或开启 auto_download 自动补齐
  symbol: "BTCUSDT"
  interval: "1h"
  start: "2021-01-01T00:00:00Z"
  end: "2024-12-01T00:00:00Z"
  initial_equity: 1000
  auto_download: true # 自动下载缺失数据
  record_equity_each_bar: false # true=逐bar MTM（更真实），false=仅成交点（更快）

  fees:
    maker: 0.0002 # Maker 手续费 0.02%
    taker: 0.0004 # Taker 手续费 0.04%
    slippage_bp: 1.0 # 滑点 1bp

  sizing:
    position_pct: 0.2 # 最大持仓比例
    trade_notional: 200 # 单笔最大名义价值

  # 因子（V2.3）：策略只读取列名，不再在策略内硬编码指标计算
  factors:
    - name: "ma"
      params: { window: 10, price_col: "close", out_col: "ma_short" }
    - name: "ma"
      params: { window: 50, price_col: "close", out_col: "ma_long" }
    - name: "rsi"
      params: { period: 14, price_col: "close", out_col: "rsi_14" }
    - name: "atr"
      params: { period: 14, out_col: "atr_14" }

  # 回测策略（可选）：若你修改因子输出列名，可在这里改 short_feature/long_feature
  strategy:
    short_feature: "ma_short"
    long_feature: "ma_long"
```

### 策略开发

实现自定义策略只需继承 `Strategy` 基类：

```python
from algo.strategy.base import Strategy
from shared.models.models import Tick, OrderSignal

class MyStrategy(Strategy):
    def on_tick(self, tick: Tick) -> list[OrderSignal]:
        # 你的策略逻辑
        # 只表达方向/理由，真实下单数量交给 sizing 层统一计算
        if ...:
            return [OrderSignal(symbol=tick.symbol, side="buy", qty=0.0, reason="my_signal")]
        return []
```

策略 qty 约定：

- `qty <= 0`：表示“方向信号”，由 `sizing` 计算真实数量（runner/paper/backtest 共用）。
- `qty > 0`：表示策略希望的目标数量，但仍会被 `sizing`/`risk` 裁剪到上限。

### 回测与优化

**单次回测**

- 修改 `config.yml` 中的 `backtest` 配置
- 运行 `python main.py backtest --config config/config.yml`
- 结果输出到控制台，并落盘到 `results/backtest/.../` 目录
- 回测中若现金不足会自动缩量成交，日志/指标记录的是“真实成交量”。

**参数搜索**

- 在 `backtest.sweep` 中配置参数网格
- 运行 `python main.py sweep --config config/config.yml`
- 结果保存到 `results/sweep/.../<symbol>/sweep.csv`

**最优参数生成**

```bash
python -m utils.best_params \
  --cfg config/config.yml \
  --sweep results/sweep/.../BTCUSDT/sweep.csv \
  --min_trades 30 \
  --out config/config_best_BTCUSDT_1h.yml
```

**可视化**

```python
from analysis.visualizations.plotter import plot_equity_curve, plot_drawdown
# 自动生成图表到 plots/ 目录
```

## 🔒 安全建议

1. **API 密钥管理**

   - ✅ 使用环境变量，不要硬编码
   - ✅ 配置文件使用占位符 `${BINANCE_API_KEY}`
   - ✅ 本地配置文件（`config.local.yml`）已加入 `.gitignore`

2. **实盘交易保护**

   - ✅ `allow_live: false` 默认阻断真实下单
   - ✅ 使用 `symbols_allowlist` 限制交易品种
   - ✅ 设置合理的 `min_notional` 和 `min_qty`
   - ✅ 先在 testnet 环境测试

3. **风控设置**
   - ✅ 设置合理的 `max_daily_loss_pct`
   - ✅ 限制 `max_position_pct` 避免过度杠杆
   - ✅ 定期检查交易日志

## 🧪 测试

运行测试套件：

```bash
# 所有测试
pytest

# 特定测试文件
pytest tests/test_strategy_and_risk.py

# 在线接口测试（需要 API Key）
LIVE_TESTS=1 pytest -m live
```

## 📊 性能指标

系统计算以下回测指标：

- **收益指标**：总收益率、年化收益率
- **风险指标**：最大回撤、Sharpe 比率、Sortino 比率
- **交易统计**：交易次数、胜率、平均盈亏、盈亏比
- **可视化**：资金曲线、回撤曲线、收益分布、参数热力图

## 🛠️ 开发指南

### 代码规范

- 遵循 PEP 8 代码风格
- 使用类型提示（Type Hints）
- 函数和类添加文档字符串
- 使用 `snake_case` 命名函数和变量
- 使用 `CamelCase` 命名类

### 提交规范

- 建议遵循简化 Conventional Commits：`feat|fix|docs|test|chore|refactor: scope – summary`
- summary 可用中文或英文，但要能一眼看懂“改了什么/影响范围”

### 项目结构

项目采用模块化设计，各模块职责清晰：

- **engine/**：交易引擎，负责事件循环和流程控制
- **algo/strategy/**：策略模块，实现交易逻辑
- **algo/risk/**：风险管理，过滤和限制交易信号
- **broker/**：交易接口，封装交易所 API
- **market_data/**：行情数据，提供实时和历史数据
- **utils/**：工具函数，配置、日志、指标计算等

## 📝 更新日志

### V2.2 (当前版本)

- ✅ Walk-Forward 验证支持
- ✅ 参数搜索可视化（热力图）
- ✅ 自动最优参数生成
- ✅ 回测结果可视化增强

### V2.1

- ✅ 参数网格搜索
- ✅ 手续费和滑点模拟
- ✅ 多品种回测支持

### V2.0

- ✅ 离线回测引擎
- ✅ 历史数据自动下载
- ✅ 回测绩效指标计算

### V1.2

- ✅ 策略去抖动
- ✅ 交易记录持久化
- ✅ PnL 结构优化
- ✅ 日内重置机制

### V1.1

- ✅ 真实交易所行情
- ✅ Binance Broker 实现
- ✅ 运行模式支持
- ✅ 安全与配置管理

### V1.0

- ✅ 事件驱动框架
- ✅ 基础策略实现
- ✅ 风控模块
- ✅ Mock Broker

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## ⚠️ 免责声明

本系统仅供学习和研究使用。使用本系统进行实盘交易存在资金损失风险，作者不对任何交易损失负责。请在使用前充分测试，并确保理解所有风险。

## 📄 许可证

MIT License

---

<div align="center">

**Made with ❤️ for algorithmic trading**

[查看详细文档](ROADMAP.md) | [报告问题](issues) | [功能建议](issues)

</div>
