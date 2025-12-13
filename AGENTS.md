# Repository Guidelines

## Project Structure & Module Organization

- 根目录：`README.md` 给出全貌，`Makefile` 封装日常命令，`CONTRIBUTING.md` 说明贡献流程，`LICENSE` 载明协议。保持根目录扁平，避免巨石文件。
- 文档库：`documents/` 汇总流程、架构与实践（如 `代码组织.md`、`通用项目架构模板.md`、`开发经验.md`），是理解方法论与协作规则的首选入口。新增流程文档时优先放此处并在 README 链接。
- 提示词资产：`prompts/` 按角色拆分（system / assistant / coding / user），
  `prompts/prompts-library/` 提供 Excel ↔ Markdown 互转工具与脚本目录，便于批量维护提示词，
  适合作为“单一真实来源”。
- 代码与集成：`libs/` 预留核心实现骨架，`common/`、`database/`、`external/` 分别对应通用模型、存储适配与外部依赖登记；新增模块需保持分层边界与单一职责，避免跨层调用。
- 备份：`backups/` 内含 `一键备份.sh` 与 `快速备份.py`，用于本地快照或同步，请先在隔离目录试跑，确认输出路径与权限。

## Build, Test, and Development Commands

- `make help`：列出所有 Make 目标，是新人快速上手的入口。
- `make lint`：使用 `markdownlint-cli` 校验全仓库 Markdown，一旦新增文档请先跑通（需本地 Node/npm 环境，可用 `npm install -g markdownlint-cli` 安装）。
- `make build` / `make test` / `make clean`：目前为占位，落地具体实现后务必更新脚本和说明；建议在 `Makefile` 旁补充注释并保持幂等，避免修改全局状态。
- 提示词转换：进入 `prompts/prompts-library/` 后执行 `python main.py` 按交互提示进行转换，运行前请确认虚拟环境、依赖与输出目录，并在完成后检查生成 Markdown 是否符合 lint 规则。

## Coding Style & Naming Conventions

- 文字层：文档、注释、日志使用中文；代码符号（函数 / 变量 / 模块）统一英文且语义直白，避免晦涩缩写。
- 缩进与排版：全仓保持空格缩进（2 或 4 空格任选其一但不得混用）；Markdown 列表、代码块与表格对齐清晰，行宽控制在 120 列内。Git diff 可读性优先。
- 设计品味：优先消除分支与重复；函数力求单一职责且短小；命名遵循小写加中划线或下划线，不使用空格与特殊字符；跨模块接口保持稳定签名。
- 依赖管理：新增工具或库时记录安装方式、最小版本与来源，必要时在 `documents/工具集.md` 或 README 中补充，并说明为何需要它（性能、兼容、功能）。

## Testing Guidelines

- 当前无实测用例；引入代码时请至少提供最小可复现测试。推荐 Python 使用 `pytest`，文件命名 `test_*.py`，夹具精简可读，遵循 red-green-refactor 循环。
- 文档与提示词改动：提交前运行 `make lint`；如转换脚本涉及数据，附带示例输入 / 输出说明或最小数据样例，确保可重复。
- 覆盖率基线由模块维护者设定；若暂无标准，确保主流程和边界条件均可被测试验证，必要时在 PR 描述中写明未覆盖的风险，并建议后续补测计划。

## Commit & Pull Request Guidelines

- Commit 建议遵循简化 Conventional Commits：`feat|fix|docs|chore|refactor|test: scope – summary`，一句话说明行为与范围；避免笼统的 “update”。
- PR 必填：变更摘要、动机或关联 Issue、测试与验证步骤（列出运行的命令与结果概览）；涉及文档 / UI 的修改应附对比截图或链接，方便 reviewer 快速复核。
- 提交前清单：跑通 `make lint`；若新增脚本 / 依赖，更新对应文档与 `Makefile` 目标；确认不携带临时文件或机密数据，并在描述中注明潜在风险或需要 reviewer 特别关注的点。

## Security & Configuration Tips

- 运行备份或转换脚本前，确认输出目录不会覆盖私有数据；建议先在临时目录试跑并检查生成文件，必要时使用只读副本。
- 外部依赖来源记录在 `libs/external/AGENTS.md`，增减依赖时同步维护，保持可追溯；引入第三方脚本需标明许可证与来源。

## Architecture Overview & Workflow

- 工作流倡导「规划 → 上下文固定 → 分步实现 → 自测 → 复盘」，对应资产分别存放在 `documents/`、`prompts/`、`libs/` 与备份脚本中。保持单向数据流和清晰责任边界可以避免后期维护成本激增。
- 设计决策与目录结构更新后，请同步修订本文件与相关文档，确保团队共享同一真相源，减少口头约定与隐式规则。
