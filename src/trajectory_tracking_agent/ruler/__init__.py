"""The frozen ruler v1 (OBJECTIVES.md §2-4): the deployment, the dataset, the metrics and the gates.

A solution never imports this package (CONTRACT §2: no peeking at the scorer). `metrics` and `gates` are numpy only and
import nothing else, so a browser (Pyodide) can import `trajectory_tracking_agent.ruler.metrics` alone; `deployment` and
`dataset` pull in robot_controllers / MuJoCo and load only when asked for (PEP 562 lazy attributes).
"""

from __future__ import annotations

import importlib
from typing import Any

RULER_VERSION = "v1"
_SUBMODULES = ("deployment", "dataset", "metrics", "gates")

__all__ = ["RULER_VERSION", *_SUBMODULES]


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
