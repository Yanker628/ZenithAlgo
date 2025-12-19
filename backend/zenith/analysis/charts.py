"""交互式图表生成模块 (Plotly)。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objs as go
import plotly.express as px
from plotly.subplots import make_subplots

def plot_equity_interactive(equity_curve: list[tuple]) -> str:
    """生成交互式权益曲线 HTML。
    
    Args:
        equity_curve: List of (datetime, equity_value)
    
    Returns:
        HTML div string.
    """
    if not equity_curve:
        return "<div>No data for equity curve</div>"
        
    df = pd.DataFrame(equity_curve, columns=["Time", "Equity"])
    df["Time"] = pd.to_datetime(df["Time"])
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["Time"], 
        y=df["Equity"],
        mode='lines',
        name='Equity',
        line=dict(color='#00E396', width=2)
    ))
    
    fig.update_layout(
        title="Equity Curve",
        xaxis_title="Time",
        yaxis_title="Equity",
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=40, b=20),
        height=400
    )
    
    return fig.to_html(full_html=False, include_plotlyjs='cdn')

def plot_drawdown_interactive(equity_curve: list[tuple]) -> str:
    """生成交互式回撤曲线 HTML。"""
    if not equity_curve:
        return "<div>No data for drawdown curve</div>"
        
    df = pd.DataFrame(equity_curve, columns=["Time", "Equity"])
    df["Time"] = pd.to_datetime(df["Time"])
    
    # Calculate Drawdown
    df["Peak"] = df["Equity"].cummax()
    df["Drawdown"] = (df["Equity"] - df["Peak"]) / df["Peak"]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["Time"], 
        y=df["Drawdown"],
        mode='lines',
        name='Drawdown',
        fill='tozeroy',
        line=dict(color='#FF4560', width=1)
    ))
    
    fig.update_layout(
        title="Drawdown",
        xaxis_title="Time",
        yaxis_title="Drawdown",
        yaxis=dict(tickformat=".1%"),
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=40, b=20),
        height=300
    )
    
    return fig.to_html(full_html=False, include_plotlyjs=False)

def plot_heatmap(df: pd.DataFrame, x_col: str, y_col: str, metric: str) -> str:
    """生成参数热力图 HTML。"""
    if df.empty or x_col not in df.columns or y_col not in df.columns or metric not in df.columns:
        return f"<div>No data for heatmap: {x_col} vs {y_col}</div>"
    
    # Pivot for heatmap
    pivot = df.pivot_table(index=y_col, columns=x_col, values=metric, aggfunc='mean')
    
    fig = px.imshow(
        pivot,
        labels=dict(x=x_col, y=y_col, color=metric),
        x=pivot.columns,
        y=pivot.index,
        aspect="auto",
        color_continuous_scale="Viridis"
    )
    
    fig.update_layout(
        title=f"Parameter Heatmap: {metric} ({x_col} vs {y_col})",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=40, b=20),
        height=500
    )
    
    return fig.to_html(full_html=False, include_plotlyjs=False)
