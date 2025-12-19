"""ZenithAlgo 统一命令行入口。

该模块提供单一入口 `main.py`，通过子命令驱动不同任务：

- `runner`：实时/纸面/干跑主循环。负责连接交易所，执行策略。
- `backtest`：单次回测。对历史数据进行策略验证。
- `sweep`：参数搜索/批量回测。寻找最优策略参数。
- `walkforward`：Walk-Forward 验证。滚动窗口测试策略稳健性。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from engine.trading_engine import TradingEngine
from research.experiment import run_experiment


@dataclass
class CliArgs:
    """定义命令行参数结构。
    
    这里列出了所有支持的命令行选项，每个字段对应一个 argparse 参数。
    config: 配置文件路径
    task: 要运行的任务类型 (runner/backtest/sweep/walkforward)
    """
    config: str
    task: str
    max_ticks: int | None = None  # 仅用于 debug，限制运行多少个 tick 就停止
    top_n: int = 5                # sweep 模式下保留前且多少组参数
    n_segments: int = 3           # walkforward 模式下的分段数
    train_ratio: float = 0.7      # walkforward 模式下的训练集占比
    min_trades: int = 10          # 最小交易次数限制
    output_dir: str = "results/walkforward_engine"
    include_live_tests: bool = False
    report_dir: str | None = None


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。

    Returns
    -------
    argparse.ArgumentParser
        配置好的参数解析器。
    """
    parser = argparse.ArgumentParser(prog="zenithalgo", description="ZenithAlgo 统一入口")
    def _add_config_arg(p: argparse.ArgumentParser, *, default: Any) -> None:
        p.add_argument(
            "--config",
            default=default,
            help="配置文件路径 (默认: config/config.yml)",
        )

    # 允许 `python main.py --config ... backtest`（全局）与 `python main.py backtest --config ...`（子命令）
    _add_config_arg(parser, default="config/config.yml")

    sub = parser.add_subparsers(dest="task")

    p_runner = sub.add_parser("runner", help="实盘/纸面/干跑主循环")
    _add_config_arg(p_runner, default=argparse.SUPPRESS)
    p_runner.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="跑多少个 tick 后退出（用于 dry-run/测试）",
    )

    p_backtest = sub.add_parser("backtest", help="单次回测")
    _add_config_arg(p_backtest, default=argparse.SUPPRESS)

    p_sweep = sub.add_parser("sweep", help="参数搜索/批量回测")
    _add_config_arg(p_sweep, default=argparse.SUPPRESS)
    p_sweep.add_argument("--top-n", type=int, default=5, help="每个品种输出前 N 组")

    p_wf = sub.add_parser("walkforward", help="Walk-Forward 验证")
    _add_config_arg(p_wf, default=argparse.SUPPRESS)
    p_wf.add_argument("--n-segments", type=int, default=3)
    p_wf.add_argument("--train-ratio", type=float, default=0.7)
    p_wf.add_argument("--min-trades", type=int, default=10)
    p_wf.add_argument("--output-dir", type=str, default="results/walkforward_engine")

    p_test = sub.add_parser("test", help="运行 pytest（默认跳过 live）")
    _add_config_arg(p_test, default=argparse.SUPPRESS)
    p_test.add_argument(
        "--include-live",
        action="store_true",
        help="包含 @pytest.mark.live 测试（可能联网）",
    )

    p_report = sub.add_parser("report", help="生成 HTML 报告")
    p_report.add_argument("report_dir", type=str, help="结果目录 (results/...)")

    return parser


def parse_args(argv: list[str] | None = None) -> CliArgs:
    """解析命令行参数。

    Parameters
    ----------
    argv:
        传入的参数列表；为 None 时读取 sys.argv。

    Returns
    -------
    CliArgs
        解析后的参数对象。
    """
    parser = build_parser()
    ns = parser.parse_args(argv)
    task = ns.task or "runner"
    config = getattr(ns, "config", "config/config.yml")
    return CliArgs(
        config=str(config),
        task=task,
        max_ticks=getattr(ns, "max_ticks", None),
        top_n=int(getattr(ns, "top_n", 5)),
        n_segments=int(getattr(ns, "n_segments", 3)),
        train_ratio=float(getattr(ns, "train_ratio", 0.7)),
        min_trades=int(getattr(ns, "min_trades", 10)),
        output_dir=str(getattr(ns, "output_dir", "results/walkforward_engine")),
        include_live_tests=bool(getattr(ns, "include_live", False)),
        report_dir=getattr(ns, "report_dir", None),
    )


def main(argv: list[str] | None = None) -> Any:
    """程序主入口。

    Parameters
    ----------
    argv:
        可选的参数列表；为 None 时读取 sys.argv。

    Returns
    -------
    Any
        对应子命令的返回结果（通常为 summary dict）。
    """
    args = parse_args(argv)

    # 根据 task 参数分发到不同的执行逻辑
    # 1. runner: 核心交易循环 (实盘/模拟盘/回测 dry-run)
    if args.task == "runner":
        # 初始化交易引擎并运行
        return TradingEngine(cfg_path=args.config, max_ticks=args.max_ticks).run().summary
    
    # 2. backtest: 历史数据回测
    if args.task == "backtest":
        return run_experiment(args.config, task="backtest")
    
    # 3. sweep: 超参数搜索
    if args.task == "sweep":
        return run_experiment(args.config, task="sweep", top_n=args.top_n)
    
    # 4. walkforward: 滚动窗口验证
    if args.task == "walkforward":
        return run_experiment(
            args.config,
            task="walkforward",
            n_segments=args.n_segments,
            train_ratio=args.train_ratio,
            min_trades=args.min_trades,
        )
    
    # 5. test: 运行单元测试
    if args.task == "test":
        import pytest

        pytest_args = ["-q"]
        if not args.include_live_tests:
            pytest_args += ["-m", "not live"]
        return pytest.main(pytest_args)

    # 6. report: 生成报告
    if args.task == "report":
        from analysis.reporting import ReportGenerator
        if not args.report_dir:
            raise ValueError("Must specify directory for report")
        gen = ReportGenerator(args.report_dir)
        path = gen.generate()
        print(f"Report generated: {path}")
        return

    raise ValueError(f"Unknown task: {args.task}")


if __name__ == "__main__":
    main()
