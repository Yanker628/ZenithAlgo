# ZenithAlgo 架构（当前实现）

## 1. 唯一入口

- 运行入口统一为 `backend/main.py`：
  - `python3 backend/main.py runner`
  - `python3 backend/main.py backtest`
  - `python3 backend/main.py sweep`
  - `python3 backend/main.py walkforward`
  - `python3 backend/main.py vector`

目的：避免“同一件事多套入口”导致的口径漂移（配置优先级/产物结构/指标口径不一致）。

## 2. 关键分层（以当前目录为准）

- `backend/zenith/core/`：执行引擎层（数据推进 + 调度）
  - `trading_engine.py`：实盘/纸面/干跑主循环
  - `backtest_engine.py`：单次回测
  - `walkforward_engine.py`：滚动窗口验证
  - `vector_backtest.py`：向量化回测（Rust 模拟）
  - `signal_pipeline.py`：共享信号处理管线（Strategy→Sizing→Risk→Broker）
- `backend/zenith/strategies/`：策略层（只输出方向与理由）
  - `risk/`：风控层（过滤/裁剪信号）
  - `sizing/`：仓位管理
  - `factors/`：指标/因子库
- `backend/zenith/execution/`：执行层（broker、撮合、账户）
  - `backtest_broker.py` / `paper_broker.py` / `live_broker.py`
- `backend/zenith/data/`：行情与数据加载（实时 client + 历史 loader + 数据集 store）
- `backend/zenith/analysis/`：研究/实验与报告（产物落盘、可视化、可复现）
- `backend/zenith/common/`：配置、模型、通用工具
- `backend/zenith/extensions/`：Rust/外部加速封装
- `backend/rust_core/`：Rust 模拟核心（向量化回测）

## 3. 主流程依赖图（当前实现）

```
backend/main.py
  |-- runner
  |     -> zenith/core/trading_engine.py
  |        -> zenith/core/signal_pipeline.py
  |        -> zenith/strategies/*
  |        -> zenith/strategies/risk/*
  |        -> zenith/strategies/sizing/*
  |        -> zenith/execution/*
  |        -> zenith/data/*
  |
  |-- backtest / sweep / walkforward
  |     -> zenith/analysis/research/experiment.py
  |        -> zenith/core/backtest_engine.py
  |        -> zenith/core/walkforward_engine.py
  |        -> zenith/data/*
  |        -> zenith/analysis/metrics/*
  |        -> zenith/analysis/reports/*
  |
  |-- vector
  |     -> zenith/core/vector_backtest.py
  |        -> zenith/extensions/rust_wrapper.py
  |        -> rust_core (zenithalgo_rust)
```

## 4. 次要模块清单（独立/辅助）

- `backend/api/`：Go API 服务（独立入口，不参与 Python 主流程）
- `frontend/`：前端 UI（独立项目）
- `backend/scripts/`：迁移/导入脚本（需单独运行）
- `backend/tests/`：测试集（`python3 backend/main.py test` 才会执行）
- `docs/`：文档库（架构/流程/合同）

## 5. 现货语义（强约束）

- 不做空；`sell` 仅用于平已有持仓；禁止产生负仓位。
