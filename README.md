# MEXC Market Maker Strategy

基于 Avellaneda-Stoikov 算法的高频做市商策略，支持 MEXC 交易所实盘交易。

## ✨ 核心特性

- 🤖 **智能定价算法**：Avellaneda-Stoikov 模型 + 库存调整
- 📊 **实时监控面板**：Rich TUI 显示账户、订单、市场状态
- 🛡️ **完整风控体系**：币种过滤、价格保护、Oracle 验证
- 🔄 **高可用架构**：REST Polling Fallback（绕过 WebSocket 封锁）
- 💰 **多币种支持**：BTC、ETH、SOL、BNB、XRP 等主流币种

## 🚀 快速开始

### 1. 安装依赖

```bash
# 使用 uv 管理环境（推荐）
uv sync
```

### 2. 配置 API Key

```bash
# 复制配置模板
cp config/.env.example config/.env

# 编辑 config/.env，添加你的 MEXC API Key
# MEXC_API_KEY=your_api_key_here
# MEXC_API_SECRET=your_api_secret_here
```

### 3. 运行策略

**模拟模式**（推荐先测试）：

```bash
uv run python -m strategies.market_maker.dashboard --auto-discover
```

**实盘模式**（小心！）：

```bash
uv run python -m strategies.market_maker.dashboard --live --auto-discover
```

### 参数说明

- `--auto-discover`: 自动筛选适合做市的币种（默认 5 个）
- `--live`: 开启实盘交易（⚠️ 会真实下单）
- `--limit N`: 限制做市币种数量

## 📊 Dashboard 说明

运行后会看到实时仪表盘，包含：

```
┌─ Header ─────────────────────────────┐
│ 🚀 ZenithAlgo | 🟢 DRY RUN / 🔴 LIVE │
├─ 📊 Market Status ─┬─ 💰 Account ────┤
│ BTC/USDT 报价      │ USDT: 100.00    │
│ ETH/USDT 报价      │ BTC:  0.00      │
│                     ├─ 📋 Orders ─────┤
│                     │ Total: 0        │
│                     │ Active: 0       │
├─ 📜 Activity Log ───────────────────┤
│ [时间] ETH/USDT Quote: 3030 / 3031  │
└──────────────────────────────────────┘
```

- **Header**: 显示运行模式（模拟/实盘）
- **Market Status**: 实时报价和价差
- **Account**: 账户余额（每 5 秒更新）
- **Orders**: 订单统计和历史
- **Activity Log**: 最近操作日志

## ⚙️ 配置参数

在 `config/.env` 中可配置：

```bash
# API 密钥
MEXC_API_KEY=your_key
MEXC_API_SECRET=your_secret

# 风控参数
MAX_SINGLE_TRADE_USDT=50      # 单笔最大交易额
MAX_DAILY_LOSS_USDT=100       # 单日最大亏损
MIN_PROFIT_THRESHOLD=0.001    # 最小利润阈值（0.1%）

# 策略参数（可选，代码中已设默认值）
# BASE_SPREAD_PCT=0.1         # 基础价差 0.1%
# POLLING_INTERVAL=1.0        # REST 轮询间隔（秒）
```

## 🏗️ 系统架构

```
┌─────────────────┐
│  Binance Oracle │ (参考价格)
└────────┬────────┘
         │
    ┌────▼────────────────────────┐
    │   Market Maker Engine       │
    │  - AS Algorithm             │
    │  - Inventory Management     │
    │  - Risk Control             │
    └────┬────────────────────┬───┘
         │                    │
    ┌────▼─────┐         ┌───▼──────────┐
    │ MEXC     │         │ High         │
    │ WebSocket│         │ Frequency    │
    │ (Backup) │         │ Executor     │
    └──────────┘         └──────────────┘
         │                    │
         └────────┬───────────┘
              ┌───▼──────┐
              │  MEXC    │
              │Exchange  │
              └──────────┘
```

### 关键模块

- **`strategies/market_maker/core/algo.py`**: Avellaneda-Stoikov 定价算法
- **`strategies/market_maker/core/executor.py`**: 高频订单执行器
- **`strategies/market_maker/core/scanner.py`**: 币种安全筛选器
- **`strategies/market_maker/gateways/mexc_ws.py`**: MEXC WebSocket + REST Polling
- **`strategies/market_maker/gateways/binance_oracle.py`**: Binance 价格 Oracle
- **`strategies/market_maker/main.py`**: 策略引擎主逻辑
- **`strategies/market_maker/dashboard.py`**: TUI 监控面板

## 🛡️ 风控机制

1. **币种过滤**

   - ✅ 只选择价格 > $10 的主流币种
   - ✅ 过滤异常波动币种
   - ✅ 白名单机制

2. **价格保护**

   - ✅ Oracle 价格验证（偏离度 < 0.05%）
   - ✅ 价差限制（0.05% - 0.5%）

3. **资金管理**
   - ⚠️ 单笔限额（配置中）
   - ⚠️ 日亏损限制（配置中）

## 📈 性能指标

- **数据延迟**: ~2 秒（REST Polling）
- **报价更新**: 实时（每秒 4 次刷新）
- **支持币种**: 5-10 个并发
- **内存占用**: < 100 MB

## ⚠️ 注意事项

1. **首次运行**

   - 建议先用模拟模式熟悉界面
   - 确认报价正常后再开启实盘

2. **实盘交易**

   - ⚠️ 当前版本**仅计算报价，未启用真实下单**
   - 如需启用下单，需修改 `strategies/market_maker/main.py` 中的 executor 调用逻辑

3. **网络要求**

   - MEXC WebSocket 可能被封锁，系统会自动降级到 REST
   - 建议使用稳定网络环境

4. **资金安全**
   - API Key 权限建议只开启现货交易
   - 禁用提币权限
   - 设置 IP 白名单

## 🐛 故障排除

### WebSocket 连接失败

```
❌ Not Subscribed successfully! Blocked!
```

**解决方案**: 这是正常的，系统会自动使用 REST Polling，无需担心。

### API Key 错误

```
❌ Missing MEXC API Key for LIVE trading!
```

**解决方案**: 检查 `config/.env` 文件是否正确配置。

### 币种显示异常报价

```
XRP/USDT Bid: -1.23 Ask: 5.67 (异常价差)
```

**解决方案**: 已修复，确保使用最新代码。如仍出现，从候选列表中移除该币种。

## 📚 相关文档

- [参数调优指南](strategies/market_maker/TUNING_GUIDE.md)

## 📄 License

MIT License

## 🤝 Contributing

欢迎提交 Issue 和 Pull Request！

---

**⚡ Made with Avellaneda-Stoikov Algorithm**
