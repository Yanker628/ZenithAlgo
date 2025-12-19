"""研究报告生成器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pandas as pd
from datetime import datetime

from analysis.charts import plot_equity_interactive, plot_drawdown_interactive, plot_heatmap

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ZenithAlgo Research Report - {title}</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #1e1e1e; color: #e0e0e0; margin: 0; padding: 20px; }}
        .container {{ max_width: 1200px; margin: 0 auto; }}
        h1, h2, h3 {{ color: #ffffff; }}
        .card {{ background: #2d2d2d; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; }}
        .metric-item {{ background: #363636; padding: 15px; border-radius: 6px; text-align: center; }}
        .metric-val {{ font-size: 24px; font-weight: bold; color: #00E396; }}
        .metric-label {{ font-size: 14px; color: #aaaaaa; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #444; }}
        th {{ background: #333; }}
        tr:hover {{ background: #3a3a3a; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
        .badge-pass {{ background: #00E396; color: #000; }}
        .badge-fail {{ background: #FF4560; color: #fff; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Research Report: {title}</h1>
        <p>Generated at: {gen_time}</p>
        
        <!-- Summary Metrics -->
        <div class="card">
            <h2>Summary Metrics</h2>
            <div class="metrics-grid">
                {metrics_html}
            </div>
        </div>
        
        <!-- Charts Area -->
        <div class="card">
            {charts_html}
        </div>
        
        <!-- Parameter Sweep Analysis (if applicable) -->
        {sweep_html}
        
    </div>
</body>
</html>
"""

class ReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        if not self.output_dir.exists():
            raise FileNotFoundError(f"Directory not found: {output_dir}")
            
    def generate(self) -> Path:
        """生成 HTML 报告。"""
        # Determine type: Sweep or Single Backtest
        sweep_csv = list(self.output_dir.rglob("sweep.csv"))
        
        if sweep_csv:
            return self._generate_sweep_report(sweep_csv[0])
        else:
            # Fallback to single backtest (checking for summary.json)
            summary_json = self.output_dir / "summary.json"
            if summary_json.exists():
                return self._generate_backtest_report(summary_json)
            else:
                raise ValueError("No valid results found (summary.json or sweep.csv)")

    def _generate_backtest_report(self, summary_path: Path) -> Path:
        """单次回测报告。"""
        with open(summary_path) as f:
            summary = json.load(f)
            
        metrics = summary.get("metrics", {})
        
        # Load Equity Curve from result.json (if available, summary usually lacks full curve)
        # Try finding results.json in sibling dirs or same dir
        # Assuming typical structure
        
        # For simplicity, if we cannot find full equity curve easily without huge 'results.json', 
        # we skip charts or try to load 'results.json' if it exists.
        charts_html = "<p>No equity curve data available for visualization.</p>"
        
        results_json = self.output_dir / "results.json"
        if results_json.exists():
            try:
                with open(results_json) as f:
                    res = json.load(f)
                    curve = res.get("equity_curve", [])
                    if curve:
                         # curve is list of [ts, value]
                         c_html = plot_equity_interactive(curve)
                         dd_html = plot_drawdown_interactive(curve)
                         charts_html = f"<h3>Equity Curve</h3>{c_html}<h3>Drawdown</h3>{dd_html}"
            except Exception:
                pass

        metrics_html = self._render_metrics(metrics)
        
        html = TEMPLATE.format(
            title=f"Backtest {summary.get('custom_alias', 'Result')}",
            gen_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            metrics_html=metrics_html,
            charts_html=charts_html,
            sweep_html=""
        )
        
        out_file = self.output_dir / "report.html"
        out_file.write_text(html, encoding="utf-8")
        return out_file

    def _generate_sweep_report(self, csv_path: Path) -> Path:
        """参数扫描报告。"""
        df = pd.read_csv(csv_path)
        
        # Top Metrics (Best based on Sharpe)
        if "sharpe" in df.columns:
            best = df.sort_values("sharpe", ascending=False).iloc[0]
        else:
            best = df.iloc[0]
            
        metrics_html = self._render_metrics(best.to_dict(), label_prefix="Best Run")
        
        # Heatmaps
        # Detect parameters (columns that are not metrics)
        known_metrics = {"total_return", "sharpe", "max_drawdown", "total_trades", "win_rate", "score", "passed", "filter_reason", "symbol"}
        params = [c for c in df.columns if c not in known_metrics]
        
        sweep_html = ""
        if len(params) >= 2:
            x_col = params[0]
            y_col = params[1]
            heatmap = plot_heatmap(df, x_col, y_col, "sharpe")
            sweep_html = f"""
            <div class="card">
                <h2>Parameter Landscape</h2>
                <p>Heatmap showing <strong>Sharpe Ratio</strong> for {x_col} vs {y_col}.</p>
                {heatmap}
            </div>
            """
            
        # Add Top 10 Table
        top_10 = df.sort_values("sharpe", ascending=False).head(10)
        table_html = "<h3>Top 10 Configurations</h3><table><thead><tr>"
        for c in top_10.columns:
            table_html += f"<th>{c}</th>"
        table_html += "</tr></thead><tbody>"
        
        for _, row in top_10.iterrows():
            table_html += "<tr>"
            for item in row:
                if isinstance(item, float):
                    val = f"{item:.4f}"
                else:
                    val = str(item)
                table_html += f"<td>{val}</td>"
            table_html += "</tr>"
        table_html += "</tbody></table>"
        
        sweep_html += f'<div class="card">{table_html}</div>'

        html = TEMPLATE.format(
            title="Parameter Sweep Analysis",
            gen_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            metrics_html=metrics_html,
            charts_html="", # Sweep summary doesn't have single equity curve
            sweep_html=sweep_html
        )
        
        out_file = self.output_dir / "report.html"
        out_file.write_text(html, encoding="utf-8")
        return out_file

    def _render_metrics(self, metrics: dict, label_prefix: str = "") -> str:
        html = ""
        # Focus on key metrics
        targets = ["total_return", "sharpe", "max_drawdown", "total_trades", "win_rate"]
        for k in targets:
            if k in metrics:
                val = metrics[k]
                if isinstance(val, (float, int)):
                     if "return" in k or "drawdown" in k or "rate" in k:
                         fmt_val = f"{val:.2%}" if abs(val) < 10 else f"{val:.2f}" # Guess percentage
                     else:
                         fmt_val = f"{val:.2f}"
                else:
                    fmt_val = str(val)
                
                label = k.replace("_", " ").title()
                if label_prefix:
                    label = f"{label_prefix} {label}"
                    
                html += f"""
                <div class="metric-item">
                    <div class="metric-val">{fmt_val}</div>
                    <div class="metric-label">{label}</div>
                </div>
                """
        return html
