# 向量化回测输入契约（信号序列）

目标：用统一的“信号序列”驱动向量化回测，确保与实盘撮合逻辑一致。

## 1. 信号序列字段

每条信号是一条 dict，字段含义如下：

- `ts`：信号时间（ISO8601 字符串或 datetime）
- `side`：`"buy"` / `"sell"`
- `qty`：下单数量；若为 `0` 或缺省，按 sizing 配置自动计算
- `price`：可选价格；缺省时使用该 bar 的 `close`

示例：

```python
signals = [
    {"ts": "2024-01-01T02:00:00Z", "side": "buy", "qty": 0.0},
    {"ts": "2024-01-01T04:00:00Z", "side": "sell", "qty": 0.0},
]
```

## 2. 关键语义

- **撮合逻辑**：复用 `BacktestFillSimulator`，包含手续费/滑点
- **仓位与风控**：复用 `size_signals` + `RiskManager`
- **价格对齐**：信号 `ts` 会匹配对应 bar 的 `close` 作为成交价（除非传 `price`）
- **方向语义**：现货语义，不做空；`sell` 仅平仓

## 3. 最小使用方式（手动驱动）

```python
from engine.vector_backtest import run_signal_vectorized

result = run_signal_vectorized(
    cfg_obj=cfg,
    price_df=price_df,     # 含 end_ts/close 的 DataFrame
    signals=signals,
)
print(result.metrics)
```

## 4. simple_ma / trend_filtered 试点（已内置）

当前内置适配器：`simple_ma`、`trend_filtered`。

当 `backtest.sweep.vectorized=true` 且 `strategy.type=simple_ma` 时，
会自动走向量化回测，无需手动传 signals。

配置示例：

```yaml
backtest:
  sweep:
    enabled: true
    vectorized: true
strategy:
  type: simple_ma
  params:
    short_window: 5
    long_window: 20
```

`trend_filtered` 同理：

```yaml
backtest:
  sweep:
    enabled: true
    vectorized: true
strategy:
  type: trend_filtered
  params:
    short_window: 10
    long_window: 60
    slope_threshold: 0.1
```

## 5. 迁移其它策略的建议

只要策略能输出 `signals` 序列，就可以接入向量化回测：

1. 运行策略生成 signals  
2. 调用 `run_signal_vectorized(...)`  
3. 对齐 `BacktestEngine` 输出结果（指标/权益曲线）

这样可以保证回测与实盘逻辑一致，便于逐步替换事件驱动回测。

## 6. 对齐验证流程（建议每次接入新策略时做一次）

目标：确保向量化结果与事件驱动回测一致，避免逻辑漂移。

步骤：

1. 先跑一轮 sweep（`backtest.sweep.vectorized=true`）。
2. 从 `sweep.csv` 选一组参数（建议取 score 最高或你关注的组合）。
3. 把该参数写回 `backtest.strategy.params`（与 sweep 保持一致）。
4. 跑一次 backtest。
5. 对比两者的关键指标：`total_return/max_drawdown/sharpe/total_trades`。

示例命令：

```bash
.venv/bin/python main.py sweep --config config/config.yml
.venv/bin/python main.py backtest --config config/config.yml
```

对齐标准：数值完全一致或仅有浮点级别误差（1e-12 量级）。

自动化脚本（推荐）：

```bash
.venv/bin/python utils/sweep_parity_check.py --config config/config.yml --sample-size 3 --sample-mode random
```
