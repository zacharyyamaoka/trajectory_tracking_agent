"""Synthetic, hand-computable inputs for the ruler acceptance tests (lane T owns this file; lane E may not edit it).

numpy only: no MuJoCo, no robot_controllers, no dataset. Every builder returns plain arrays whose metric values a reader can
derive by hand; each derivation sits beside its test in ``test_ruler_acceptance.py``.

WHY constant-velocity lines and closed move intervals: CONTRACT section 6 does not say how the target tool speed is
differentiated (``np.gradient`` on ``t``, forward or backward differences). On a line at constant speed every scheme gives
the same speed at every sample, ends included. And a move whose tool position changes only between its first and last
sample, with a joint speed set on that CLOSED interval, has the moving set [first, last] under every scheme. So the tests
pin the ruler's definition, never one implementation's differencing.
WHY ``start + k / rate`` time grids: that is how a tape's clock is built, so the float rounding the ruler meets in
production (``t[k + 10] - t[k]`` is 0.19999999999999996 at some k) is in the tests too.
"""

from __future__ import annotations

import math

import numpy as np

HOST_RATE_HZ = 50.0  # the ur5e_alone deployment's host rate (OBJECTIVES section 2)
MM = 1e-3  # metres per millimetre: the ruler takes SI metres and reports millimetres
DOF = 6  # UR5e
UR5E_TORQUE_CAPS_NM = np.array([150.0, 150.0, 150.0, 28.0, 28.0, 28.0])  # OBJECTIVES section 2: 150 x3, 28 x3 N*m

U = np.array([2.0, 3.0, 6.0]) / 7.0  # unit (4 + 9 + 36 = 49), deliberately off every axis
V = np.array([3.0, -2.0, 0.0]) / math.sqrt(13.0)  # unit, perpendicular to U (6 - 6 + 0 = 0)
W = np.cross(U, V)  # unit, perpendicular to both
P0 = np.array([0.40, -0.10, 0.30])  # a tool point in front of the arm, m

MOVE = "move"
REST = "rest"


def time_grid(count: int, rate_hz: float = HOST_RATE_HZ, start_s: float = 0.0) -> np.ndarray:
    """``count`` sample times ``start_s + k / rate_hz``, s (built the way a tape's clock is, float rounding included)."""
    return start_s + np.arange(count) / rate_hz


def line(t: np.ndarray, speed_m_s: float, direction: np.ndarray = U, start: np.ndarray = P0) -> np.ndarray:
    """(N, 3) tool points moving along unit ``direction`` at constant ``speed_m_s``: every finite difference is the speed."""
    return start + speed_m_s * (t - t[0])[:, None] * direction


def still_tool(count: int, point: np.ndarray = P0) -> np.ndarray:
    """(N, 3) tool points resting at ``point``."""
    return np.tile(point, (count, 1))


def still_joints(count: int, dof: int = DOF) -> np.ndarray:
    """(N, dof) zero joint speeds, rad/s."""
    return np.zeros((count, dof))


def moving_from_runs(*runs: tuple[str, int]) -> np.ndarray:
    """A moving mask from ``(MOVE | REST, count)`` runs, in order: ``moving_from_runs((MOVE, 5), (REST, 21))``."""
    return np.concatenate([np.full(count, state == MOVE, dtype=bool) for state, count in runs])


def run_indices(*runs: tuple[str, int]) -> list[tuple[str, int, int]]:
    """``(state, first index, last index)`` of each run, both inclusive; same arguments as ``moving_from_runs``."""
    spans, first = [], 0
    for state, count in runs:
        spans.append((state, first, first + count - 1))
        first += count
    return spans


def stop_scene(stop_points: list[np.ndarray], *, move_samples: int = 10, rest_samples: int = 15,
               rate_hz: float = HOST_RATE_HZ) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    """A target that moves (straight, ``move_samples``) to each of ``stop_points`` and rests there ``rest_samples``.

    The first move starts from P0. Returns ``(t, target (N, 3), rests)``, where ``rests`` lists each rest's (first, last)
    sample index. The target is EXACTLY constant from a rest's first to its last sample, so "the target at the stop" is one
    point however the ruler reads it (at t1, or averaged over the hold window).
    """
    segments, previous = [], P0
    for point in stop_points:
        fractions = (np.arange(move_samples) + 1.0) / move_samples  # the move's last sample lands exactly on the point
        segments.append(previous + fractions[:, None] * (point - previous))
        segments.append(still_tool(rest_samples, point))
        previous = point
    target = np.concatenate(segments)
    period = move_samples + rest_samples
    rests = [(k * period + move_samples, k * period + period - 1) for k in range(len(stop_points))]
    return time_grid(len(target), rate_hz), target, rests


def rest_move_rest(rest_before: int = 20, move: int = 25, rest_after: int = 30, speed_m_s: float = 0.05,
                   rate_hz: float = HOST_RATE_HZ) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    """A target at rest at P0, one straight move along U at ``speed_m_s``, then at rest at the move's end.

    Returns ``(t, target_tool (N, 3), target_qd (N, DOF), first, last)``: the move is samples first..last. The tool point is
    P0 up to and including ``first`` and constant from ``last`` on, and joint 6 turns at 0.5 rad/s on the closed interval
    [first, last] (a wrist roll), so the moving set is exactly first..last under central, forward or backward differences.
    """
    count = rest_before + move + rest_after
    t = time_grid(count, rate_hz)
    first, last = rest_before, rest_before + move - 1
    progress = np.clip(t - t[first], 0.0, t[last] - t[first])
    target_tool = P0 + speed_m_s * progress[:, None] * U
    target_qd = still_joints(count)
    target_qd[first : last + 1, 5] = 0.5
    return t, target_tool, target_qd, first, last
