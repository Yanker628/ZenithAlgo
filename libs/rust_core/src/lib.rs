use pyo3::prelude::*;

fn is_nan(val: f64) -> bool {
    val.is_nan()
}

fn rolling_mean(values: &[f64], window: usize) -> Vec<f64> {
    let n = values.len();
    let mut out = vec![f64::NAN; n];
    if window == 0 || n == 0 {
        return out;
    }
    let mut sum = 0.0;
    let mut count: usize = 0;
    for i in 0..n {
        let v = values[i];
        if !is_nan(v) {
            sum += v;
            count += 1;
        }
        if i >= window {
            let prev = values[i - window];
            if !is_nan(prev) {
                sum -= prev;
                count -= 1;
            }
        }
        if count >= window {
            out[i] = sum / count as f64;
        }
    }
    out
}

fn ema_series(values: &[f64], period: usize) -> Vec<f64> {
    let n = values.len();
    let mut out = vec![f64::NAN; n];
    if period == 0 || n == 0 {
        return out;
    }
    let alpha = 2.0 / (period as f64 + 1.0);
    let mut ema = values[0];
    for i in 0..n {
        let v = values[i];
        if i == 0 {
            ema = v;
        } else {
            ema = alpha * v + (1.0 - alpha) * ema;
        }
        if i + 1 >= period {
            out[i] = ema;
        }
    }
    out
}

/// 计算简单移动平均（SMA）。
/// - values: 输入序列
/// - window: 窗口长度（必须 > 0）
/// 返回与输入等长的序列，前 window-1 个位置为 NaN。
#[pyfunction]
fn ma(values: Vec<f64>, window: usize) -> PyResult<Vec<f64>> {
    if window == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "window 必须大于 0",
        ));
    }
    let n = values.len();
    let mut out = vec![f64::NAN; n];
    if n == 0 {
        return Ok(out);
    }

    let mut sum = 0.0;
    for i in 0..n {
        sum += values[i];
        if i >= window {
            sum -= values[i - window];
        }
        if i + 1 >= window {
            out[i] = sum / window as f64;
        }
    }
    Ok(out)
}

/// 计算 RSI（SMA 版本）。
/// - values: 输入序列
/// - period: 周期长度（必须 > 0）
/// 返回与输入等长的序列，前 period 个位置为 NaN。
#[pyfunction]
fn rsi(values: Vec<f64>, period: usize) -> PyResult<Vec<f64>> {
    if period == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "period 必须大于 0",
        ));
    }
    let n = values.len();
    let mut gains = vec![f64::NAN; n];
    let mut losses = vec![f64::NAN; n];
    for i in 1..n {
        let delta = values[i] - values[i - 1];
        if delta.is_nan() {
            gains[i] = f64::NAN;
            losses[i] = f64::NAN;
        } else if delta >= 0.0 {
            gains[i] = delta;
            losses[i] = 0.0;
        } else {
            gains[i] = 0.0;
            losses[i] = -delta;
        }
    }

    let avg_gain = rolling_mean(&gains, period);
    let avg_loss = rolling_mean(&losses, period);

    let mut out = vec![f64::NAN; n];
    for i in 0..n {
        let g = avg_gain[i];
        let l = avg_loss[i];
        if is_nan(g) || is_nan(l) {
            out[i] = f64::NAN;
        } else if l == 0.0 {
            out[i] = 100.0;
        } else {
            let rs = g / l;
            out[i] = 100.0 - (100.0 / (1.0 + rs));
        }
    }
    Ok(out)
}

/// 计算 ATR（SMA 版本）。
/// - high: 最高价序列
/// - low: 最低价序列
/// - close: 收盘价序列
/// - period: 周期长度（必须 > 0）
#[pyfunction]
fn atr(high: Vec<f64>, low: Vec<f64>, close: Vec<f64>, period: usize) -> PyResult<Vec<f64>> {
    if period == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "period 必须大于 0",
        ));
    }
    let n = high.len().min(low.len()).min(close.len());
    let mut tr = vec![f64::NAN; n];
    for i in 0..n {
        let h = high[i];
        let l = low[i];
        let tr1 = h - l;
        if i == 0 {
            tr[i] = tr1;
            continue;
        }
        let prev_close = close[i - 1];
        let tr2 = (h - prev_close).abs();
        let tr3 = (l - prev_close).abs();
        let mut max_val = tr1;
        if !tr2.is_nan() && tr2 > max_val {
            max_val = tr2;
        }
        if !tr3.is_nan() && tr3 > max_val {
            max_val = tr3;
        }
        tr[i] = max_val;
    }

    Ok(rolling_mean(&tr, period))
}

/// 计算 EMA（指数移动平均）。
/// - values: 输入序列
/// - period: 周期长度（必须 > 0）
#[pyfunction]
fn ema(values: Vec<f64>, period: usize) -> PyResult<Vec<f64>> {
    if period == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "period 必须大于 0",
        ));
    }
    Ok(ema_series(&values, period))
}

/// Python 模块入口。
#[pymodule]
fn zenithalgo_rust(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(ma, m)?)?;
    m.add_function(wrap_pyfunction!(rsi, m)?)?;
    m.add_function(wrap_pyfunction!(atr, m)?)?;
    m.add_function(wrap_pyfunction!(ema, m)?)?;
    Ok(())
}
