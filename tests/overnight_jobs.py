"""Stand-in jobs for tests/test_runs_overnight.py: a worker the machine kills part-way through a split.

Module-level so a forkserver worker can import them (the parent's sys.path, tests/ included, goes to the worker)."""

from __future__ import annotations

import os
import signal
import time


def killed_on_t2(arguments: tuple[str, str, str, str | None]) -> dict:
    """Task t2's worker dies the way the OOM killer or a memory guard's SIGTERM ends it; every other task scores 1.0."""
    _solution, task_id, _split, _records = arguments
    if task_id == "t2":
        time.sleep(0.5)  # every other task has reported by now, so t2 is the one unfinished task
        os.kill(os.getpid(), signal.SIGKILL)
    return {"task": task_id, "objective": 1.0}
