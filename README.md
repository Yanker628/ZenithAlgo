# ZenithAlgo 🚀

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![Rust](https://img.shields.io/badge/rust-1.70+-orange)
![Go](https://img.shields.io/badge/go-1.21+-cyan)
![Next.js](https://img.shields.io/badge/next.js-14+-black)

**ZenithAlgo** 是一个高性能、现代化的量化交易与研究平台（Research-as-a-Service）。它融合了 Rust 的极致性能、Python 的生态便利、Go 的高并发调度以及 Web 前端的交互体验，旨在为量化研究员提供从策略研发、回测到实盘的一站式解决方案。

## ✨ 核心特性

- **🚀 混合架构核心**:
  - **Rust**: 核心算子与回测引擎，提供纳秒级性能。
  - **Go**: 负责任务调度、API 服务与 WebSocket 推送。
  - **Python**: 策略逻辑层，兼容 Pandas/Numpy 生态。
- **📊 RaaS (Research as a Service)**:
  - 分布式任务队列 (Redis)，支持大规模参数扫描 (Sweep)。
  - 实时 WebSocket 前端推送，回测进度与权益曲线可视化。
  - 结果自动持久化 (Postgres)，数据有据可查。
- **🛡️ 严格的数据一致性**:
  - `M7 Alignment`: 确保 Rust Core、Python Vectorized 与 Iterative 模式下的计算结果在数学上精确一致 (Diff < 1e-10)。
- **🖥️ 现代化前端**:
  - 基于 Next.js 14 + Tailwind CSS + Shadcn UI 构建。
  - 交互式 Dashboard，支持回测配置与历史记录回溯。

## 🏗️ 架构概览

```mermaid
graph TD
    Client[Frontend (Next.js)] <-->|HTTP/WS| API[Go API Gateway]
    API <-->|Tasks| Redis[(Redis Queue)]
    API <-->|Events| PubSub[Redis Pub/Sub]

    Worker[Python Worker] <-->|Pop Job| Redis
    Worker -->|Calc| RustCore[Rust Native Core]
    Worker -->|Progress| PubSub

    Persister[Result Persister] <-->|Sub| PubSub
    Persister -->|Write| DB[(Postgres)]
```

## 🛠️ 技术栈

- **Backend (Scheduling)**: Go (Gin, Go-Redis, Gorilla WebSocket)
- **Engine (Compute)**: Python 3.10+, Rust (PyO3, Maturin)
- **Frontend**: TypeScript, Next.js, Recharts, Tailwind CSS
- **Infrastructure**: Docker, Redis, PostgreSQL
- **Tooling**: `uv` (Python pkg), `cargo` (Rust), `make`

## 🚀 快速开始

### 前置要求

- Docker & Docker Compose
- Go 1.21+
- Python 3.10+ (推荐使用 `uv`)
- Node.js 18+

### 一键启动

我们提供了方便的脚本来一键启动整个 RaaS 系统（含数据库、后端和前端）。

```bash
chmod +x scripts/*.sh
./scripts/start.sh
```

启动后访问：

- **前端控制台**: [http://localhost:3000/backtest](http://localhost:3000/backtest)
- **API 文档/接口**: [http://localhost:8080](http://localhost:8080)

### 停止系统

```bash
./scripts/stop.sh
```

## ✅ 全量测试

运行以下脚本以执行完整的系统自检（包括数据一致性校验和 RaaS 集成测试）：

```bash
./scripts/test_full.sh
```

## 📂 目录结构

```text
.
├── backend
│   ├── app
│   │   ├── engine       # Python/Rust 回测引擎
│   │   └── server       # Go API 调度服务
│   ├── native           # Rust 核心源码
│   └── scripts          # 测试与验证脚本
├── frontend             # Next.js 前端应用
└── scripts              # 项目级运维脚本 (start/stop)
```

## 📜 License

MIT
