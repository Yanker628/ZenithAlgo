"""ZenithAlgo 统一命令行入口。

该模块提供单一入口 `main.py`，通过子命令驱动不同任务：

- `runner`：实时/纸面/干跑主循环。
- `backtest`：单次回测。
- `sweep`：参数搜索/批量回测。
- `walkforward`：Walk-Forward 验证。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from engine.runner import run_runner
from research.experiment import run_experiment


@dataclass
class CliArgs:
    config: str
    task: str
    max_ticks: int | None = None
    top_n: int = 5
    n_segments: int = 3
    train_ratio: float = 0.7
    min_trades: int = 10
    output_dir: str = "data/walkforward"
    include_live_tests: bool = False


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。

    Returns
    -------
    argparse.ArgumentParser
        配置好的参数解析器。
    """
    parser = argparse.ArgumentParser(prog="zenithalgo", description="ZenithAlgo 统一入口")
    parser.add_argument(
        "--config",
        default="config/config.yml",
        help="配置文件路径 (默认: config/config.yml)",
    )

    sub = parser.add_subparsers(dest="task")

    p_runner = sub.add_parser("runner", help="实盘/纸面/干跑主循环")
    p_runner.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="跑多少个 tick 后退出（用于 dry-run/测试）",
    )

    sub.add_parser("backtest", help="单次回测")

    p_sweep = sub.add_parser("sweep", help="参数搜索/批量回测")
    p_sweep.add_argument("--top-n", type=int, default=5, help="每个品种输出前 N 组")

    p_wf = sub.add_parser("walkforward", help="Walk-Forward 验证")
    p_wf.add_argument("--n-segments", type=int, default=3)
    p_wf.add_argument("--train-ratio", type=float, default=0.7)
    p_wf.add_argument("--min-trades", type=int, default=10)
    p_wf.add_argument("--output-dir", type=str, default="data/walkforward")

    p_test = sub.add_parser("test", help="运行 pytest（默认跳过 live）")
    p_test.add_argument(
        "--include-live",
        action="store_true",
        help="包含 @pytest.mark.live 测试（可能联网）",
    )

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
    return CliArgs(
        config=str(ns.config),
        task=task,
        max_ticks=getattr(ns, "max_ticks", None),
        top_n=int(getattr(ns, "top_n", 5)),
        n_segments=int(getattr(ns, "n_segments", 3)),
        train_ratio=float(getattr(ns, "train_ratio", 0.7)),
        min_trades=int(getattr(ns, "min_trades", 10)),
        output_dir=str(getattr(ns, "output_dir", "data/walkforward")),
        include_live_tests=bool(getattr(ns, "include_live", False)),
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

    if args.task == "runner":
        return run_runner(cfg_path=args.config, max_ticks=args.max_ticks)
    if args.task == "backtest":
        return run_experiment(args.config, task="backtest")
    if args.task == "sweep":
        return run_experiment(args.config, task="sweep", top_n=args.top_n)
    if args.task == "walkforward":
        return run_experiment(
            args.config,
            task="walkforward",
            n_segments=args.n_segments,
            train_ratio=args.train_ratio,
            min_trades=args.min_trades,
        )
    if args.task == "test":
        import pytest

        pytest_args = ["-q"]
        if not args.include_live_tests:
            pytest_args += ["-m", "not live"]
        return pytest.main(pytest_args)

    raise ValueError(f"Unknown task: {args.task}")


if __name__ == "__main__":
    main()
