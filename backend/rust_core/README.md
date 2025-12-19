# rust_core

Rust 计算层骨架（PyO3 最小示例）。

## 目标

- 提供高性能算子入口（如 MA/RSI/ATR）。
- 先跑通编译与导入流程，再逐步替换 Python 实现。

## 构建方式（本地）

建议使用 `maturin`：

```bash
cd libs/rust_core
uv pip install maturin
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin develop
```

安装后可在 Python 中使用：

```python
import zenithalgo_rust
print(zenithalgo_rust.ma([1, 2, 3, 4, 5], 3))
print(zenithalgo_rust.rsi([1, 2, 3, 4, 5], 3))
print(zenithalgo_rust.atr([2, 3, 4], [1, 1.5, 2], [1.5, 2, 3], 2))
print(zenithalgo_rust.ema([1, 2, 3, 4, 5], 3))
```
