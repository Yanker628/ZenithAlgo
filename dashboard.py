import streamlit as st
import pandas as pd
import os
import importlib.util
import inspect
from core.backtest import VectorBacktester

st.set_page_config(page_title="ZenithAlgo Lite - 极简向量化回测", layout="wide")

st.title("⚡ ZenithAlgo Lite - 极简向量化回测")

# --- Sidebar: Configuration ---
st.sidebar.header("1. 数据选择")
data_dir = "data"

# --- Data Downloader Section ---
with st.sidebar.expander("📥 下载新数据 (Download Data)"):
    import ccxt
    
    dl_symbol = st.text_input("交易对 (Symbol)", "BTC/USDT").upper()
    dl_timeframe = st.selectbox("时间周期 (Timeframe)", ["1d", "4h", "1h", "15m", "5m"], index=0)
    dl_limit = st.number_input("K线数量 (Limit)", value=1000, step=100)
    
    if st.button("开始下载 (Download)"):
        with st.spinner(f"正在从 Binance 下载 {dl_symbol}..."):
            try:
                exchange = ccxt.binance()
                ohlcv = exchange.fetch_ohlcv(dl_symbol, timeframe=dl_timeframe, limit=dl_limit)
                
                if not ohlcv:
                    st.error("未获取到数据，请检查交易对名称。")
                else:
                    # Convert to DataFrame
                    data_df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    data_df['date'] = pd.to_datetime(data_df['timestamp'], unit='ms')
                    data_df.set_index('date', inplace=True)
                    data_df.drop(columns=['timestamp'], inplace=True)
                    
                    # Save to CSV
                    safe_symbol = dl_symbol.replace("/", "_")
                    filename = f"{data_dir}/{safe_symbol}_{dl_timeframe}.csv"
                    data_df.to_csv(filename)
                    st.success(f"已保存: `{filename}` ({len(data_df)} bars)")
                    
                    # Force reload to update file list (Streamlit hack: just wait for user to interact or rerun)
                    # st.experimental_rerun()  # Deprecated in newer versions, let's just ask user to refresh selectbox
                    
            except Exception as e:
                st.error(f"下载失败: {e}")

if not os.path.exists(data_dir):
    os.makedirs(data_dir)
    st.sidebar.warning(f"已创建 {data_dir}。请将 CSV 文件放入该目录。")

files = [f for f in os.listdir(data_dir) if f.endswith(".csv")]
if not files:
    st.sidebar.error("在 data/ 目录中未找到 CSV 文件")
    data_file = None
else:
    data_file = st.sidebar.selectbox("选择数据集", files)

st.sidebar.header("2. 策略选择")
strategies_dir = "strategies"
strategy_files = [f for f in os.listdir(strategies_dir) if f.endswith(".py") and f not in ["__init__.py", "config.py"]]
selected_strategy_file = st.sidebar.selectbox("选择策略", strategy_files)

# --- Main Logic ---

if data_file and selected_strategy_file:
    # 1. Load Data
    data_path = os.path.join(data_dir, data_file)
    try:
        df = pd.read_csv(data_path, parse_dates=True, index_col=0)
        # Standardize columns
        df.columns = [c.lower() for c in df.columns]
        st.write(f"已加载 **{len(df)}** 条 K 线数据，来自 `{data_file}`")
        
        # Show raw data preview
        with st.expander("原始数据预览 (Raw Data Preview)"):
            st.dataframe(df.head())

    except Exception as e:
        st.error(f"加载数据出错: {e}")
        st.stop()

    # 2. Load Strategy
    try:
        spec = importlib.util.spec_from_file_location("strategy_module", os.path.join(strategies_dir, selected_strategy_file))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        strategy_func = getattr(module, "strategy")
        
        # 2.2 Load Asset Specific Config (Unified Source)
        from strategies.config import get_strategy_config
        strategy_config = get_strategy_config(data_file)
        asset_params = strategy_config.get("params", {})
        
        st.sidebar.info(f"📊 {strategy_config.get('description', '默认配置')}")
        
        # Inspect parameters to create UI widgets dynamically
        sig = inspect.signature(strategy_func)
        params = {}
        
        st.sidebar.subheader("策略参数 (Strategy Parameters)")
        for name, param in sig.parameters.items():
            if name == "df": continue # Skip dataframe argument
            
            # 优先从统一配置中心获取默认值
            default_val = asset_params.get(name, param.default)
            if default_val == inspect.Parameter.empty:
                default_val = 0
            
            if isinstance(default_val, int):
                params[name] = st.sidebar.number_input(name, value=int(default_val), step=1)
            elif isinstance(default_val, float):
                # 针对百分比参数设置更精细的步长
                step = 0.01 if "pct" in name else 0.1
                params[name] = st.sidebar.number_input(name, value=float(default_val), step=step)
            else:
                params[name] = st.sidebar.text_input(name, value=str(default_val))
                
    except Exception as e:
        st.error(f"加载策略出错: {e}")
        st.stop()

    # 3. Run Backtest Button
    if st.sidebar.button("🚀 运行回测 (Run Backtest)"):
        with st.spinner("正在执行向量化回测..."):
            try:
                bt = VectorBacktester(df)
                result = bt.run(strategy_func, **params)
                
                # --- Results Display ---
                st.subheader("回测结果 (Backtest Results)")
                
                # Metrics
                m = result.metrics
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("总收益率 (Total Return)", f"{m.get('Total Return', 0):.2%}")
                c2.metric("年化收益率 (CAGR)", f"{m.get('CAGR', 0):.2%}")
                c3.metric("夏普比率 (Sharpe)", f"{m.get('Sharpe', 0):.2f}")
                c4.metric("最大回撤 (Max Drawdown)", f"{m.get('Max Drawdown', 0):.2%}")
                
                # Charts
                st.subheader("权益曲线 (Equity Curve)")
                
                # 合并策略权益和基准权益以便绘图
                chart_data = pd.DataFrame({
                    "策略净值 (Strategy)": result.equity_curve,
                    "基准净值 (Benchmark)": result.benchmark_equity
                })
                # 显式指定颜色：策略(蓝色), 基准(橙色)
                st.line_chart(chart_data, color=["#2962FF", "#FF9800"])
                
                # --- ✨ 新增：展示交易记录 ---
                st.subheader("交易记录 (Trade Log - 为什么亏钱?)")
                if not result.trades.empty:
                    # 按照盈亏排序，先看亏得最惨的
                    st.dataframe(
                        result.trades.sort_values(by="PnL", ascending=True)
                        .style.format({"Entry Price": "{:.2f}", "Exit Price": "{:.2f}", "PnL %": "{:.2f}%"})
                    )
                else:
                    st.info("本次回测未产生交易 (No trades generated).")
                
                # Signals overlay (Optional / Simplified)
                # st.subheader("Signals")
                # st.line_chart(result.signals)

            except Exception as e:
                st.exception(e)
else:
    st.info("请确保 `data/` 目录中有 CSV 数据，并且 `strategies/` 目录中有策略文件。")

# --- Instructions ---
with st.sidebar:
    st.markdown("---")
    st.markdown("**ZenithAlgo Lite**")
    st.markdown("极简向量化回测系统")
