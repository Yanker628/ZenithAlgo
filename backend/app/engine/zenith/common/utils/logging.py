"""
轻量日志封装。

Notes
-----
`setup_logger` 会避免重复添加 handler，否则多次调用会出现重复日志。
"""

from __future__ import annotations

import logging


def setup_logger(name: str = "trading", level: int = logging.INFO) -> logging.Logger:
    """
    创建或获取命名 logger。

    Parameters
    ----------
    name:
        Logger 名称。
    level:
        日志级别，默认 INFO。

    Returns
    -------
    logging.Logger
        已配置的 logger。
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    has_stream = any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    if not has_stream:
        ch = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger
