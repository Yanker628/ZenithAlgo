import logging

def setup_logger(name: str = "trading", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    # 控制台 handler
    ch = logging.StreamHandler()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger
