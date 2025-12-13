# Contributing

## 开发约定

- 文档/注释/日志使用中文；代码符号（函数/变量/模块）使用英文。
- 保持仓库入口单一：运行从 `main.py` 进入。
- 不提交真实 API Key；使用环境变量或 `config/config.local.yml`。

## 本地验证

- 运行测试：`make test`（默认跳过 `@pytest.mark.live`）。
- 文档 lint：`make lint`（需要 `npm install -g markdownlint-cli`）。

## Commit 规范（简化版）

推荐：`feat|fix|docs|chore|refactor|test: scope – summary`
