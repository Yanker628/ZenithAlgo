import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from analysis.visualizations.plotter import _prepare_heatmap_pivot, plot_sweep_heatmap

csv_path = "results/sweep_engine/SOLUSDT/SOLUSDT_1h_sweep.csv"
try:
    df = pd.read_csv(csv_path)
    print("Dtypes:")
    print(df.dtypes)
    print("\nHead:")
    print(df.head())
    
    pivot = _prepare_heatmap_pivot(
        df, 
        x_param="short_window", 
        y_param="long_window", 
        value_param="score",
        filters={"min_trades": 5}, # as used in engine
        mask_filtered=False
    )
    print("\nPivot Table (Mean Score):")
    print(pivot)
    
    # Check specific cell
    check = df[(df["long_window"]==60) & (df["short_window"]==30)]
    print("\nEntries for 60,30:")
    print(check[["score", "passed"]])
    print("Mean:", check["score"].mean())

    # Try plotting
    # plot_sweep_heatmap(csv_path, save_path="debug_heatmap.png")
    # print("Plot saved to debug_heatmap.png")

except Exception as e:
    print(e)
