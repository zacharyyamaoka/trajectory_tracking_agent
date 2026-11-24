"""The ruler's metrics (OBJECTIVES §4, CONTRACT §6): numpy only, SI in, the unit in the name out.

    moving = moving_mask(t, target_tool_xyz, target_qd)
    stops = stop_windows(t, moving)
    tool_track_rms_mm(target_tool_xyz, measured_tool_xyz, moving)     # the objective, per task

Conventions every function shares:

- Arrays are time along axis 0. Tool points are (N, 3) metres, joint signals (N, n) rad, rad/s or N·m.
- *Fail closed* (arm_motion_bench v3.11): a NaN in an input makes a tracking number NaN, and a NaN sample counts as a
  violation in every counting gate (`limit_violations`, `floor_clearance_violations`); `saturation_share_pct` is NaN.
  NaN never passes a gate (`gates.gate_verdicts`).
- A task with no moving samples returns NaN from the tracking metrics; one with no stops has `stop_error_max_mm = 0.0`.
- Shapes that do not line up raise ValueError: a ruler that guessed would score the wrong thing.

The numbers are arm_motion_bench's KPI catalog (`kpi_names.py`, the source OBJECTIVES §4 is drawn from), named here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

# ── the frozen numbers (OBJECTIVES §4) ──────────────────────────────────────────────────────────────────────

MOVING_TOOL_SPEED_M_S = 1e-3  # "target tool speed > 1 mm/s"
# WHY radians(0.06): OBJECTIVES §4 states the joint threshold as 0.06 °/s. Its source (arm_motion_bench kpi_names
# MOVING_JOINT_SPEED_RAD_S) is 1e-3 rad/s = 0.0573 °/s, of which 0.06 is the display rounding; the frozen ruler's text
# wins, and the 4.7 % gap is reported to the dispatcher (lane E report, 2026-11-24).
MOVING_JOINT_SPEED_RAD_S = math.radians(0.06)
MIN_STOP_S = 0.2  # "a stop = target at rest >= 0.2 s"
HOLD_WINDOW_S = 0.1  # "mean tool position over each stop's last 0.1 s"
SATURATION_FRACTION = 0.98  # "|tau| >= 98 % of its cap"
VELOCITY_LIMIT_ALLOWANCE = 1.05  # "above 1.05 x a velocity limit"
TIME_TOLERANCE_S = 1e-9  # a sample at 0.2 s on a 0.01 s grid is 0.19999999999999998 after the subtraction
SMOOTH_WINDOW_S = 0.05  # tool_jerk_rms_m_s3: the catalog's 50 ms box, applied 3 times

__all__ = [
    "HOLD_WINDOW_S",
    "MIN_STOP_S",
    "MOVING_JOINT_SPEED_RAD_S",
    "MOVING_TOOL_SPEED_M_S",
    "SATURATION_FRACTION",
    "VELOCITY_LIMIT_ALLOWANCE",
    "energy_j",
    "floor_clearance_violations",
    "joint_track_rms_deg",
    "limit_violations",
    "moving_mask",
    "saturation_share_pct",
    "stop_error_max_mm",
    "stop_error_median_mm",
    "stop_errors_mm",
    "stop_windows",
    "tool_errors_m",
    "tool_jerk_rms_m_s3",
    "tool_track_max_mm",
    "tool_track_rms_mm",
]


# ── input checks ────────────────────────────────────────────────────────────────────────────────────────────


def _times(t: object) -> np.ndarray:
    times = np.asarray(t, dtype=np.float64)
    if times.ndim != 1:
        raise ValueError(f"t must be (N,) seconds, got shape {times.shape}")
    return times


def _points(values: object, name: str, rows: int | None = None) -> np.ndarray:
    points = np.asarray(values, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"{name} must be (N, 3) metres, got shape {points.shape}")
    if rows is not None and points.shape[0] != rows:
        raise ValueError(f"{name} has {points.shape[0]} rows, expected {rows}")
    return points


def _joints(values: object, name: str, rows: int | None = None) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 1:  # one joint
        array = array[:, None]
    if array.ndim != 2:
        raise ValueError(f"{name} must be (N, n), got shape {array.shape}")
    if rows is not None and array.shape[0] != rows:
        raise ValueError(f"{name} has {array.shape[0]} rows, expected {rows}")
    return array


def _mask(values: object, rows: int) -> np.ndarray:
    mask = np.asarray(values)
    if mask.shape != (rows,):
        raise ValueError(f"moving must be (N,) = ({rows},), got shape {mask.shape}")
    return mask.astype(bool)


# ── moving and stops ────────────────────────────────────────────────────────────────────────────────────────


def moving_mask(t: object, target_tool_xyz: object, target_qd: object) -> np.ndarray:
    """Samples where the TARGET moves: target tool speed > 1 mm/s or any |target joint speed| > 0.06 °/s.

    The tool speed is `np.gradient(target_tool_xyz, t)` (central differences inside, one-sided at the ends), read on
    the target's own unsmoothed signals (arm_motion_bench kpis.py reading 9). A NaN speed counts as moving: a sample
    the ruler cannot place at rest is never let off as a stop.
    """
    times = _times(t)
    tool = _points(target_tool_xyz, "target_tool_xyz", len(times))
    qd = _joints(target_qd, "target_qd", len(times))
    if len(times) >= 2:
        tool_speed = np.linalg.norm(np.gradient(tool, times, axis=0), axis=1)
    else:
        tool_speed = np.zeros(len(times))
    joint_speed = np.max(np.abs(qd), axis=1) if qd.shape[1] else np.zeros(len(times))
    at_rest = (tool_speed <= MOVING_TOOL_SPEED_M_S) & (joint_speed <= MOVING_JOINT_SPEED_RAD_S)
    return ~at_rest  # NaN compares False, so it is not at rest


def stop_windows(t: object, moving: object) -> list[tuple[float, float]]:
    """Every span where the target is at rest (not moving) for >= 0.2 s, as (t0, t1): the times of its first and last
    rest sample, in time order. A rest at the very start or end of the trajectory is a stop like any other."""
    times = _times(t)
    rest = ~_mask(moving, len(times))
    windows: list[tuple[float, float]] = []
    index = 0
    while index < len(times):
        if not rest[index]:
            index += 1
            continue
        end = index
        while end + 1 < len(times) and rest[end + 1]:
            end += 1
        t0, t1 = float(times[index]), float(times[end])
        if t1 - t0 >= MIN_STOP_S - TIME_TOLERANCE_S:
            windows.append((t0, t1))
        index = end + 1
    return windows


# ── tracking ────────────────────────────────────────────────────────────────────────────────────────────────


def tool_errors_m(target_tool_xyz: object, measured_tool_xyz: object) -> np.ndarray:
    """|p_target(t) - p_measured(t)| at every sample (m), same instant."""
    target = _points(target_tool_xyz, "target_tool_xyz")
    measured = _points(measured_tool_xyz, "measured_tool_xyz", len(target))
    return np.linalg.norm(target - measured, axis=1)


def tool_track_rms_mm(target_tool_xyz: object, measured_tool_xyz: object, moving: object) -> float:
    """THE OBJECTIVE for one task: RMS over the moving samples of |p_target - p_measured| (mm). NaN when nothing moves
    or any moving sample is NaN."""
    errors = tool_errors_m(target_tool_xyz, measured_tool_xyz)
    mask = _mask(moving, len(errors))
    if not mask.any():
        return math.nan
    return float(1e3 * np.sqrt(np.mean(np.square(errors[mask]))))


def tool_track_max_mm(target_tool_xyz: object, measured_tool_xyz: object, moving: object) -> float:
    """Max over the moving samples of |p_target - p_measured| (mm); NaN when nothing moves or any moving sample is NaN."""
    errors = tool_errors_m(target_tool_xyz, measured_tool_xyz)
    mask = _mask(moving, len(errors))
    if not mask.any():
        return math.nan
    moving_errors = errors[mask]
    if np.isnan(moving_errors).any():
        return math.nan
    return float(1e3 * np.max(moving_errors))


def joint_track_rms_deg(target_q: object, measured_q: object, moving: object) -> float:
    """The worst joint: max over joints of the RMS over moving samples of q_target - q_measured (deg)."""
    target = _joints(target_q, "target_q")
    measured = _joints(measured_q, "measured_q", len(target))
    if measured.shape != target.shape:
        raise ValueError(f"target_q {target.shape} and measured_q {measured.shape} differ")
    mask = _mask(moving, len(target))
    if not mask.any() or not target.shape[1]:
        return math.nan
    per_joint = np.sqrt(np.mean(np.square(target[mask] - measured[mask]), axis=0))
    return float(math.degrees(np.max(per_joint))) if not np.isnan(per_joint).any() else math.nan


# ── stops ───────────────────────────────────────────────────────────────────────────────────────────────────


def stop_errors_mm(
    t: object, target_tool_xyz: object, measured_tool_xyz: object, stops: Sequence[tuple[float, float]]
) -> np.ndarray:
    """Per stop: |mean(p_target) - mean(p_measured)| over the stop's last 0.1 s (mm), the samples with
    t1 - 0.1 <= t <= t1 (and t >= t0). The target rests there, so its mean is the stop's keypose. A stop with no sample
    in its window, or a NaN in it, is NaN."""
    times = _times(t)
    target = _points(target_tool_xyz, "target_tool_xyz", len(times))
    measured = _points(measured_tool_xyz, "measured_tool_xyz", len(times))
    out = np.full(len(stops), np.nan)
    for index, (t0, t1) in enumerate(stops):
        start = max(float(t0), float(t1) - HOLD_WINDOW_S)
        window = (times >= start - TIME_TOLERANCE_S) & (times <= float(t1) + TIME_TOLERANCE_S)
        if window.any():
            out[index] = 1e3 * np.linalg.norm(target[window].mean(axis=0) - measured[window].mean(axis=0))
    return out


def stop_error_max_mm(
    t: object, target_tool_xyz: object, measured_tool_xyz: object, stops: Sequence[tuple[float, float]]
) -> float:
    """GATE (<= 1 mm): max over stops of the stop error; 0.0 with no stops; NaN if any stop's error is NaN."""
    errors = stop_errors_mm(t, target_tool_xyz, measured_tool_xyz, stops)
    if errors.size == 0:
        return 0.0
    return math.nan if np.isnan(errors).any() else float(np.max(errors))


def stop_error_median_mm(
    t: object, target_tool_xyz: object, measured_tool_xyz: object, stops: Sequence[tuple[float, float]]
) -> float:
    """Diagnostic `stop_error_mm`: the median over stops (ISO 9283 pose accuracy, one cycle); NaN with no stops."""
    errors = stop_errors_mm(t, target_tool_xyz, measured_tool_xyz, stops)
    if errors.size == 0 or np.isnan(errors).any():
        return math.nan
    return float(np.median(errors))


# ── the violation gates ─────────────────────────────────────────────────────────────────────────────────────


def saturation_share_pct(torque: object, caps: object) -> float:
    """GATE (<= 2 %): 100 x the share of samples where any |tau_j| >= 0.98 x cap_j. NaN with no samples, a NaN torque or
    a cap that is not finite and > 0."""
    tau = _joints(torque, "torque")
    cap = np.asarray(caps, dtype=np.float64).reshape(-1)
    if cap.shape != (tau.shape[1],):
        raise ValueError(f"caps must be ({tau.shape[1]},), got shape {cap.shape}")
    if tau.shape[0] == 0 or np.isnan(tau).any() or not (np.isfinite(cap).all() and (cap > 0.0).all()):
        return math.nan
    saturated = np.any(np.abs(tau) >= SATURATION_FRACTION * cap, axis=1)
    return float(100.0 * np.mean(saturated))


def limit_violations(q: object, qd: object, q_lo: object, q_hi: object, qd_max: object) -> int:
    """GATE (== 0): samples with any joint outside [q_lo, q_hi] or with |qd| > 1.05 x qd_max. A NaN sample counts."""
    position = _joints(q, "q")
    velocity = _joints(qd, "qd", len(position))
    joints = position.shape[1]
    low, high, limit = (np.asarray(v, dtype=np.float64).reshape(-1) for v in (q_lo, q_hi, qd_max))
    for name, values in (("q_lo", low), ("q_hi", high), ("qd_max", limit)):
        if values.shape != (joints,):
            raise ValueError(f"{name} must be ({joints},), got shape {values.shape}")
    if velocity.shape != position.shape:
        raise ValueError(f"q {position.shape} and qd {velocity.shape} differ")
    inside = (position >= low) & (position <= high) & (np.abs(velocity) <= VELOCITY_LIMIT_ALLOWANCE * limit)
    return int(np.count_nonzero(~np.all(inside, axis=1)))  # NaN compares False: outside


def floor_clearance_violations(points_z: object, floor_z: float = 0.0) -> int:
    """GATE (== 0): samples with any point (the tool and every link origin) below the floor plane, z < floor_z. A NaN
    counts. `points_z` is (N, k) metres; (N,) is one point."""
    heights = _joints(points_z, "points_z")
    above = heights >= float(floor_z)
    return int(np.count_nonzero(~np.all(above, axis=1)))


# ── diagnostics (reported, never optimized) ─────────────────────────────────────────────────────────────────


def energy_j(t: object, torque: object, qd: object) -> float:
    """"Motor energy": positive mechanical work at the joints, the trapezoid integral of sum_j max(tau_j qd_j, 0) (J).
    WHY no negative part (arm_motion_bench energy_mech_j): braking work is not regenerated."""
    times = _times(t)
    tau = _joints(torque, "torque", len(times))
    velocity = _joints(qd, "qd", len(times))
    if tau.shape != velocity.shape:
        raise ValueError(f"torque {tau.shape} and qd {velocity.shape} differ")
    if len(times) < 2:
        return math.nan
    power = np.sum(np.maximum(tau * velocity, 0.0), axis=1)
    return float(np.sum(0.5 * (power[1:] + power[:-1]) * np.diff(times)))


def _smooth(signal: np.ndarray, width: int) -> np.ndarray:
    """A centred box of `width` samples applied 3 times along axis 0, the ends replicated (never zero-padded)."""
    half = width // 2
    out = signal
    for _ in range(3):
        padded = np.concatenate([np.repeat(out[:1], half, axis=0), out, np.repeat(out[-1:], half, axis=0)])
        cumulative = np.cumsum(np.concatenate([np.zeros((1, out.shape[1])), padded]), axis=0)
        out = (cumulative[width:] - cumulative[:-width]) / width
    return out


def tool_jerk_rms_m_s3(t: object, measured_tool_xyz: object, moving: object) -> float:
    """RMS over moving samples of |d3 p_measured / dt3| (m/s³): p smoothed by a 50 ms box applied 3 times, then
    np.gradient 3 times (arm_motion_bench tcp_jerk_rms_m_s3). Needs a uniform grid; NaN otherwise."""
    times = _times(t)
    points = _points(measured_tool_xyz, "measured_tool_xyz", len(times))
    mask = _mask(moving, len(times))
    if len(times) < 4 or not mask.any() or np.isnan(points).any():
        return math.nan
    steps = np.diff(times)
    dt = float(np.median(steps))
    if dt <= 0.0 or np.max(np.abs(steps - dt)) > 1e-6 * max(dt, 1e-12) + 1e-12:
        return math.nan
    width = max(1, int(round(SMOOTH_WINDOW_S / dt)))
    width += 1 - width % 2
    jerk = np.gradient(np.gradient(np.gradient(_smooth(points, width), dt, axis=0), dt, axis=0), dt, axis=0)
    return float(np.sqrt(np.mean(np.sum(np.square(jerk[mask]), axis=1))))
