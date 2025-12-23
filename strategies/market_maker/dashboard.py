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
from rich.align import Align

from strategies.market_maker.main import MarketMakerEngine
import logging

class DashboardLogHandler(logging.Handler):
    """Custom handler to redirect logs to Dashboard deque"""
    def __init__(self, log_deque):
        super().__init__()
        self.log_deque = log_deque
        
    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_deque.append(msg)
        except Exception:
            self.handleError(record)

class MarketMakerDashboard:
    def __init__(self, symbols, dry_run=True):
        self.symbols = symbols
        self.engine = MarketMakerEngine(symbols, dry_run=dry_run)
        self.dry_run = dry_run
        
        # 禁止引擎直接打印，改由 Dashboard 接管 (But allow Logging)
        self.engine.suppress_logs = True
        self.engine.on_tick_callback = self.on_data_update

        # 核心状态 (Thread-Safeish since we are using asyncio single thread)
        self.state = {
            'start_time': time.time(),
            'initial_equity': None, # 初始总权益 (USDT + 持仓价值)
            'current_equity': 0.0,
            'usdt_balance': 0.0,
            'positions': {}, # {symbol: {'amount': 0.0, 'value': 0.0, 'price': 0.0}}
            'orders': [],    # Active orders
            'market': {},    # {symbol: {'bid':..., 'ask':..., 'price':...}}
            'logs': deque(maxlen=10)
        }
        
        # 初始化市场数据结构
        for sym in symbols:
            self.state['market'][sym] = {'price': 0.0, 'spread': 0.0}
            self.state['positions'][sym] = {'amount': 0.0, 'value': 0.0}

        # Setup Logging redirection (requires self.state)
        self._setup_logging()

    def _setup_logging(self):
        """Configure logging to output to self.state['logs']"""
        # Remove existing handlers to avoid duplicates/spam
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
            
        # Add our custom handler
        handler = DashboardLogHandler(self.state['logs'])
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

    def on_data_update(self, data):
        """引擎回调：接收实时价格数据 (极高频)"""
        sym = data['symbol']
        details = self.state['market'].get(sym, {})
        details.update({
            'price': data['ref_price'],
            'bid': data['bid'],
            'ask': data['ask'],
            'spread': data['spread_pct']
        })
        self.state['market'][sym] = details
        
        # 记录关键日志 (可选)
        # log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {sym} Quote: {data['bid']:.2f}/{data['ask']:.2f}"
        # self.state['logs'].append(log_msg)
        self.state['last_update'] = time.time()

    async def fetch_background_data(self):
        """后台循环：获取低频数据 (余额、订单)"""
        while True:
            try:
                # 1. 获取余额 (可能耗时)
                balances = await self.engine.fetch_account_balances()
                self.state['usdt_balance'] = balances.get('USDT', 0.0)
                
                # 更新持仓数量 (Dynamic for all assets)
                # 1. Update existing symbols
                for sym in self.symbols:
                    coin = sym.split('/')[0]
                    amt = balances.get(coin, 0.0)
                    self.state['positions'][sym]['amount'] = amt
                
                # 2. Add new assets found in balances
                for coin, amt in balances.items():
                    if coin == 'USDT': continue
                    found = False
                    for sym in self.symbols:
                        if sym.startswith(f"{coin}/"):
                            found = True
                            break
                    if not found and amt > 0:
                        # Create a dummy symbol entry for display
                        dummy_sym = f"{coin}/USDT" # Assumption
                        if dummy_sym not in self.state['positions']:
                            self.state['positions'][dummy_sym] = {'amount': amt, 'value': 0.0}
                            self.state['market'][dummy_sym] = {'price': 0.0, 'spread': 0.0}
                        else:
                            self.state['positions'][dummy_sym]['amount'] = amt
                
                # 2. 获取订单 (从 Executor 内存获取，非 API)
                if hasattr(self.engine, 'executor'):
                    # 这里假设 active_orders 是一个字典
                    # raw_orders = self.engine.executor.active_orders
                    pass
                    
                # 3. 计算总权益 (Mark-to-Market)
                # 3. 计算总权益 (Mark-to-Market)
                total_equity = self.state['usdt_balance']
                # Iterate all known positions
                for sym, pos in self.state['positions'].items():
                    price = self.state['market'].get(sym, {}).get('price', 0)
                    amt = pos.get('amount', 0)
                    
                    if price > 0:
                        val = amt * price
                        self.state['positions'][sym]['value'] = val
                        total_equity += val
                
                self.state['current_equity'] = total_equity
                
                # 如果是第一次获取，记录为初始权益
                if self.state['initial_equity'] is None and total_equity > 0:
                    self.state['initial_equity'] = total_equity
                    self.state['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] 📸 Initial Equity Snapshot: ${total_equity:.2f}")

            except Exception as e:
                self.state['logs'].append(f"[Error] Fetch Data: {str(e)}")
            
            await asyncio.sleep(2) # 2秒刷新一次

    def generate_header(self) -> Panel:
        """顶部 KPI 横幅"""
        equity = self.state['current_equity']
        initial = self.state['initial_equity'] or equity
        
        pnl = equity - initial
        pnl_pct = (pnl / initial * 100) if initial > 0 else 0.0
        
        color = "green" if pnl >= 0 else "red"
        sign = "+" if pnl >= 0 else ""
        
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="center", ratio=1)
        
        # 1. Title
        # 1. Title
        mode = "🔴 LIVE" if not self.dry_run else "🟢 DRY-RUN"
        
        # Heartbeat
        last_upd = self.state.get('last_update', 0)
        hb_color = "green" if time.time() - last_upd < 5 else "red"
        hb_text = datetime.fromtimestamp(last_upd).strftime('%H:%M:%S') if last_upd > 0 else "N/A"

        grid.add_row(
            f"[bold white]🚀 ZenithAlgo MM[/bold white] | {mode}",
            f"[bold yellow]💰 Equity: ${equity:,.2f}[/bold yellow]",
            f"[{color}]📈 PnL: {sign}${abs(pnl):.2f} ({sign}{pnl_pct:.2f}%)[/{color}] \n[dim]🕒 {hb_text}[/dim]"
        )
        
        return Panel(grid, style="on blue")

    def generate_portfolio_panel(self) -> Panel:
        """持仓与资产表格"""
        table = Table(box=box.SIMPLE_HEAD, expand=True)
        table.add_column("Asset", style="cyan bold")
        table.add_column("Holdings", justify="right")
        table.add_column("Price ($)", justify="right")
        table.add_column("Value ($)", justify="right", style="green")
        
        # USDT
        usdt = self.state['usdt_balance']
        table.add_row("USDT", f"{usdt:.4f}", "$1.00", f"${usdt:.2f}")
        
        # Cryptos
        # Iterate over all positions we know about
        for sym, pos in self.state['positions'].items():
            coin = sym.split('/')[0]
            amt = pos.get('amount', 0)
            price = self.state['market'].get(sym, {}).get('price', 0)
            val = pos.get('value', 0)
            
            if amt > 0.0001: # 只显示有持仓的
                table.add_row(
                    coin, 
                    f"{amt:.4f}", 
                    f"{price:.2f}",
                    f"${val:.2f}"
                )
        
        return Panel(table, title="💼 Portfolio & Assets")

    def generate_market_mixed_panel(self) -> Panel:
        """混合面板：上方行情，下方统计"""
        # 上半部分：行情 Table
        table = Table(box=box.SIMPLE_HEAD, expand=True)
        table.add_column("Sym", style="bold white")
        table.add_column("Price", justify="right", style="cyan")
        table.add_column("Spread", justify="right", style="dim white")
        
        for sym in self.symbols:
            m = self.state['market'][sym]
            table.add_row(
                sym.split('/')[0], 
                f"{m.get('price',0):.2f}", 
                f"{m.get('spread',0):.3f}%"
            )

        # 下半部分：最近订单
        # 暂时只用文本列表
        history = self.engine.executor.order_history if hasattr(self.engine, 'executor') else []
        recent_orders = "\n".join([
            f"[dim]{datetime.fromtimestamp(o['time']).strftime('%H:%M:%S')}[/dim] [bold]{o.get('symbol', 'UNKNOWN')}[/bold] {o['side'].upper()} {o['price']}" 
            for o in list(history)[-5:] # Show last 5
        ]) if history else "No active orders"

        from rich.console import Group
        group = Group(
            table,
            Text("\n📜 Recent Orders:", style="bold underline"),
            Text(recent_orders)
        )
        
        return Panel(group, title="⚡ Activity")

    def generate_logs_panel(self) -> Panel:
        """日志"""
        logs = list(self.state['logs'])
        return Panel(Text("\n".join(logs), style="dim white"), title="📜 System Logs", box=box.SIMPLE)

    def make_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=4),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=5)
        )
        layout["body"].split_row(
            Layout(name="portfolio", ratio=6),
            Layout(name="side", ratio=4)
        )
        
        layout["header"].update(self.generate_header())
        layout["portfolio"].update(self.generate_portfolio_panel())
        layout["side"].update(self.generate_market_mixed_panel())
        layout["footer"].update(self.generate_logs_panel())
        return layout

    async def run(self):
        """主入口"""
        # 1. 启动交易引擎
        engine_task = asyncio.create_task(self.engine.start())
        
        # 2. 启动数据后台 (独立循环)
        bg_task = asyncio.create_task(self.fetch_background_data())
        
        # 3. 启动 UI (主循环) - 纯渲染，不await API
        try:
            with Live(self.make_layout(), refresh_per_second=4, screen=True) as live:
                while True:
                    live.update(self.make_layout())
                    await asyncio.sleep(0.2) # 200ms 刷新率
                    
                    if engine_task.done():
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self.engine.running = False
            bg_task.cancel()
            if not engine_task.done():
                engine_task.cancel()
            try:
                await engine_task
            except:
                pass

# ===== 启动入口 (保持不变) =====
if __name__ == "__main__":
    import argparse
    from strategies.market_maker.core.scanner import MarketScanner
    
    import os
    from dotenv import load_dotenv
    env_path = os.path.abspath("config/.env")
    load_dotenv(env_path)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='⚠️ 开启实盘交易 (LIVE TRADING)')
    parser.add_argument('--auto-discover', action='store_true', help='自动发现新币种')
    parser.add_argument('--limit', type=int, default=5, help='显示数量限制')
    parser.add_argument('--discover-mode', type=str, default='low_risk', choices=['low_risk', 'high_spread'], help='选币模式：低风险/高价差')
    parser.add_argument('--symbol', type=str, help='指定交易对，如 SOL/USDT')
    args = parser.parse_args()
    
    if args.live:
        print("\n" + "="*50)
        print("🚨🚨🚨 DANGER: LIVE TRADING MODE ENABLED 🚨🚨🚨")
        print("Make sure you have MEXC_API_KEY set in .env")
        print("="*50 + "\n")
        time.sleep(2)
    
    # 优先使用指定的symbol
    if args.symbol:
        targets = [args.symbol]
    elif args.auto_discover:
        potential = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT',
            'XRP/USDT', 'AVAX/USDT', 'LINK/USDT', 'LTC/USDT', 'UNI/USDT']
        scanner = MarketScanner()
        targets = scanner.scan(potential, mode=args.discover_mode, limit=args.limit)
    else:
        targets = ['ETH/USDT', 'SOL/USDT', 'PEPE/USDT']
        
    dashboard = MarketMakerDashboard(targets, dry_run=not args.live)
    
    try:
        asyncio.run(dashboard.run())
    except KeyboardInterrupt:
        print("停止仪表盘...")
