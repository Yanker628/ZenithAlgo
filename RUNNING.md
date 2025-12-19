# ZenithAlgo 运行指南 (Run Manual)

本文档旨在帮助用户快速上手 ZenithAlgo 量化系统。

## 环境准备

确保已安装 Python 3.10+ 和项目依赖：

```bash
# 安装依赖 (推荐在虚拟环境中)
pip install -r requirements.txt
# 或者使用 pdm/poetry
pdm install
```

## 核心命令

ZenithAlgo 使用 `main.py` 作为统一入口。

### 1. 运行回测 (Backtest)
使用历史数据验证策略表现。

```bash
# 默认回测 (使用 config/config.yml)
python main.py backtest

# 指定配置文件
python main.py --config config/my_strategy.yml backtest
```

### 2. 运行参数搜索 (Sweep)
批量运行回测，寻找最优参数组合。

```bash
# 运行 Sweep，并输出前 5 组最优参数
python main.py sweep --top-n 5
```

### 3. 运行实盘/模拟盘 (Runner)
启动交易引擎主循环，连接交易所（或模拟环境）。

```bash
# 启动 Runner (模式由 config.yml 中的 mode 字段决定: live/paper/dry-run)
python main.py runner

# 干跑模式（用于测试代码逻辑，不连接交易所）
python main.py runner --max-ticks 100
```

### 4. 运行 Walk-Forward 验证
使用滚动窗口方法验证策略在不同时间段的稳健性。

```bash
# 3 段验证，训练集占比 70%
python main.py walkforward --n-segments 3 --train-ratio 0.7
```

### 5. 运行测试
运行单元测试确保代码正确性。

```bash
# 运行所有非实盘测试
python main.py test
```

## 目录结构说明

- `main.py`: 统一入口。
- `config/`: 配置文件目录。
- `algo/strategy/`: 策略实现代码。
- `engine/`: 交易引擎核心逻辑。
- `results/`: 回测和实验结果输出目录。

## 常见问题

**Q: 如何切换实盘和模拟盘？**
A: 修改 `config/config.yml` 中的 `mode` 字段。
- `live`: 实盘（需配置 api_key）
- `paper`: 模拟盘（本地撮合）
- `dry-run`: 干跑（仅调试代码）

**Q: 只有 Python 基础如何写策略？**
A: 参考 `algo/strategy/simple_ma.py`。只需继承 `Strategy` 类并实现 `on_tick` 方法，返回 `OrderSignal` 列表即可。
