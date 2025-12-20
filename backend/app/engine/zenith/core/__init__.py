"""执行引擎层（engine）。

统一入口：各引擎以 `XxxEngine.run() -> EngineResult` 形式对外提供能力；
命令行入口由仓库根目录 `main.py` 统一承载。
"""

