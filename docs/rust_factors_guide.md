# Rust 算子迁移指南（模板版）

目标：让每个算子迁移都遵循同一套路，减少重复劳动。

## 1. Rust 侧（libs/rust_core/src/lib.rs）

新增一个 Rust 函数，并导出到 Python。

模板：

```rust
/// 算子说明（中文）。
/// - values: 输入序列
/// - window: 窗口长度
#[pyfunction]
fn your_factor(values: Vec<f64>, window: usize) -> PyResult<Vec<f64>> {
    if window == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err("window 必须大于 0"));
    }
    let n = values.len();
    let mut out = vec![f64::NAN; n];
    // TODO: 填算法逻辑
    Ok(out)
}

#[pymodule]
fn zenithalgo_rust(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(your_factor, m)?)?;
    Ok(())
}
```

## 2. Python 侧（algo/factors/*.py）

默认优先使用 Rust，失败自动回退。

模板：

```python
from shared.utils.logging import setup_logger

_LOGGER = setup_logger("factor-xxx")
_RUST_LOGGED = False
_FALLBACK_LOGGED = False

def compute(...):
    try:
        import zenithalgo_rust
    except Exception:
        zenithalgo_rust = None
    if zenithalgo_rust is not None:
        global _RUST_LOGGED
        if not _RUST_LOGGED:
            _LOGGER.info("XXXFactor 使用 Rust 算子加速。")
            _RUST_LOGGED = True
        # TODO: 调用 rust 函数
        return df
    global _FALLBACK_LOGGED
    if not _FALLBACK_LOGGED:
        _LOGGER.warning("XXXFactor Rust 算子不可用，回退到 pandas。")
        _FALLBACK_LOGGED = True
    # TODO: pandas 实现
    return df
```

## 3. 一致性测试（tests/test_rust_factor_parity.py）

新增一条 Rust vs pandas 对齐测试，Rust 不可用时自动 skip。

模板：

```python
def test_rust_xxx_parity():
    rust = pytest.importorskip("zenithalgo_rust")
    # 构造输入数据
    rust_vals = rust.xxx(...)
    pandas_vals = ...
    _assert_series_close(rust_vals, pandas_vals)
```

## 4. 快速命令

- 构建/安装：`make rust-dev`
- 运行对齐测试：`make rust-test`
