# ZenithAlgo 2.0 Roadmap（全景架构版）

当前版本：v2.0-Alpha
最后核对：2025-12-20

核心哲学：研究流先行，计算下沉 Rust，控制中台化，执行一致性。

## 0. 北极星（工程优先级）

- 高性能研究：向量化回测秒级完成，消灭 GIL 限制。
- 解耦中台化：UI、API 与执行引擎三层分离，支持多语言协作。
- 数据资产化：数据自带 Hash 指纹，实现“研究-数据-结果”的闭环溯源。
- 执行一致性（M7）：回测逻辑与实盘逻辑 100% 对齐，杜绝“回测盈利，实盘亏损”。

## 1. 第一阶段：数据资产化（Data as First-Class Citizen）- 进行中/核心

目标：建立跨语言、高性能的数据底座。

- [x] M6-1 元信息 Hash：生成 meta.json 并计算 data_hash，实现数据集指纹识别。
- [x] **Project Restructuring (Monorepo)**
  - [x] Backend/Frontend Directory Split
  - [x] `src/zenith` Domain-Driven Layout
  - [x] Unified `main.py` CLI
- [ ] **Frontend Development**
  - [ ] Next.js Initialization
  - [ ] Dashboard UI
- [ ] M6-3 DatasetStore：在 database/ 下抽象统一的数据加载接口，屏蔽底层文件细节。
- [ ] M7 一致性对齐：通过固定 data_hash 对比回测引擎与实盘引擎的信号差异。
  - 备注：当前以信号一致性为验收口径，成交/费用/滑点一致性后续补测。

## 2. 第二阶段：研究流服务化（Research-as-a-Service）

目标：将 CLI 脚本升级为异步 API 服务，支持“点击运行”。

- [ ] API 总线（Go）：封装 main.py 逻辑，提供 REST API 触发回测与 Sweep。
- [ ] 异步任务调度：引入任务队列，支持多并发回测任务，返回 task_id 供进度查询。
- [ ] 结果索引库：建立轻量级数据库记录历史运行的 run_id、配置与性能指标，方便前端对比。
- [ ] 实时推送（WS）：通过 WebSocket 将回测/交易进度与权益曲线实时推送至外部。

## 3. 第三阶段：计算层下沉（Algo-Core Acceleration）

目标：引入 Rust/C++ 解决 Python 计算瓶颈。

- [ ] 混合架构集成：引入 PyO3 或 pybind11 环境，预埋高性能扩展入口。
- [ ] 核心算子下沉：将 algo/factors/ 中的基础算子（RSI、MA、ATR）改写为 Rust/C++ 原生实现。
- [ ] 向量化模拟器：针对扫参任务开发非事件驱动的“矩阵回测引擎”，实现性能数量级跃迁。

## 4. 第四阶段：全景平台化（Zenith Platform）

目标：构建完整的 Web 交互看板，实现量化研发流水线。

- [ ] 策略仪表盘：前端可视化看板，展示策略分布、资产走势与交易分布图。
- [ ] 参数热力图：在网页端交互式展示 sweep 结果，点击热力图格点即可查看该组回测详情。
- [ ] 实盘/纸面监控：对接 ledger.sqlite3，实时展示当前持仓、对账状态与安全保险丝状态。

## 5. 长期规划与 AI 协同

- A1 投研 Agent：LLM 接入 API，自动生成策略配置并调用研究流进行验证。
- A2 代码生成：根据策略描述自动生成符合接口规范的 Rust 算子。
- 多语言中台：将 Go 改造为核心订单路由网关，负责多路 WebSocket 接入。

## 6. 暂缓清单（明确后做）

- 复杂的 Web 权限系统：优先保证研究流性能。
- 高频专用 DB（如 ClickHouse）：在 Parquet 性能达到极限前不引入额外运维复杂度。
