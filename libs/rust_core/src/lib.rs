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

/// 计算滚动标准差。
/// - values: 输入序列
/// - period: 周期长度（必须 > 0）
#[pyfunction]
fn stddev(values: Vec<f64>, period: usize) -> PyResult<Vec<f64>> {
    if period == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "period 必须大于 0",
        ));
    }
    let n = values.len();
    let mut out = vec![f64::NAN; n];
    if n == 0 {
        return Ok(out);
    }
    
    // Welford's algorithm or Naive two-pass? 
    // For simplicity and vector speed, let's use the naive rolling window sum of squares approach
    // Var = E[X^2] - (E[X])^2
    // But precision issues might arise.
    // Let's stick to a simple loop for clarity and safety first.
    
    // Rolling variance
    for i in 0..n {
        if i + 1 >= period {
            let slice = &values[i + 1 - period..=i];
            let mut sum = 0.0;
            let mut count = 0;
            for v in slice {
                if !is_nan(*v) {
                    sum += v;
                    count += 1;
                }
            }
            if count > 0 {
                let mean = sum / count as f64;
                let mut sum_sq_diff = 0.0;
                for v in slice {
                    if !is_nan(*v) {
                        sum_sq_diff += (v - mean).powi(2);
                    }
                }
                // Sample standard deviation (divide by N-1, unless N=1)
                if count > 1 {
                    out[i] = (sum_sq_diff / (count as f64 - 1.0)).sqrt();
                } else {
                     out[i] = 0.0;
                }
            }
        }
    }
    Ok(out)
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

/// 模拟交易执行 (支持 SL/TP 和 path-dependence)。
///
/// Parameters
/// ----------
/// timestamps: 时间戳 (i64, ms or s)
/// opens: 开盘价序列
/// highs: 最高价序列
/// lows: 最低价序列
/// closes: 收盘价序列
/// signals: 信号序列 (1=Buy, -1=Sell, 0=None)
/// sl_pct: 止损百分比 (e.g., 0.05 for 5%)
/// tp_pct: 止盈百分比 (e.g., 0.10 for 10%)
///
/// Returns
/// -------
/// (equity_curve, trades_list)
/// equity_curve: Vec<(ts, equity)>
/// trades_list: Vec<(entry_ts, exit_ts, entry_price, exit_price, pnl, reason)>
#[pyfunction]
fn simulate_trades_v2(
    timestamps: Vec<i64>,
    opens: Vec<f64>,
    highs: Vec<f64>,
    lows: Vec<f64>,
    closes: Vec<f64>,
    signals: Vec<i32>,
    sl_pct: f64,
    tp_pct: f64,
    allow_short: bool,
) -> PyResult<(Vec<(i64, f64)>, Vec<(i64, i64, f64, f64, f64, String)>)> {
    let n = timestamps.len();
    if opens.len() != n || highs.len() != n || lows.len() != n || closes.len() != n || signals.len() != n {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "All input arrays must have the same length",
        ));
    }

    let mut equity_curve = Vec::with_capacity(n);
    let mut trades = Vec::new();
    
    // 状态变量
    let mut position_size = 0.0; // 1.0 = Long, -1.0 = Short, 0.0 = Flat
    let mut entry_price = 0.0;
    let mut entry_ts = 0;
    let mut cash = 10000.0; // 初始资金，用于计算 equity 曲线趋势（相对值）
    
    for i in 0..n {
        let ts = timestamps[i];
        let op = opens[i];
        let hi = highs[i];
        let lo = lows[i];
        let cl = closes[i];
        let sig = signals[i];

        // 1. 检查当前持仓是否触发 SL/TP (Intra-bar check)
        // 假设顺序：Open -> Low/High -> Close
        // Conservative assumption: Check SL first using High/Low
        
        if position_size != 0.0 {
            let mut exit_price = 0.0;
            let mut reason = "".to_string();
            let mut triggered = false;

            if position_size > 0.0 {
                // Long: Check SL (Low) and TP (High)
                let sl_price = entry_price * (1.0 - sl_pct);
                let tp_price = entry_price * (1.0 + tp_pct);

                if lo <= sl_price {
                    // SL Hit
                    // 如果 Open 已经低于 SL (Gap Down)，则以 Open 成交，否则以 SL 价格成交
                    exit_price = if op < sl_price { op } else { sl_price };
                    reason = "sl".to_string();
                    triggered = true;
                } else if hi >= tp_price {
                    // TP Hit
                    // 如果 Open 已经高于 TP (Gap Up)，则以 Open 成交，否则以 TP 价格成交
                    exit_price = if op > tp_price { op } else { tp_price };
                    reason = "tp".to_string();
                    triggered = true;
                }
            } else if position_size < 0.0 {
                 // Short: Check SL (High) and TP (Low)
                let sl_price = entry_price * (1.0 + sl_pct);
                let tp_price = entry_price * (1.0 - tp_pct);

                if hi >= sl_price {
                     // SL Hit
                    exit_price = if op > sl_price { op } else { sl_price };
                    reason = "sl".to_string();
                    triggered = true;
                } else if lo <= tp_price {
                    // TP Hit
                    exit_price = if op < tp_price { op } else { tp_price };
                    reason = "tp".to_string();
                    triggered = true;
                }
            }

            if triggered {
                // 执行平仓
                let pnl = (exit_price - entry_price) * position_size;
                cash += pnl;
                trades.push((entry_ts, ts, entry_price, exit_price, pnl, reason));
                position_size = 0.0;
                entry_price = 0.0;
                entry_ts = 0;
            }
        }

        // 2. 处理新信号 (Signal Execution)
        // 如果当前是 Flat，检查是否开仓
        // 如果当前有持仓，检查是否反转 (Flip)
        // 假设信号在 Close 时产生，下一个 Bar Open 执行？或者 Current Bar Close 执行？
        // Vector backtest 常用逻辑：Signal at i, Execute at i (Close) or i+1 (Open).
        // 这里为了简化且符合 bar 内撮合逻辑，假设：信号基于 Close 计算，在 NEXT BAR Open 执行？
        // 但这里的输入是 aligned arrays。通常 signal[i] 意味着在 time i 产生的信号。
        // 如果我们要在 time i 执行，意味着我们用 close[i] 成交？
        // 
        // 既然要做“Intra-bar SL/TP”，通常意味着 Entry 是在 Previous Bar Close 或 Current Bar Open。
        // 为了最快模拟，我们假设：
        // Signal[i] 导致在 Close[i] 成交 (简化) 或者我们模拟的是基于 i-1 的信号在 i 的行为？
        // 
        // User request: "传入 (timestamp, ..., signal, ...) ... O(N) loop".
        // 让我们假设 signal[i] 是策略在 i 时刻给出的指令。
        // 如果我们想在 i 时刻就进行 SL/TP 检查，那必须是 i-1 时刻建立的仓位。
        // 
        // 逻辑修正：
        // Loop i:
        //   First: Check intra-bar SL/TP for EXISTING position (from i-1).
        //   Second: Process Signal[i] to Update position for NEXT step (or Close execute now).
        //   If Signal[i] says Buy and we are Flat -> Open Long at Close[i].
        //   If Signal[i] says Sell and we are Long -> Close Long at Close[i].
        //   
        // 这样 SL/TP 会在 持仓后的 每一个 Bar (i+1...) 进行检查。
        
        // 处理信号
        if sig != 0 {
             // 简化：全部按 Close 价成交
             // 如果有反向持仓，先平仓
             if position_size != 0.0 && ((sig == 1 && position_size == -1.0) || (sig == -1 && position_size == 1.0)) {
                 let exit_price = cl;
                 let pnl = (exit_price - entry_price) * position_size;
                 cash += pnl;
                 trades.push((entry_ts, ts, entry_price, exit_price, pnl, "signal_flip".to_string()));
                 position_size = 0.0;
             }

             // 开新仓
             if position_size == 0.0 {
                 if sig == 1 {
                     position_size = 1.0;
                     entry_price = cl;
                     entry_ts = ts;
                 } else if sig == -1 {
                     if allow_short {
                         position_size = -1.0;
                         entry_price = cl;
                         entry_ts = ts;
                     }
                 }
             }
        }

        // 记录权益
        // Equity = Cash + Unrealized PnL
        let unrealized_pnl = if position_size != 0.0 {
            (cl - entry_price) * position_size
        } else {
            0.0
        };
        equity_curve.push((ts, cash + unrealized_pnl));
    }

    Ok((equity_curve, trades))
}

/// Python 模块入口。
#[pymodule]
fn zenithalgo_rust(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(ma, m)?)?;
    m.add_function(wrap_pyfunction!(rsi, m)?)?;
    m.add_function(wrap_pyfunction!(atr, m)?)?;
    m.add_function(wrap_pyfunction!(ema, m)?)?;
    m.add_function(wrap_pyfunction!(stddev, m)?)?;
    m.add_function(wrap_pyfunction!(simulate_trades_v2, m)?)?;
    Ok(())
}
