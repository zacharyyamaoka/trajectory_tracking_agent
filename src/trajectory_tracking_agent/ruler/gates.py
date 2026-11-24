"""The ruler's gates (OBJECTIVES §4, CONTRACT §6): per-task verdicts, admissibility and the objective. Fail closed.

    verdicts = gate_verdicts(task_kpis)             # {"completed": True, "stop_error_max_mm": False, ...}
    admissible(verdicts_per_task)                   # every task passes every gate
    objective(task_objectives)                      # median over tasks; any NaN -> NaN

`task_kpis` is keyed by gate name; each value is what that gate reads: `completed` a bool, `stop_error_max_mm` mm,
`saturation_share_pct` %, `limit_violations` and `floor_clearance` sample counts (`floor_clearance_violations` is
accepted for the latter, the name of the metric that counts them). A missing key, None, NaN, a non-number or a bool where
a number belongs is a failed gate, never a pass (arm_motion_bench v3.11).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

GATES: tuple[str, ...] = ("completed", "stop_error_max_mm", "saturation_share_pct", "limit_violations", "floor_clearance")

STOP_ERROR_MAX_MM = 1.0  # Zach's standing 1 mm tool gate (2026-11-11)
SATURATION_SHARE_MAX_PCT = 2.0
LIMIT_VIOLATIONS_MAX = 0
FLOOR_CLEARANCE_VIOLATIONS_MAX = 0

# (gate, what it reads, op, threshold), for display and for the scorecard's record of the ruler
THRESHOLDS: dict[str, tuple[str, float]] = {
    "completed": ("is", 1.0),
    "stop_error_max_mm": ("<=", STOP_ERROR_MAX_MM),
    "saturation_share_pct": ("<=", SATURATION_SHARE_MAX_PCT),
    "limit_violations": ("<=", LIMIT_VIOLATIONS_MAX),
    "floor_clearance": ("<=", FLOOR_CLEARANCE_VIOLATIONS_MAX),
}
_ALIASES = {"floor_clearance": ("floor_clearance", "floor_clearance_violations")}

__all__ = ["GATES", "THRESHOLDS", "admissible", "gate_pass_rate", "gate_verdicts", "objective"]


def _number(value: Any) -> float | None:
    """A finite real number, else None (a bool is not a number here: True <= 1.0 must not pass a mm gate)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read(task_kpis: Mapping[str, Any], gate: str) -> Any:
    for key in _ALIASES.get(gate, (gate,)):
        if key in task_kpis:
            return task_kpis[key]
    return None


def _completed(value: Any) -> bool:
    # WHY only True (or exactly 1): "completed" is a verdict; a NaN, None, 0.5 or the string "yes" is not one
    if isinstance(value, bool):
        return value
    number = _number(value)
    return number == 1.0


def gate_verdicts(task_kpis: Mapping[str, float | bool | None]) -> dict[str, bool]:
    """One task's verdict on every gate in GATES order. Fail closed: None / NaN / missing -> False."""
    if not isinstance(task_kpis, Mapping):
        return {gate: False for gate in GATES}
    verdicts: dict[str, bool] = {}
    for gate in GATES:
        value = _read(task_kpis, gate)
        if gate == "completed":
            verdicts[gate] = _completed(value)
            continue
        number = _number(value)
        verdicts[gate] = number is not None and number <= THRESHOLDS[gate][1]
    return verdicts


def admissible(verdicts_per_task: Sequence[Mapping[str, bool]]) -> bool:
    """True only if there is at least one task and every task passes every gate in GATES (a missing verdict fails)."""
    tasks = list(verdicts_per_task)
    if not tasks:
        return False
    return all(isinstance(v, Mapping) and all(v.get(gate) is True for gate in GATES) for v in tasks)


def gate_pass_rate(verdicts_per_task: Sequence[Mapping[str, bool]]) -> float:
    """The share of (task, gate) verdicts that pass, over every task and every gate in GATES; 0.0 with no tasks."""
    tasks = list(verdicts_per_task)
    if not tasks:
        return 0.0
    passed = sum(1 for v in tasks for gate in GATES if isinstance(v, Mapping) and v.get(gate) is True)
    return passed / (len(tasks) * len(GATES))


def objective(task_objectives: Sequence[float]) -> float:
    """The solution's objective: the median of the per-task `tool_track_rms_mm`; any NaN / None (or no task) -> NaN."""
    values = []
    for value in task_objectives:
        number = _number(value)
        if number is None:
            return math.nan
        values.append(number)
    if not values:
        return math.nan
    values.sort()
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else 0.5 * (values[middle - 1] + values[middle])
