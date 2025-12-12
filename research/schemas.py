"""Experiment 配置/结果 schema（轻量占位，便于后续扩展）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExperimentConfig:
    task: str
    cfg_path: str
    extra: dict[str, Any] | None = None

