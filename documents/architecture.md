# ZenithAlgo 架构（当前实现）

## 1. 唯一入口

- 运行入口统一为仓库根目录 `main.py`：
  - `python3 main.py runner`
  - `python3 main.py backtest`
  - `python3 main.py sweep`
  - `python3 main.py walkforward`

目的：避免“同一件事多套入口”导致的口径漂移（配置优先级/产物结构/指标口径不一致）。

## 2. 关键分层

- `engine/`：执行引擎层（数据推进 + 调度）
  - `engine/trading_engine.py`：实盘/纸面/干跑
  - `engine/backtest_engine.py`：单次回测
  - `engine/signal_pipeline.py`：共享信号处理管线（Strategy→Sizing→Risk→Broker）
- `strategy/`：策略层（只输出方向与理由）
- `sizing/` + `utils/sizer.py`：统一下单规模（sizing）
- `risk/`：风控层（过滤/裁剪信号）
- `broker/`：执行层（mock/binance/backtest）
- `market_data/`：行情与数据模型（`Tick/Candle/OrderSignal/Position`）
- `research/`：研究/实验与报告（产物落盘、可视化、可复现）

## 3. 现货语义（强约束）

- 不做空；`sell` 仅用于平已有持仓；禁止产生负仓位。

