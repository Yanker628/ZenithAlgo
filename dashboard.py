import streamlit as st
import pandas as pd
import os
import importlib.util
import inspect
from core.backtest import VectorBacktester

st.set_page_config(page_title="ZenithAlgo Lite", layout="wide")

st.title("⚡ ZenithAlgo Lite")

# --- Sidebar: Configuration ---
st.sidebar.header("1. Data Selection")
data_dir = "data"
if not os.path.exists(data_dir):
    os.makedirs(data_dir)
    st.sidebar.warning(f"Created {data_dir}. Please put CSV files there.")

files = [f for f in os.listdir(data_dir) if f.endswith(".csv")]
if not files:
    st.sidebar.error("No CSV files found in data/")
    data_file = None
else:
    data_file = st.sidebar.selectbox("Select Dataset", files)

st.sidebar.header("2. Strategy Selection")
strategies_dir = "strategies"
strategy_files = [f for f in os.listdir(strategies_dir) if f.endswith(".py") and f != "__init__.py"]
selected_strategy_file = st.sidebar.selectbox("Select Strategy", strategy_files)

# --- Main Logic ---

if data_file and selected_strategy_file:
    # 1. Load Data
    data_path = os.path.join(data_dir, data_file)
    try:
        df = pd.read_csv(data_path, parse_dates=True, index_col=0)
        # Standardize columns
        df.columns = [c.lower() for c in df.columns]
        st.write(f"Loaded **{len(df)}** bars from `{data_file}`")
        
        # Show raw data preview
        with st.expander("Raw Data Preview"):
            st.dataframe(df.head())

    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.stop()

    # 2. Load Strategy
    try:
        spec = importlib.util.spec_from_file_location("strategy_module", os.path.join(strategies_dir, selected_strategy_file))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        strategy_func = getattr(module, "strategy")
        
        # Inspect parameters to create UI widgets dynamically
        sig = inspect.signature(strategy_func)
        params = {}
        
        st.sidebar.subheader("Strategy Parameters")
        for name, param in sig.parameters.items():
            if name == "df": continue # Skip dataframe argument
            
            default = param.default if param.default != inspect.Parameter.empty else 0
            if isinstance(default, int):
                params[name] = st.sidebar.number_input(name, value=default, step=1)
            elif isinstance(default, float):
                params[name] = st.sidebar.number_input(name, value=default, step=0.1)
            else:
                params[name] = st.sidebar.text_input(name, value=str(default))
                
    except Exception as e:
        st.error(f"Error loading strategy: {e}")
        st.stop()

    # 3. Run Backtest Button
    if st.sidebar.button("🚀 Run Backtest"):
        with st.spinner("Running Vectorized Backtest..."):
            try:
                bt = VectorBacktester(df)
                result = bt.run(strategy_func, **params)
                
                # --- Results Display ---
                st.subheader("Backtest Results")
                
                # Metrics
                m = result.metrics
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Return", f"{m.get('Total Return', 0):.2%}")
                c2.metric("CAGR", f"{m.get('CAGR', 0):.2%}")
                c3.metric("Sharpe Ratio", f"{m.get('Sharpe', 0):.2f}")
                c4.metric("Max Drawdown", f"{m.get('Max Drawdown', 0):.2%}")
                
                # Charts
                st.subheader("Equity Curve")
                st.line_chart(result.equity_curve)
                
                # Signals overlay (Optional / Simplified)
                # st.subheader("Signals")
                # st.line_chart(result.signals)

            except Exception as e:
                st.exception(e)
else:
    st.info("Please ensure data files exist in `ZenithAlgo_Lite/data` and strategies in `ZenithAlgo_Lite/strategies`.")

# --- Instructions ---
with st.sidebar:
    st.markdown("---")
    st.markdown("**ZenithAlgo Lite**")
    st.markdown("Minimalist Vector Backtester")
