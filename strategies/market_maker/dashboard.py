import asyncio
import time
from collections import deque
from datetime import datetime
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Console
from rich import box

from strategies.market_maker.main import MarketMakerEngine

class MarketMakerDashboard:
    def __init__(self, symbols, dry_run=True):
        self.symbols = symbols
        self.engine = MarketMakerEngine(symbols, dry_run=dry_run)
        self.dry_run = dry_run
        
        # 禁止引擎直接打印，改由 Dashboard 接管
        self.engine.suppress_logs = True
        self.engine.on_tick_callback = self.on_data_update
        
        # 数据缓存
        self.history = deque(maxlen=20)  # 最近20条日志
        self.balances = {'USDT': 0.0}  # 账户余额
        self.last_balance_update = 0  # 上次更新时间
        
        self.market_data = {
            sym: {
                'price': 0.0, 
                'bid': 0.0, 
                'ask': 0.0, 
                'spread': 0.0,
                'inventory': 0.0,
                'last_update': datetime.now()
            } for sym in symbols
        }
        
    def on_data_update(self, data):
        """引擎回调：接收实时数据"""
        sym = data['symbol']
        self.market_data[sym] = {
            'price': data['ref_price'],
            'bid': data['bid'],
            'ask': data['ask'],
            'spread': data['spread_pct'],
            'inventory': data['inventory'],
            'last_update': datetime.fromtimestamp(data['timestamp'])
        }
        
        # 添加到日志窗口
        log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {sym:<8} Quote: {data['bid']:.4f} / {data['ask']:.4f} (Spr: {data['spread_pct']:.3f}%)"
        self.history.append(log_msg)

    def generate_table(self) -> Table:
        """生成行情表格"""
        table = Table(box=box.ROUNDED, expand=True)
        table.add_column("Symbol", style="cyan", no_wrap=True)
        table.add_column("Ref Price (Binance)", justify="right", style="green")
        table.add_column("My Bid", justify="right", style="blue")
        table.add_column("My Ask", justify="right", style="magenta")
        table.add_column("Spread %", justify="right")
        table.add_column("Inventory", justify="right", style="yellow")
        table.add_column("Last Update", justify="center", style="dim")
        
        for sym in self.symbols:
            d = self.market_data.get(sym, {})
            if d['price'] > 0:
                # 颜色高亮
                spread_style = "red" if d['spread'] < 0 else "green"
                
                table.add_row(
                    sym,
                    f"${d['price']:.4f}",
                    f"{d['bid']:.4f}",
                    f"{d['ask']:.4f}",
                    f"[{spread_style}]{d['spread']:.3f}%[/{spread_style}]",
                    f"{d['inventory']:.2f}",
                    d['last_update'].strftime('%H:%M:%S')
                )
            else:
                table.add_row(sym, "-", "-", "-", "-", "-", "Waiting...")
                
        return table
    
    def generate_balance_panel(self) -> Table:
        """生成账户余额面板"""
        table = Table(box=box.SIMPLE, show_header=True, expand=False)
        table.add_column("Asset", style="cyan", width=10)
        table.add_column("Balance", justify="right", style="yellow", width=15)
        
        # USDT 余额
        usdt_bal = self.balances.get('USDT', 0.0)
        table.add_row("USDT", f"{usdt_bal:.2f}")
        
        # 各币种余额
        for sym in self.symbols:
            coin = sym.split('/')[0]
            bal = self.balances.get(coin, 0.0)
            if bal > 0.001:  # 只显示有余额的
                table.add_row(coin, f"{bal:.4f}")
        
        return table
    
    def generate_order_panel(self) -> Panel:
        """生成订单状态面板"""
        from rich.text import Text
        
        # 统计信息
        total_orders = self.engine.executor.total_orders if hasattr(self.engine, 'executor') else 0
        order_history = self.engine.executor.order_history if hasattr(self.engine, 'executor') else []
        
        # 构建显示文本
        lines = []
        lines.append(f"📊 Total Orders: {total_orders}")
        lines.append(f"🟢 Active: 0")  # 当前未实现真实下单
        lines.append("")
        lines.append("📜 Recent Orders:")
        
        if order_history:
            for order in list(order_history)[-5:]:  # 最近5笔
                from datetime import datetime
                time_str = datetime.fromtimestamp(order['time']).strftime('%H:%M:%S')
                lines.append(f"  {time_str} {order['symbol']}")
                lines.append(f"  B:{order['bid']:.2f} A:{order['ask']:.2f}")
        else:
            lines.append("  No orders yet")
        
        content = "\n".join(lines)
        return Panel(
            Text(content, style="white"),
            title="📋 Orders",
            border_style="green",
            box=box.ROUNDED
        )

    def generate_log_panel(self) -> Panel:
        """生成日志面板"""
        log_text = "\n".join(self.history)
        return Panel(
            Text(log_text, style="white"),
            title="📜 Live Activity Log",
            border_style="blue",
            box=box.ROUNDED
        )

    def make_layout(self) -> Layout:
        """构建界面布局"""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=2),
            Layout(name="footer", size=10)
        )
        
        # 主体区域分左右两列
        layout["main"].split_row(
            Layout(name="market", ratio=3),
            Layout(name="sidebar", ratio=1)
        )
        
        # Header
        mode_indicator = "🔴 LIVE MODE" if not self.dry_run else "🟢 DRY RUN"
        layout["header"].update(
            Panel(
                Text(f"🚀 ZenithAlgo - MEXC Market Maker  |  {mode_indicator}", 
                     justify="center", style="bold white"),
                style="on blue"
            )
        )
        
        # 市场表格
        layout["market"].update(
            Panel(self.generate_table(), title="📊 Market Status")
        )
        
        # 侧边栏分上下两部分
        layout["sidebar"].split_column(
            Layout(name="balance", ratio=1),
            Layout(name="orders", ratio=1)
        )
        
        # 余额面板
        layout["balance"].update(
            Panel(self.generate_balance_panel(), title="💰 Account")
        )
        
        # 订单面板
        layout["orders"].update(
            self.generate_order_panel()
        )
        
        # Footer (Logs)
        layout["footer"].update(self.generate_log_panel())
        
        return layout

    async def run(self):
        """运行即时面板"""
        # 1. 启动引擎 (后台任务)
        engine_task = asyncio.create_task(self.engine.start())
        
        # 2. 启动 UI 循环
        try:
            with Live(self.make_layout(), refresh_per_second=4, screen=True) as live:
                loop_count = 0
                while True:
                    # 每 10 秒更新一次余额（避免频繁调用 API）
                    if loop_count % 40 == 0:  # 优化：20 -> 40 (10秒)
                        try:
                            self.balances = await self.engine.fetch_account_balances()
                        except Exception as e:
                            pass  # 静默失败，使用旧数据
                    
                    live.update(self.make_layout())
                    await asyncio.sleep(0.25)
                    loop_count += 1
                    
                    # 如果引擎挂了，退出
                    if engine_task.done():
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self.engine.running = False
            # Ensure engine task is cancelled if it's still running
            if not engine_task.done():
                engine_task.cancel()
            
            try:
                await engine_task
            except asyncio.CancelledError:
                pass

# ===== 启动入口 =====
if __name__ == "__main__":
    import argparse
    from strategies.market_maker.core.scanner import MarketScanner
    
    # 强制预加载环境变量 (在所有逻辑之前)
    import os
    from dotenv import load_dotenv
    env_path = os.path.abspath("config/.env")
    load_dotenv(env_path)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='⚠️ 开启实盘交易 (LIVE TRADING)')
    parser.add_argument('--auto-discover', action='store_true', help='自动发现新币种')
    parser.add_argument('--limit', type=int, default=5, help='显示数量限制')
    args = parser.parse_args()
    
    if args.live:
        print("\n" + "="*50)
        print("🚨🚨🚨 DANGER: LIVE TRADING MODE ENABLED 🚨🚨🚨")
        print("Make sure you have MEXC_API_KEY set in .env")
        print("="*50 + "\n")
        time.sleep(3)
    
    if args.auto_discover:
        print("🔍 Scanning for safe opportunities...")
        # 只选择价格 > $10 的主流大盘币（AS 模型更稳定）
        potential = [
            'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT',
            'XRP/USDT', 'AVAX/USDT', 'LINK/USDT', 'LTC/USDT', 'UNI/USDT'
        ]
        scanner = MarketScanner()
        targets = scanner.scan_opportunities(potential)[:args.limit]
        print(f"✅ Auto-selected: {targets}")
    else:
        targets = ['ETH/USDT', 'SOL/USDT', 'PEPE/USDT']
        
    dashboard = MarketMakerDashboard(targets, dry_run=not args.live)
    
    try:
        asyncio.run(dashboard.run())
    except KeyboardInterrupt:
        print("停止仪表盘...")
