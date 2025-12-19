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

## 4. simple_ma 试点（已内置）

当前内置适配器：`simple_ma`。

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

## 5. 迁移其它策略的建议

只要策略能输出 `signals` 序列，就可以接入向量化回测：

1. 运行策略生成 signals  
2. 调用 `run_signal_vectorized(...)`  
3. 对齐 `BacktestEngine` 输出结果（指标/权益曲线）

这样可以保证回测与实盘逻辑一致，便于逐步替换事件驱动回测。
