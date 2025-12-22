"""
MEXC 价差对比分析工具

实时对比我们的报价 vs MEXC 真实价差
帮助优化做市参数
"""

import ccxt
import asyncio
import time
from datetime import datetime
from collections import deque
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich import box

console = Console()

class SpreadAnalyzer:
    def __init__(self, symbols=['BTC/USDT', 'ETH/USDT', 'SOL/USDT']):
        self.symbols = symbols
        self.mexc = ccxt.mexc()
        
        # 数据收集
        self.spread_history = {sym: deque(maxlen=100) for sym in symbols}
        self.start_time = time.time()
        
    def fetch_mexc_orderbook(self, symbol):
        """获取 MEXC 真实订单簿"""
        try:
            ob = self.mexc.fetch_order_book(symbol, limit=5)
            
            if not ob['bids'] or not ob['asks']:
                return None
            
            best_bid = ob['bids'][0][0]
            best_ask = ob['asks'][0][0]
            mid_price = (best_bid + best_ask) / 2
            spread_pct = (best_ask - best_bid) / mid_price * 100
            
            return {
                'bid': best_bid,
                'ask': best_ask,
                'mid': mid_price,
                'spread_pct': spread_pct,
                'timestamp': time.time()
            }
        except Exception as e:
            console.print(f"[red]Error fetching {symbol}: {e}[/red]")
            return None
    
    def calculate_our_quotes(self, mid_price, sigma=0.0004):
        """计算我们的报价（使用当前算法）"""
        spread_pct = sigma * 50  # 0.002 * 50 = 0.1%
        spread_pct = max(0.01, min(spread_pct, 0.5))
        
        half_spread = mid_price * spread_pct / 100 / 2
        
        our_bid = mid_price - half_spread
        our_ask = mid_price + half_spread
        
        return {
            'bid': our_bid,
            'ask': our_ask,
            'spread_pct': spread_pct
        }
    
    def generate_table(self, data):
        """生成对比表格"""
        table = Table(title="📊 MEXC 价差对比分析", box=box.ROUNDED)
        
        table.add_column("Symbol", style="cyan", no_wrap=True)
        table.add_column("MEXC Bid", justify="right", style="green")
        table.add_column("MEXC Ask", justify="right", style="red")
        table.add_column("MEXC Spread", justify="right", style="yellow")
        table.add_column("Our Bid", justify="right", style="blue")
        table.add_column("Our Ask", justify="right", style="magenta")
        table.add_column("Our Spread", justify="right", style="yellow")
        table.add_column("Competitive?", justify="center")
        
        for symbol, info in data.items():
            if not info:
                continue
            
            mexc = info['mexc']
            ours = info['ours']
            
            # 竞争力分析
            if ours['spread_pct'] < mexc['spread_pct']:
                competitive = "[green]✅ 更窄[/green]"
            elif ours['spread_pct'] < mexc['spread_pct'] * 1.2:
                competitive = "[yellow]⚠️ 接近[/yellow]"
            else:
                competitive = "[red]❌ 太宽[/red]"
            
            table.add_row(
                symbol,
                f"{mexc['bid']:.2f}",
                f"{mexc['ask']:.2f}",
                f"{mexc['spread_pct']:.3f}%",
                f"{ours['bid']:.2f}",
                f"{ours['ask']:.2f}",
                f"{ours['spread_pct']:.3f}%",
                competitive
            )
        
        return table
    
    def collect_statistics(self):
        """统计分析"""
        stats = {}
        
        for symbol in self.symbols:
            if not self.spread_history[symbol]:
                continue
            
            spreads = [s['spread_pct'] for s in self.spread_history[symbol]]
            stats[symbol] = {
                'avg': sum(spreads) / len(spreads),
                'min': min(spreads),
                'max': max(spreads),
                'count': len(spreads)
            }
        
        return stats
    
    async def run_analysis(self, duration_minutes=60):
        """运行分析（默认1小时）"""
        console.print(f"[bold green]开始价差分析...[/bold green]")
        console.print(f"[yellow]将运行 {duration_minutes} 分钟[/yellow]\n")
        
        end_time = time.time() + duration_minutes * 60
        
        with Live(self.generate_table({}), refresh_per_second=1) as live:
            while time.time() < end_time:
                data = {}
                
                for symbol in self.symbols:
                    mexc_data = self.fetch_mexc_orderbook(symbol)
                    
                    if mexc_data:
                        # 保存历史
                        self.spread_history[symbol].append({
                            'spread_pct': mexc_data['spread_pct'],
                            'timestamp': time.time()
                        })
                        
                        # 计算我们的报价
                        our_quotes = self.calculate_our_quotes(mexc_data['mid'])
                        
                        data[symbol] = {
                            'mexc': mexc_data,
                            'ours': our_quotes
                        }
                
                # 更新显示
                live.update(self.generate_table(data))
                
                await asyncio.sleep(2)  # 每2秒更新一次
        
        # 显示统计结果
        self.show_statistics()
    
    def show_statistics(self):
        """显示统计结果"""
        console.print("\n[bold cyan]📊 统计分析结果[/bold cyan]\n")
        
        stats = self.collect_statistics()
        
        table = Table(title="MEXC 价差统计（过去数据）", box=box.ROUNDED)
        table.add_column("Symbol", style="cyan")
        table.add_column("平均价差", justify="right", style="yellow")
        table.add_column("最小价差", justify="right", style="green")
        table.add_column("最大价差", justify="right", style="red")
        table.add_column("样本数", justify="right")
        
        for symbol, stat in stats.items():
            table.add_row(
                symbol,
                f"{stat['avg']:.3f}%",
                f"{stat['min']:.3f}%",
                f"{stat['max']:.3f}%",
                str(stat['count'])
            )
        
        console.print(table)
        
        # 参数调优建议
        self.suggest_parameters(stats)
    
    def suggest_parameters(self, stats):
        """参数调优建议"""
        console.print("\n[bold green]🎯 参数调优建议[/bold green]\n")
        
        for symbol, stat in stats.items():
            avg_spread = stat['avg']
            
            # 计算建议的 sigma
            # 目标：我们的价差 = MEXC 平均价差 * 0.8（略窄一点更有竞争力）
            target_spread = avg_spread * 0.8
            suggested_sigma = target_spread / 50  # 因为 spread = sigma * 50
            
            current_sigma = 0.002
            current_spread = current_sigma * 50
            
            console.print(f"[cyan]{symbol}:[/cyan]")
            console.print(f"  MEXC 平均价差: {avg_spread:.3f}%")
            console.print(f"  当前设置 (sigma={current_sigma}): {current_spread:.3f}%")
            console.print(f"  [yellow]建议 sigma: {suggested_sigma:.4f}[/yellow]")
            console.print(f"  预期价差: {target_spread:.3f}%")
            
            if target_spread < current_spread:
                console.print(f"  💡 [green]可以缩窄价差以提高竞争力[/green]")
            else:
                console.print(f"  ✅ [green]当前设置已经很有竞争力[/green]")
            console.print()

if __name__ == "__main__":
    import sys
    
    # 参数：运行时长（分钟）
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    
    analyzer = SpreadAnalyzer()
    
    try:
        asyncio.run(analyzer.run_analysis(duration_minutes=duration))
    except KeyboardInterrupt:
        console.print("\n[yellow]分析中断，显示当前统计...[/yellow]")
        analyzer.show_statistics()
