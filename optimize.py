import pandas as pd
import itertools
from strategies.macd_cross import strategy as macd_strategy
from core.backtest import VectorBacktester
import os

# 1. 加载数据 (只读一次，提速)
# 优先级：Binance 下载的 1d 数据 > sample_btc
data_path = "data/ETH_USDT_1d.csv" 
if not os.path.exists(data_path):
    data_path = "data/sample_eth.csv"

if not os.path.exists(data_path):
    print("❌ 错误：未找到数据文件！请先在 Dashboard 下载数据。")
    exit()

print(f"📂 正在从 {data_path} 加载数据...")
df = pd.read_csv(data_path, parse_dates=True, index_col=0)
# 标准化列名
df.columns = [c.lower() for c in df.columns]

# 2. 调整参数搜索范围 (给 ETH "降级")
param_grid = {
    'fast': [12],
    'slow': [26],
    'atr_multiplier': [2.0, 3.0, 4.0],  # SOL可能需要 4.0?
    'trailing_pct':   [0.05, 0.10, 0.15],
    
    # --- ✨ 重点：放宽 ADX 范围 ---
    # 测试一下 15 和 20，看看是不是 25 太高了
    'adx_limit': [15, 20, 25] 
}

# 生成所有组合 (Cartesian Product)
keys, values = zip(*param_grid.items())
combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]

print(f"🚀 即将开始暴力回测，共计 {len(combinations)} 组参数组合...")

results = []

# 3. 开始循环回测
for i, params in enumerate(combinations):
    bt = VectorBacktester(df)
    # 运行策略
    try:
        res = bt.run(macd_strategy, **params)
        metrics = res.metrics
        
        # 记录结果
        record = params.copy()
        record['Total Return'] = metrics.get('Total Return', -1)
        record['Max Drawdown'] = metrics.get('Max Drawdown', -1)
        record['Sharpe'] = metrics.get('Sharpe', 0)
        
        results.append(record)
    except Exception as e:
        print(f"Skipping combination {params} due to error: {e}")
    
    # 进度显示
    if (i + 1) % 20 == 0:
        print(f"⏳ 进度: {i + 1}/{len(combinations)}...")

# 4. 分析结果
if not results:
    print("\n❌ 错误：没有任何有效的回测结果。请检查策略函数参数！")
    exit()

res_df = pd.DataFrame(results)

# 按照 'Total Return' (总收益) 排序
print("\n🏆 --- 收益前 5 名 (Best Returns) ---")
top_returns = res_df.sort_values(by='Total Return', ascending=False).head(5)
print(top_returns)

# 按照 'Sharpe' (夏普比率/性价比) 排序
print("\n💎 --- 性价比前 5 名 (Highest Sharpe) ---")
top_sharpe = res_df.sort_values(by='Sharpe', ascending=False).head(5)
print(top_sharpe)

# 保存到 CSV 供进一步分析
res_df.to_csv("optimization_results.csv", index=False)
print("\n✅ 所有结果已保存至 `optimization_results.csv`。快用 Excel 去寻找“版本答案”吧！")
