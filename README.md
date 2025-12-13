# ZenithAlgo

<div align="center">

**一个事件驱动的量化交易系统（研究可复现 + 实盘可恢复）**

[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

## 简介

ZenithAlgo 是一个基于 Python 的事件驱动量化交易系统，面向加密货币现货交易。
系统以“可复现、可回归、可审计、不乱交易”为工程优先级。

演进计划见 `ROADMAP.md`（以仓库代码现状为准）。

## 当前能力（对齐 ROADMAP）

- M4 全面强类型化：配置与核心产物使用 Pydantic schema，未知 key 启动即失败。
- M4 复现契约：研究/回测产物写入 `schema_version`，并包含 `git_sha/config_hash/data_hash/created_at`。
- M5 状态恢复：`client_order_id` 幂等 + SQLite ledger（跨进程）+ 启动对账与安全保险丝。
- M6 数据层升级：进行中（数据集 meta/hash、列式缓存、激活 `database/`）。

## 目录约定（输入 / 输出 / 状态）

- 输入数据：`dataset/history/`（历史行情 CSV；默认 gitignore）。
- 进程状态：`dataset/state/`（SQLite ledger；默认 gitignore）。
- 研究产物：`results/`（统一落盘；默认 gitignore）。
- 数据层（预留）：`database/`（用于 M6 数据层升级；不承载进程状态账本）。
- 文档：`documents/`，路线图：`ROADMAP.md`。

## 快速开始

### 环境要求

- Python 3.13+

### 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 配置

```bash
cp config/config.example.yml config/config.yml
```

环境变量（可选，支持 `.env` / `.env.local` 自动加载）：

```bash
export BINANCE_API_KEY="your_api_key"
export BINANCE_API_SECRET="your_api_secret"
```

### 运行

唯一入口：`main.py`。

```bash
# runner：dry-run / paper / live-*
python3 main.py runner --config config/config.yml

# 单次回测
python3 main.py backtest --config config/config.yml

# 参数搜索（sweep）
python3 main.py sweep --config config/config.yml

# Walk-Forward
python3 main.py walkforward --config config/config.yml
```

运行测试（默认跳过 live）：

```bash
python3 main.py test
```

## 产物与状态

### 研究/回测产物（results）

一次 backtest/sweep/walkforward 会写入：

`results/{task}/{symbol}/{interval}/{start}_{end}/{run_id}/`

目录内至少包含：

- `config.yml`、`effective_config.json`
- `meta.json`、`summary.json`、`results.json`（均含 `schema_version`）

回测类任务还会导出 `trades.csv`、`equity.csv` 与图表（如 `equity.png`）。

### 进程状态账本（dataset/state）

runner（paper/live）模式默认把进程状态写入 `dataset/state/ledger.sqlite3`
（可用 `ledger.path` 修改）。
该账本用于跨进程幂等与恢复，不等同于研究报表产物。

## 配置要点（常用开关）

实盘保险丝与白名单：

```yaml
exchange:
  allow_live: false
  symbols_allowlist: ["BTCUSDT"]
```

启动恢复/对账（对账完成前禁止交易；失败自动只读观察）：

```yaml
recovery:
  enabled: true
  mode: "observe_only" # observe_only | trade
```

本地事件账本（SQLite ledger）：

```yaml
ledger:
  enabled: true
  path: "dataset/state/ledger.sqlite3"
```

sweep 是否额外跑一次“最佳参数单次回测”（默认关闭，避免重复计算）：

```yaml
backtest:
  sweep:
    run_best_backtest: false
```

## 开发命令

```bash
make help
make test
make lint  # 需要 npm install -g markdownlint-cli
```

## 贡献

欢迎提交 Issue 和 Pull Request。

## 免责声明

本系统仅供学习和研究使用。
实盘交易存在资金损失风险，请在充分测试并理解风险后使用。

## 许可证

MIT License（见 `LICENSE`）
