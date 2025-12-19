# Backtest 逻辑梳理（当前实现）

## 1. 数据流

`BacktestEngine`（`engine/backtest_engine.py`）的主循环可以按“一根 K 线 = 一个 tick”理解：

1. `market_data/loader.py` 加载 K 线 CSV（可选通过 Binance REST 补齐缺失区间）
2. `algo/factors/` 计算特征列并写入 DataFrame
3. 遍历每根 bar 构造 `Tick`（推荐从 `market_data/models.py` 导入；特征写入 `Tick.features`）
4. 每个 tick：
   - `engine/signal_pipeline.py`：Strategy → Sizing → Risk 生成可执行信号
   - `broker/backtest_broker.py` 撮合成交并记录 trade/equity
5. 结束后计算 `analysis/metrics/metrics.py` 指标，并可选输出 trades/equity/图表（实验落盘统一在 `results/`）

## 2. equity_curve 口径（可配置）

`backtest.record_equity_each_bar`：

- `false`（默认）：仅在成交时点记录权益（更快，但 Sharpe/回撤口径更粗）
- `true`：逐 bar mark-to-market 记录权益（更适合严肃评估 Sharpe/回撤）
