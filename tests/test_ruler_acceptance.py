"""Acceptance tests for the frozen ruler v1: CONTRACT section 6's metrics and gates (lane T; READ-ONLY to lane E).

These are the ruler's ruler. Lane E implements ``src/trajectory_tracking_agent/ruler/metrics.py`` and ``ruler/gates.py``
against them and may not edit this file or ``ruler_fixtures.py``; a test lane E believes is wrong goes back to the
dispatcher. Until lane E lands, collection fails on the import below: that is expected (committed red).

Run: ``cd /home/bam/trajectory_tracking_agent && uv run pytest tests/test_ruler_acceptance.py -q``

Every input is synthetic and hand-computable (numpy only: no MuJoCo, no robot_controllers, no dataset); the expected value
of each test is derived in the comment beside it. Units: SI in (m, s, rad, rad/s, N*m), the unit in the name out (mm, %).

KPI key -> gate mapping assumed by ``gate_verdicts`` (the KPI mapping is one task's KPIs; diagnostics ride along in it):

    gate                    reads KPI key                   passes when
    completed            <- "completed" (bool)             is True (a numpy True too)
    stop_error_max_mm    <- "stop_error_max_mm"            <= 1.0 mm
    saturation_share_pct <- "saturation_share_pct"         <= 2.0 %
    limit_violations     <- "limit_violations"             == 0
    floor_clearance      <- "floor_clearance_violations"   == 0

Interpretations this file encodes where section 6 / OBJECTIVES leave a choice (each WHY is beside its tests):

1. Joint "moving" threshold is OBJECTIVES' 0.06 deg/s = 1.0472e-3 rad/s, not arm_motion_bench's 1e-3 rad/s (0.0573 deg/s).
   Tool speed is the norm of the 3-D target velocity, unsmoothed, on the given clock ``t``.
2. A stop's duration is measured on ``t``: a run of non-moving samples, first..last, is a stop when
   ``t[last] - t[first] >= 0.2 s`` (float rounding tolerated: at 50 Hz, ``t[15] - t[5]`` is 0.19999999999999998), and
   ``stop_windows`` returns ``(t[first], t[last])``. So a returned window's own length is its rest time, and t1 never
   passes the tape's last sample. A rest at the very start of the tape is a stop too (the definition says "target at
   rest >= 0.2 s", nothing about arriving).
3. "The last 0.1 s" of a stop: the tests are neutral on whether the sample at exactly ``t1 - 0.1`` is in the window
   (``t1 - 0.1 <= t <= t1``, or the last ``round(0.1 / dt)`` samples) - that sample always carries the window's mean
   error. The target at a stop is held exactly constant, so "the target" can be read at t1 or averaged over the window.
4. Counts are plain Python ``int``, metrics plain ``float`` (numpy float64 is one), verdicts plain ``bool``: they land
   in JSON scorecards and the ledger, where numpy ints and bools do not serialize.
5. Floor clearance has no tolerance: 1 micrometre below ``floor_z`` counts, exactly on it does not.
6. ``admissible`` fails closed on a task whose verdicts lack a gate, as on an empty task list.

The mutation self-check (wrong implementations, and which test kills each) is at the bottom of this file.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from ruler_fixtures import (
    DOF,
    MM,
    MOVE,
    P0,
    REST,
    UR5E_TORQUE_CAPS_NM,
    U,
    V,
    W,
    line,
    moving_from_runs,
    rest_move_rest,
    run_indices,
    still_joints,
    still_tool,
    stop_scene,
    time_grid,
)

from trajectory_tracking_agent.ruler import gates, metrics

NAN = float("nan")


def approx(value):
    return pytest.approx(value, rel=1e-9, abs=1e-12)


def is_plain_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ============================================================================================================ moving_mask
# OBJECTIVES section 4: moving = target tool speed > 1 mm/s OR any target joint speed > 0.06 deg/s.

JOINT_JUST_ABOVE_RAD_S = math.radians(0.061)  # 1.0647e-3 rad/s > 0.06 deg/s = 1.0472e-3 rad/s
JOINT_JUST_BELOW_RAD_S = math.radians(0.059)  # 1.0297e-3 rad/s < 1.0472e-3, but > arm_motion_bench's 1e-3 rad/s


def test_moving_mask_is_one_bool_per_sample():
    t = time_grid(40)
    moving = metrics.moving_mask(t, line(t, 0.01), still_joints(40))
    assert isinstance(moving, np.ndarray)
    assert moving.dtype == bool
    assert moving.shape == (40,)


def test_moving_mask_all_false_at_rest():
    # Tool still (speed 0 m/s) and every joint speed 0 rad/s: neither test fires anywhere.
    t = time_grid(30)
    moving = metrics.moving_mask(t, still_tool(30), still_joints(30))
    assert not moving.any()


@pytest.mark.parametrize("rate_hz", [10.0, 50.0, 1000.0])
def test_moving_mask_tool_speed_just_above_1mm_s_is_moving(rate_hz):
    # 1.01 mm/s along U, joints still: |v| = 1.01e-3 m/s > 1e-3 at every sample (a constant-speed line, so every
    # differencing scheme agrees, ends included). Per axis the speed is at most 6/7 x 1.01 = 0.866 mm/s, so a per-axis
    # test misses it; a test on per-sample steps (ignoring t) sees 1.01 mm/s / rate_hz <= 0.101 mm per sample and misses it.
    t = time_grid(25, rate_hz, start_s=4.2)
    moving = metrics.moving_mask(t, line(t, 1.01 * MM), still_joints(25))
    assert moving.all()


@pytest.mark.parametrize("rate_hz", [10.0, 50.0, 1000.0])
def test_moving_mask_tool_speed_just_below_1mm_s_is_not_moving(rate_hz):
    # 0.99 mm/s along U, joints still: |v| = 0.99e-3 m/s < 1e-3 -> never moving. The sum of the axis speeds,
    # (2 + 3 + 6)/7 x 0.99 = 1.556 mm/s, would wrongly fire.
    t = time_grid(25, rate_hz, start_s=4.2)
    moving = metrics.moving_mask(t, line(t, 0.99 * MM), still_joints(25))
    assert not moving.any()


@pytest.mark.parametrize("sign", [1.0, -1.0])
@pytest.mark.parametrize("joint", range(DOF))
def test_moving_mask_any_one_joint_just_above_0p06_deg_s_is_moving(joint, sign):
    # Tool still; one joint at +-0.061 deg/s, the other five at 0: |qd| = 1.0647e-3 rad/s > 1.0472e-3 -> moving at every
    # sample, whichever joint and either sign (|qd|, not qd; any joint, not joint 0 or all joints).
    target_qd = still_joints(20)
    target_qd[:, joint] = sign * JOINT_JUST_ABOVE_RAD_S
    moving = metrics.moving_mask(time_grid(20), still_tool(20), target_qd)
    assert moving.all()


def test_moving_mask_every_joint_just_below_0p06_deg_s_is_not_moving():
    # Tool still; all six joints at 0.059 deg/s = 1.0297e-3 rad/s, alternating sign: each |qd| < 1.0472e-3 -> not moving.
    # Kills the 1e-3 rad/s threshold (1.0297e-3 > 1e-3) and any sum over joints (6 x 1.03e-3 rad/s).
    target_qd = np.tile(JOINT_JUST_BELOW_RAD_S * np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0]), (20, 1))
    moving = metrics.moving_mask(time_grid(20), still_tool(20), target_qd)
    assert not moving.any()


def test_moving_mask_tool_alone_is_enough():
    # OR semantics: tool at 5 mm/s along V, every joint speed 0 -> moving everywhere (an AND would say nowhere).
    t = time_grid(30)
    moving = metrics.moving_mask(t, line(t, 5.0 * MM, direction=V), still_joints(30))
    assert moving.all()


def test_moving_mask_joints_alone_are_enough():
    # OR semantics: tool still; joint 3 at +0.5 rad/s on samples 5..9 and joint 5 at -0.5 rad/s on 20..24 -> moving on
    # exactly those 10 samples (a wrist roll about the tool axis moves joints, not the tool point).
    target_qd = still_joints(30)
    target_qd[5:10, 2] = 0.5
    target_qd[20:25, 4] = -0.5
    moving = metrics.moving_mask(time_grid(30), still_tool(30), target_qd)
    expected = np.zeros(30, dtype=bool)
    expected[5:10] = True
    expected[20:25] = True
    np.testing.assert_array_equal(moving, expected)


def test_moving_mask_rest_move_rest_is_exactly_the_move():
    # rest_move_rest(): rest 20, move 25 (samples 20..44), rest 30 at 50 Hz. The tool changes position only between
    # samples 20 and 44 and joint 6 turns on [20, 44], so the moving set is exactly 20..44 under any differencing of the
    # UNSMOOTHED target (OBJECTIVES: "target tool speed", no filter; a smoothed target would bleed into the rests).
    t, target_tool, target_qd, first, last = rest_move_rest()
    moving = metrics.moving_mask(t, target_tool, target_qd)
    expected = np.zeros(len(t), dtype=bool)
    expected[first : last + 1] = True
    np.testing.assert_array_equal(moving, expected)


# =========================================================================================================== stop_windows
# A stop = the target at rest >= 0.2 s, returned as (t0, t1) = (t[first rest sample], t[last rest sample]) in seconds.

FLOAT_SENSITIVE_STARTS = [1, 4, 9, 10, 37]  # at 100 Hz, t[k + 20] - t[k] == 0.19999999999999996 for k = 1, 4, 9, 10


@pytest.mark.parametrize("rest_first", FLOAT_SENSITIVE_STARTS)
def test_stop_windows_rest_of_exactly_0p2_s_counts(rest_first):
    # 100 Hz; rest samples rest_first .. rest_first + 20 (21 samples) -> t1 - t0 = 20 x 0.01 s = 0.2 s -> a stop.
    # In float the span is 0.19999999999999996 for several starts: the ruler must not lose a 0.2 s rest to rounding.
    t = time_grid(rest_first + 26, 100.0)
    moving = moving_from_runs((MOVE, rest_first), (REST, 21), (MOVE, 5))
    windows = metrics.stop_windows(t, moving)
    assert len(windows) == 1
    assert windows[0] == approx((t[rest_first], t[rest_first + 20]))


@pytest.mark.parametrize("rest_first", FLOAT_SENSITIVE_STARTS)
def test_stop_windows_rest_of_0p19_s_does_not_count(rest_first):
    # 100 Hz; 20 rest samples -> t1 - t0 = 19 x 0.01 s = 0.19 s < 0.2 s -> no stop. (Counting samples x dt would call
    # this 20 x 0.01 = 0.2 s; the duration is measured on t, see interpretation 2 at the top.)
    t = time_grid(rest_first + 25, 100.0)
    moving = moving_from_runs((MOVE, rest_first), (REST, 20), (MOVE, 5))
    assert metrics.stop_windows(t, moving) == []


def test_stop_windows_at_the_50hz_host_rate():
    # 50 Hz. Rest samples 5..15 (11 samples) span t[15] - t[5] = 0.30 - 0.10 = 0.2 s (0.19999999999999998 in float)
    # -> a stop; rest samples 21..30 (10 samples) span 0.18 s -> not. -> [(0.10, 0.30)].
    runs = ((MOVE, 5), (REST, 11), (MOVE, 5), (REST, 10), (MOVE, 5))
    t = time_grid(36)
    windows = metrics.stop_windows(t, moving_from_runs(*runs))
    assert len(windows) == 1
    assert windows[0] == approx((0.10, 0.30))


def test_stop_windows_several_stops_in_time_order_in_seconds():
    # 100 Hz from t = 3.0 s. Runs: move 10 | rest 25 (samples 10..34: 0.24 s, stop) | move 10 | rest 15 (45..59: 0.14 s,
    # too short) | move 10 | rest 30 (70..99: 0.29 s, stop) | move 10. -> [(3.10, 3.34), (3.70, 3.99)] s: seconds on the
    # given clock (not indices, not seconds from zero), in time order, short rests dropped, stops never merged.
    runs = ((MOVE, 10), (REST, 25), (MOVE, 10), (REST, 15), (MOVE, 10), (REST, 30), (MOVE, 10))
    assert [(state, first, last) for state, first, last in run_indices(*runs) if state == REST] == [
        (REST, 10, 34), (REST, 45, 59), (REST, 70, 99)]  # fmt: skip
    t = time_grid(110, 100.0, start_s=3.0)
    windows = metrics.stop_windows(t, moving_from_runs(*runs))
    assert len(windows) == 2
    assert windows[0] == approx((3.10, 3.34))
    assert windows[1] == approx((3.70, 3.99))


def test_stop_windows_trajectory_ending_at_rest():
    # 50 Hz: move 20 | rest 30 (samples 20..49, to the end). -> [(t[20], t[49])] = [(0.40, 0.98)]: t1 is the last sample,
    # not one period past it.
    t = time_grid(50)
    windows = metrics.stop_windows(t, moving_from_runs((MOVE, 20), (REST, 30)))
    assert len(windows) == 1
    assert windows[0] == approx((0.40, 0.98))


def test_stop_windows_leading_rest_is_a_stop():
    # 50 Hz: rest 15 (samples 0..14: 0.28 s) | move 20 | rest 12 (35..46: 0.22 s). Both rests are >= 0.2 s.
    # -> [(0.00, 0.28), (0.70, 0.92)].
    t = time_grid(47)
    windows = metrics.stop_windows(t, moving_from_runs((REST, 15), (MOVE, 20), (REST, 12)))
    assert len(windows) == 2
    assert windows[0] == approx((0.00, 0.28))
    assert windows[1] == approx((0.70, 0.92))


def test_stop_windows_never_at_rest_is_empty():
    t = time_grid(40)
    assert metrics.stop_windows(t, np.ones(40, dtype=bool)) == []


def test_stop_windows_always_at_rest_is_one_stop():
    # 50 Hz, 30 samples, never moving -> one stop spanning the whole tape: [(0.0, 0.58)].
    t = time_grid(30)
    windows = metrics.stop_windows(t, np.zeros(30, dtype=bool))
    assert len(windows) == 1
    assert windows[0] == approx((0.0, 0.58))


def test_stop_windows_returns_a_list_of_float_pairs():
    t = time_grid(50, start_s=1.0)
    windows = metrics.stop_windows(t, moving_from_runs((MOVE, 10), (REST, 20), (MOVE, 10), (REST, 10)))
    assert isinstance(windows, list)
    for window in windows:
        assert isinstance(window, tuple) and len(window) == 2
        assert all(isinstance(edge, float) for edge in window)


# ================================================================================ tool_track_rms_mm / tool_track_max_mm
# Per sample: |measured - target| (Euclidean, m); over the MOVING samples only: RMS -> mm, max -> mm; none moving -> nan.


def _offsets(target: np.ndarray, offsets_mm: dict[int, np.ndarray]) -> np.ndarray:
    """measured = target, with sample k moved by offsets_mm[k] (a 3-vector in mm)."""
    measured = target.copy()
    for sample, offset in offsets_mm.items():
        measured[sample] += np.asarray(offset) * MM
    return measured


def test_tool_track_constant_2mm_offset_is_2mm():
    # Every sample is 2 mm off along W (a unit vector off every axis): every distance is 2.0 mm -> RMS 2.0, max 2.0.
    # (An RMS over the 3N components, sqrt(mean(d_xyz^2)), would give 2 / sqrt(3) = 1.155.)
    t = time_grid(50)
    target = line(t, 0.1)
    measured = target + 2.0 * MM * W
    moving = np.ones(50, dtype=bool)
    assert metrics.tool_track_rms_mm(target, measured, moving) == approx(2.0)
    assert metrics.tool_track_max_mm(target, measured, moving) == approx(2.0)


def test_tool_track_mixed_offsets_known_rms():
    # Four moving samples off by 1, 2, 2, 4 mm (along U, V, W, -U).
    # RMS = sqrt((1 + 4 + 4 + 16) / 4) = sqrt(6.25) = 2.5 mm; max = 4.0 mm. (Mean 2.25, median 2.0.)
    t = time_grid(4)
    target = line(t, 0.2)
    measured = _offsets(target, {0: 1.0 * U, 1: 2.0 * V, 2: 2.0 * W, 3: -4.0 * U})
    moving = np.ones(4, dtype=bool)
    assert metrics.tool_track_rms_mm(target, measured, moving) == approx(2.5)
    assert metrics.tool_track_max_mm(target, measured, moving) == approx(4.0)


def test_tool_track_only_moving_samples_count():
    # 8 samples; moving at 1, 2, 5, 6 with errors 1, 2, 2, 4 mm; the 4 resting samples (0, 3, 4, 7) are 1000 mm off.
    # -> RMS 2.5 mm, max 4.0 mm, as above: the resting samples change nothing.
    t = time_grid(8)
    target = line(t, 0.2)
    resting = {sample: 1000.0 * V for sample in (0, 3, 4, 7)}
    measured = _offsets(target, {1: 1.0 * U, 2: 2.0 * V, 5: 2.0 * W, 6: -4.0 * U, **resting})
    moving = np.array([False, True, True, False, False, True, True, False])
    assert metrics.tool_track_rms_mm(target, measured, moving) == approx(2.5)
    assert metrics.tool_track_max_mm(target, measured, moving) == approx(4.0)


def test_tool_track_resting_samples_do_not_dilute():
    # 8 samples; the 4 moving ones (0..3) are 2 mm off along U, the 4 resting ones (4..7) exact -> RMS 2.0, max 2.0.
    # (Summing over the moving samples but dividing by all 8 gives sqrt(4 x 4 / 8) = 1.414.)
    t = time_grid(8)
    target = line(t, 0.2)
    measured = _offsets(target, {sample: 2.0 * U for sample in range(4)})
    moving = np.array([True] * 4 + [False] * 4)
    assert metrics.tool_track_rms_mm(target, measured, moving) == approx(2.0)
    assert metrics.tool_track_max_mm(target, measured, moving) == approx(2.0)


def test_tool_track_metres_in_millimetres_out():
    # 0.0123 m off along V at every moving sample -> 12.3 mm (not 0.0123, not 12300).
    t = time_grid(10)
    target = line(t, 0.3)
    measured = target + 0.0123 * V
    moving = np.ones(10, dtype=bool)
    assert metrics.tool_track_rms_mm(target, measured, moving) == approx(12.3)
    assert metrics.tool_track_max_mm(target, measured, moving) == approx(12.3)


def test_tool_track_no_moving_samples_is_nan():
    # CONTRACT section 6: no moving samples -> nan (the task then fails nothing by itself; `completed` decides).
    t = time_grid(10)
    target = still_tool(10)
    measured = target + 3.0 * MM * U
    moving = np.zeros(10, dtype=bool)
    rms = metrics.tool_track_rms_mm(target, measured, moving)
    worst = metrics.tool_track_max_mm(target, measured, moving)
    assert isinstance(rms, float) and math.isnan(rms)
    assert isinstance(worst, float) and math.isnan(worst)


def test_tool_track_returns_float():
    t = time_grid(10)
    target = line(t, 0.3)
    moving = np.ones(10, dtype=bool)
    assert isinstance(metrics.tool_track_rms_mm(target, target + 1e-3 * U, moving), float)
    assert isinstance(metrics.tool_track_max_mm(target, target + 1e-3 * U, moving), float)


# ===================================================================================================== stop_error_max_mm
# Per stop: |target - mean(measured tool over the stop's last 0.1 s)| -> mm; the worst stop; no stops -> 0.0.
# stop_scene() at 50 Hz: each stop is 15 rest samples first..last (t1 - t0 = 0.28 s). Its last 0.1 s is samples
# last-5..last (t1 - 0.1 <= t <= t1) or last-4..last (the last round(0.1 / 0.02) = 5 samples); sample last-5 always
# carries the window's mean error, so either reading gives the same answer. Samples first..last-6 are >= 0.12 s before t1.


def test_stop_error_metres_in_millimetres_out():
    # One stop; the measured tool rests 0.5 mm off along V for the whole stop -> 0.5 mm. The approach (not a stop) is
    # 30 mm off along W and is ignored.
    t, target, rests = stop_scene([P0 + 0.1 * U])
    first, last = rests[0]
    measured = target.copy()
    measured[:first] += 30.0 * MM * W
    measured[first : last + 1] += 0.5 * MM * V
    stops = [(t[first], t[last])]
    assert metrics.stop_error_max_mm(t, target, measured, stops) == approx(0.5)


def test_stop_error_ignores_error_before_the_last_0p1_s():
    # Samples first..last-6 of the stop (9 samples, all >= 0.12 s before t1) are 50 mm off along U; samples last-5..last
    # are 0.5 mm off along V -> 0.5 mm.
    # (The mean over the whole stop would be (9 x 50 U + 6 x 0.5 V) / 15 = 30 U + 0.2 V -> 30.0 mm.)
    t, target, rests = stop_scene([P0 + 0.1 * U])
    first, last = rests[0]
    measured = target.copy()
    measured[first : last - 5] += 50.0 * MM * U
    measured[last - 5 : last + 1] += 0.5 * MM * V
    assert metrics.stop_error_max_mm(t, target, measured, [(t[first], t[last])]) == approx(0.5)


def test_stop_error_zero_mean_oscillation_in_the_last_0p1_s_averages_out():
    # The whole stop is 0.5 mm off along V. On top, samples last-4..last swing +4, -1, -1, -1, -1 mm along U (sum 0) and
    # sample last-5 does not swing -> the mean tool position over the last 0.1 s is 0.5 mm off along V -> 0.5 mm.
    # What is NOT the stop error (each differs): the per-sample distances' max, sqrt(4^2 + 0.5^2) = 4.03 mm, or their
    # mean, (4.03 + 4 x 1.118) / 5 = 1.70 mm; the last sample alone, or any shorter tail of the window (last 2, 3 or 4
    # samples: swing -1 mm on average), sqrt(1^2 + 0.5^2) = 1.118 mm. Only the whole last 0.1 s averages the swing out.
    t, target, rests = stop_scene([P0 + 0.1 * U])
    first, last = rests[0]
    measured = target.copy()
    measured[first : last + 1] += 0.5 * MM * V
    for sample, swing_mm in zip(range(last - 4, last + 1), (4.0, -1.0, -1.0, -1.0, -1.0)):
        measured[sample] += swing_mm * MM * U
    assert metrics.stop_error_max_mm(t, target, measured, [(t[first], t[last])]) == approx(0.5)


def test_stop_error_is_the_worst_stop_against_its_own_target():
    # Three stops at three different targets (100 mm apart), resting 0.3, 0.9 and 0.6 mm off along W, U and V
    # -> max(0.3, 0.9, 0.6) = 0.9 mm. (First 0.3, last 0.6, mean 0.6, median 0.6; comparing every stop with one
    # stop's target would be ~100 mm.)
    points = [P0 + 0.1 * U, P0 + 0.1 * U + 0.1 * V, P0 + 0.1 * V]
    t, target, rests = stop_scene(points)
    measured = target.copy()
    for (first, last), offset in zip(rests, (0.3 * W, 0.9 * U, 0.6 * V)):
        measured[first : last + 1] += offset * MM
    stops = [(t[first], t[last]) for first, last in rests]
    assert metrics.stop_error_max_mm(t, target, measured, stops) == approx(0.9)


def test_stop_error_no_stops_is_zero():
    # CONTRACT section 6: a task with no stops has stop_error_max_mm = 0.0 (it passes that gate). The 40 mm error is
    # never inside a stop, so it cannot matter.
    t = time_grid(30)
    target = line(t, 0.1)
    measured = target + 40.0 * MM * U
    result = metrics.stop_error_max_mm(t, target, measured, [])
    assert isinstance(result, float)
    assert result == 0.0


def test_metrics_compose_on_rest_move_rest():
    # rest_move_rest() at 50 Hz: rest samples 0..19, move 20..44, rest 45..74. moving_mask -> exactly 20..44;
    # stop_windows -> [(t[0], t[19]), (t[45], t[74])] = [(0.00, 0.38), (0.90, 1.48)] s.
    # Measured: 5 mm off along W while moving, 0.4 mm off along V in the first rest, 0.7 mm along V in the second
    # -> tool_track_rms_mm = tool_track_max_mm = 5.0 mm; stop_error_max_mm = max(0.4, 0.7) = 0.7 mm.
    t, target_tool, target_qd, first, last = rest_move_rest()
    measured = target_tool.copy()
    measured[first : last + 1] += 5.0 * MM * W
    measured[:first] += 0.4 * MM * V
    measured[last + 1 :] += 0.7 * MM * V
    moving = metrics.moving_mask(t, target_tool, target_qd)
    stops = metrics.stop_windows(t, moving)
    assert len(stops) == 2
    assert stops[0] == approx((0.00, 0.38))
    assert stops[1] == approx((0.90, 1.48))
    assert metrics.tool_track_rms_mm(target_tool, measured, moving) == approx(5.0)
    assert metrics.tool_track_max_mm(target_tool, measured, moving) == approx(5.0)
    assert metrics.stop_error_max_mm(t, target_tool, measured, stops) == approx(0.7)


# ================================================================================================== saturation_share_pct
# 100 x the share of samples where ANY joint has |tau| >= 0.98 x its own cap. Caps: the UR5e boards, 150 x3, 28 x3 N*m.


def _torques(rows: int, overrides: dict[tuple[int, int], float]) -> np.ndarray:
    """(rows, DOF) torques, 0 N*m except overrides[(sample, joint)]."""
    torque = np.zeros((rows, DOF))
    for (sample, joint), value in overrides.items():
        torque[sample, joint] = value
    return torque


@pytest.mark.parametrize(("joint", "at_98_pct_nm"), [(0, 147.0), (3, 27.44)])
def test_saturation_exactly_0p98_of_the_cap_counts(joint, at_98_pct_nm):
    # 0.98 x 150 = 147.0 and 0.98 x 28 = 27.44 N*m: exactly at 98 % counts (>=, not >). Sample 0 at it, samples 1..3
    # at 0 -> 1 of 4 samples -> 25.0 % (a percentage, not the fraction 0.25).
    torque = _torques(4, {(0, joint): at_98_pct_nm})
    assert metrics.saturation_share_pct(torque, UR5E_TORQUE_CAPS_NM) == approx(25.0)


@pytest.mark.parametrize(("joint", "at_97p9_pct_nm"), [(0, 0.979 * 150.0), (3, 0.979 * 28.0)])
def test_saturation_0p979_of_the_cap_does_not_count(joint, at_97p9_pct_nm):
    # 0.979 x 150 = 146.85 and 0.979 x 28 = 27.412 N*m: below 98 % -> 0 of 4 samples -> 0.0 %.
    torque = _torques(4, {(0, joint): at_97p9_pct_nm})
    assert metrics.saturation_share_pct(torque, UR5E_TORQUE_CAPS_NM) == approx(0.0)


def test_saturation_counts_samples_with_any_joint():
    # 5 samples: sample 0 joint 1 at 149 N*m; sample 2 joints 0 and 5 at 150 and 28 N*m (two joints, ONE sample);
    # samples 1, 3, 4 at 0 -> 2 of 5 samples = 40.0 %. (Joint-samples would give 3 / 30 = 10 % or 3 / 5 = 60 %.)
    torque = _torques(5, {(0, 1): 149.0, (2, 0): 150.0, (2, 5): 28.0})
    assert metrics.saturation_share_pct(torque, UR5E_TORQUE_CAPS_NM) == approx(40.0)


def test_saturation_negative_torque_counts_by_magnitude():
    # Sample 0 joint 0 at -147 N*m (|tau| = 147 = 98 % of 150), sample 1 joint 4 at -28 N*m (100 % of 28)
    # -> 2 of 4 samples = 50.0 %. (A signed test sees -147 < 147 and -28 < 27.44.)
    torque = _torques(4, {(0, 0): -147.0, (1, 4): -28.0})
    assert metrics.saturation_share_pct(torque, UR5E_TORQUE_CAPS_NM) == approx(50.0)


def test_saturation_reads_each_joints_own_cap():
    # 27.5 N*m on joint 0 in sample 0 (18 % of its 150 cap) and on joint 3 in sample 1 (98.2 % of its 28 cap)
    # -> only sample 1 -> 1 of 2 samples = 50.0 %. (Joint 0's cap for all: 0 %; the smallest cap for all: 100 %.)
    torque = _torques(2, {(0, 0): 27.5, (1, 3): 27.5})
    assert metrics.saturation_share_pct(torque, UR5E_TORQUE_CAPS_NM) == approx(50.0)


def test_saturation_returns_float():
    assert isinstance(metrics.saturation_share_pct(_torques(3, {}), UR5E_TORQUE_CAPS_NM), float)


# ======================================================================================================= limit_violations
# Samples with any joint outside [q_lo, q_hi] OR with |qd| > 1.05 x its velocity limit. Three joints with distinct limits;
# the velocity limits are powers of two, so 1.05 x the limit is exact in float: 2.1, 4.2, 1.05 rad/s.

Q_LO = np.array([-1.0, -2.0, -3.0])
Q_HI = np.array([1.5, 2.5, 3.5])
QD_MAX = np.array([2.0, 4.0, 1.0])


def _joint_samples(rows: int, q: dict[tuple[int, int], float] | None = None,
                   qd: dict[tuple[int, int], float] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(rows, 3) q and qd, all 0 (inside every limit) except the given (sample, joint) overrides."""
    positions, velocities = np.zeros((rows, 3)), np.zeros((rows, 3))
    for (sample, joint), value in (q or {}).items():
        positions[sample, joint] = value
    for (sample, joint), value in (qd or {}).items():
        velocities[sample, joint] = value
    return positions, velocities


def test_limit_position_outside_counts():
    # Sample 0 joint 1 at 2.5001 rad (above its 2.5), sample 1 joint 2 at -3.0001 rad (below its -3.0), sample 2 inside
    # -> 2 samples.
    q, qd = _joint_samples(3, q={(0, 1): 2.5001, (1, 2): -3.0001})
    assert metrics.limit_violations(q, qd, Q_LO, Q_HI, QD_MAX) == 2


def test_limit_position_on_the_limit_does_not_count():
    # Sample 0 joint 0 exactly at its upper 1.5 rad, sample 1 joint 1 exactly at its lower -2.0 rad: on the limit is
    # inside the closed range [lo, hi] -> 0.
    q, qd = _joint_samples(2, q={(0, 0): 1.5, (1, 1): -2.0})
    assert metrics.limit_violations(q, qd, Q_LO, Q_HI, QD_MAX) == 0


def test_limit_velocity_above_1p05_counts():
    # Sample 0 joint 1 at 4.21 rad/s (> 1.05 x 4 = 4.2), sample 1 joint 2 at -1.06 rad/s (|.| > 1.05 x 1 = 1.05)
    # -> 2 samples.
    q, qd = _joint_samples(3, qd={(0, 1): 4.21, (1, 2): -1.06})
    assert metrics.limit_violations(q, qd, Q_LO, Q_HI, QD_MAX) == 2


def test_limit_velocity_exactly_1p05_does_not_count():
    # Exactly 1.05 x the limit, both signs: 2.1 on joint 0, -4.2 on joint 1, 1.05 on joint 2 -> 0 (above, not at).
    q, qd = _joint_samples(3, qd={(0, 0): 2.1, (1, 1): -4.2, (2, 2): 1.05})
    assert metrics.limit_violations(q, qd, Q_LO, Q_HI, QD_MAX) == 0


def test_limit_velocity_between_the_limit_and_1p05_does_not_count():
    # Over the limit but within the 5 % allowance: 2.09 on joint 0 (limit 2.0), -1.04 on joint 2 (limit 1.0) -> 0.
    q, qd = _joint_samples(2, qd={(0, 0): 2.09, (1, 2): -1.04})
    assert metrics.limit_violations(q, qd, Q_LO, Q_HI, QD_MAX) == 0


def test_limit_counts_samples_not_violations():
    # Sample 0: joint 0 at 1.6 rad (above 1.5) AND 3.0 rad/s (above 2.1) - one sample, two violations.
    # Sample 1: joint 0 at -1.1 rad, joint 1 at 5.0 rad/s, joint 2 at 3.6 rad - one sample, three violations.
    # Sample 2: clean. -> 2 samples (not 5 violations).
    q, qd = _joint_samples(3, q={(0, 0): 1.6, (1, 0): -1.1, (1, 2): 3.6}, qd={(0, 0): 3.0, (1, 1): 5.0})
    assert metrics.limit_violations(q, qd, Q_LO, Q_HI, QD_MAX) == 2


def test_limit_reads_each_joints_own_limits():
    # Sample 0: joint 2 at 1.5 rad/s (over joint 2's 1.05, under joint 0's 2.1) -> counts.
    # Sample 1: joint 1 at 2.2 rad (inside joint 1's 2.5, outside joint 0's 1.5) -> does not.
    # Sample 2: joint 1 at 3.0 rad/s (under joint 1's 4.2, over joint 0's 2.1) -> does not. -> 1.
    # (Joint 0's limits for all: 2; the widest limits for all: 0.)
    q, qd = _joint_samples(3, q={(1, 1): 2.2}, qd={(0, 2): 1.5, (2, 1): 3.0})
    assert metrics.limit_violations(q, qd, Q_LO, Q_HI, QD_MAX) == 1


def test_limit_violations_returns_int():
    q, qd = _joint_samples(2, q={(0, 0): 9.0})
    result = metrics.limit_violations(q, qd, Q_LO, Q_HI, QD_MAX)
    assert is_plain_int(result) and result == 1


# ============================================================================================= floor_clearance_violations
# Samples where ANY point (tool + link origins) is strictly below floor_z. 7 points per sample: tool + 6 link origins.


def _points_z(rows: int, overrides: dict[tuple[int, int], float], points: int = 7) -> np.ndarray:
    """(rows, points) heights, 0.30 m except overrides[(sample, point)]; point 1 is the base link origin, ON the floor."""
    heights = np.full((rows, points), 0.30)
    heights[:, 1] = 0.0
    for (sample, point), value in overrides.items():
        heights[sample, point] = value
    return heights


def test_floor_point_below_counts():
    # Sample 2's tool point (point 0) at z = -1e-6 m, 1 micrometre below the floor; the base origin sits at exactly 0
    # in every sample -> 1 sample. (No tolerance: OBJECTIVES says "below the floor plane".)
    assert metrics.floor_clearance_violations(_points_z(4, {(2, 0): -1e-6})) == 1


def test_floor_exactly_on_the_floor_does_not_count():
    # Every sample has the base origin at exactly 0.0, and sample 1 has three more points at exactly 0.0 -> 0.
    assert metrics.floor_clearance_violations(_points_z(3, {(1, 0): 0.0, (1, 4): 0.0, (1, 6): 0.0})) == 0


def test_floor_counts_samples_not_points():
    # Sample 0: points 0, 3, 5 below (-0.01, -0.2, -0.05 m); sample 3: point 6 below (-0.001 m) -> 2 samples, not 4 points.
    heights = _points_z(5, {(0, 0): -0.01, (0, 3): -0.2, (0, 5): -0.05, (3, 6): -0.001})
    assert metrics.floor_clearance_violations(heights) == 2


def test_floor_custom_floor_z():
    # floor_z = 0.05 m (every other point raised to 0.30 m, the base origin too):
    # sample 0 lowest 0.0499 (below -> counts), sample 1 lowest 0.05 (on -> doesn't), sample 2 lowest 0.06 (above),
    # sample 3 lowest -0.2 (counts) -> 2. On the default floor_z = 0.0 the same heights give 1 (only sample 3).
    heights = _points_z(4, {(0, 2): 0.0499, (1, 2): 0.05, (2, 2): 0.06, (3, 2): -0.2})
    heights[:, 1] = 0.30
    assert metrics.floor_clearance_violations(heights, floor_z=0.05) == 2
    assert metrics.floor_clearance_violations(heights, 0.05) == 2
    assert metrics.floor_clearance_violations(heights) == 1


def test_floor_clearance_violations_returns_int():
    result = metrics.floor_clearance_violations(_points_z(3, {(0, 0): -1.0}))
    assert is_plain_int(result) and result == 1


# ================================================================================================================== gates

GATE_KPI = {  # the mapping in the module docstring: gate -> the KPI key it reads
    "completed": "completed",
    "stop_error_max_mm": "stop_error_max_mm",
    "saturation_share_pct": "saturation_share_pct",
    "limit_violations": "limit_violations",
    "floor_clearance": "floor_clearance_violations",
}

GOOD_KPIS = {
    "completed": True,
    "stop_error_max_mm": 0.4,
    "saturation_share_pct": 0.5,
    "limit_violations": 0,
    "floor_clearance_violations": 0,
    # The objective and diagnostics ride along in the same mapping. A NaN tracking metric (no moving samples) fails no
    # gate by itself (CONTRACT section 6), so it must not trip fail-closed handling of the gate KPIs.
    "tool_track_rms_mm": NAN,
    "tool_track_max_mm": NAN,
    "energy_j": 12.0,
}


def _verdicts_with(**changes) -> dict[str, bool]:
    return gates.gate_verdicts({**GOOD_KPIS, **changes})


def _assert_only_failing(verdicts: dict[str, bool], failing: set[str]) -> None:
    assert set(verdicts) == set(gates.GATES)
    assert all(isinstance(verdict, bool) for verdict in verdicts.values())
    assert {gate for gate, passed in verdicts.items() if not passed} == failing


def test_gates_tuple_is_frozen():
    assert gates.GATES == (
        "completed", "stop_error_max_mm", "saturation_share_pct", "limit_violations", "floor_clearance")  # fmt: skip
    assert isinstance(gates.GATES, tuple)


def test_gate_verdicts_all_pass_on_good_kpis():
    # Every gate KPI inside its bound; tool_track_* are NaN (no moving samples) -> all five gates pass, as plain bools.
    _assert_only_failing(gates.gate_verdicts(GOOD_KPIS), set())


@pytest.mark.parametrize("bad", ["missing", "none", "nan"])
@pytest.mark.parametrize("gate", list(GATE_KPI))
def test_gate_verdicts_fail_closed(gate, bad):
    # OBJECTIVES section 4: a missing or NaN value is a failed gate, never a pass. Each gate's own KPI is removed, None or
    # NaN -> that gate fails; the other four still pass.
    kpis = dict(GOOD_KPIS)
    if bad == "missing":
        del kpis[GATE_KPI[gate]]
    else:
        kpis[GATE_KPI[gate]] = None if bad == "none" else NAN
    _assert_only_failing(gates.gate_verdicts(kpis), {gate})


@pytest.mark.parametrize(("completed", "passes"), [(True, True), (np.True_, True), (False, False), (np.False_, False)])
def test_gate_completed(completed, passes):
    _assert_only_failing(_verdicts_with(completed=completed), set() if passes else {"completed"})


@pytest.mark.parametrize(("value", "passes"), [(0.0, True), (1.0, True), (1.0001, False), (3.0, False), (math.inf, False)])
def test_gate_stop_error_max_mm_at_most_1mm(value, passes):
    # <= 1.0 mm passes: 1.0 itself passes, 1.0001 fails.
    _assert_only_failing(_verdicts_with(stop_error_max_mm=value), set() if passes else {"stop_error_max_mm"})


@pytest.mark.parametrize(("value", "passes"), [(0.0, True), (2.0, True), (2.0001, False), (100.0, False)])
def test_gate_saturation_share_pct_at_most_2pct(value, passes):
    # <= 2.0 % passes: 2.0 itself passes, 2.0001 fails.
    _assert_only_failing(_verdicts_with(saturation_share_pct=value), set() if passes else {"saturation_share_pct"})


@pytest.mark.parametrize(("value", "passes"), [(0, True), (np.int64(0), True), (1, False), (np.int64(7), False)])
def test_gate_limit_violations_zero(value, passes):
    _assert_only_failing(_verdicts_with(limit_violations=value), set() if passes else {"limit_violations"})


@pytest.mark.parametrize(("value", "passes"), [(0, True), (np.int64(0), True), (1, False), (3, False)])
def test_gate_floor_clearance_reads_floor_clearance_violations(value, passes):
    _assert_only_failing(_verdicts_with(floor_clearance_violations=value), set() if passes else {"floor_clearance"})


def test_gate_floor_clearance_does_not_read_the_verdict_name():
    # The gate reads the KPI "floor_clearance_violations" only; "floor_clearance" is the VERDICT's name.
    # (a) Both keys present and disagreeing (3 violations, a stale "floor_clearance": 0 beside them): the KPI decides
    #     -> fails. Preferring the verdict name here would pass a tool that went through the floor (fail open).
    # (b) Only "floor_clearance": 0, no "floor_clearance_violations": the KPI is MISSING -> fails closed.
    _assert_only_failing(_verdicts_with(floor_clearance_violations=3, floor_clearance=0), {"floor_clearance"})
    kpis = {key: value for key, value in GOOD_KPIS.items() if key != "floor_clearance_violations"}
    kpis["floor_clearance"] = 0
    _assert_only_failing(gates.gate_verdicts(kpis), {"floor_clearance"})


# ------------------------------------------------------------------------------------------------------------- admissible

ALL_PASS = {gate: True for gate in GATE_KPI}


def test_admissible_when_every_task_passes_every_gate():
    assert gates.admissible([dict(ALL_PASS), dict(ALL_PASS), dict(ALL_PASS)]) is True


@pytest.mark.parametrize("gate", list(GATE_KPI))
@pytest.mark.parametrize("task", [0, 1, 2])
def test_admissible_fails_on_any_one_failed_gate(task, gate):
    tasks = [dict(ALL_PASS) for _ in range(3)]
    tasks[task][gate] = False
    assert gates.admissible(tasks) is False


@pytest.mark.parametrize("empty", [[], ()])
def test_admissible_fails_closed_on_no_tasks(empty):
    # No evidence is not a pass: all([]) is True, the ruler's answer is False.
    assert gates.admissible(empty) is False


def test_admissible_fails_closed_on_a_task_missing_a_gate():
    # Task 1 has no floor_clearance verdict -> not "every gate on every task" -> False.
    partial = {gate: True for gate in GATE_KPI if gate != "floor_clearance"}
    assert gates.admissible([dict(ALL_PASS), partial, dict(ALL_PASS)]) is False


def test_admissible_on_gate_verdicts_output():
    good = gates.gate_verdicts(GOOD_KPIS)
    one_bad_stop = _verdicts_with(stop_error_max_mm=1.2)
    assert gates.admissible([good, good]) is True
    assert gates.admissible([good, one_bad_stop]) is False


# -------------------------------------------------------------------------------------------------------------- objective


def test_objective_is_the_median_odd_count():
    # [5, 1, 2] -> sorted [1, 2, 5] -> median 2.0. (Mean 2.67, max 5.)
    result = gates.objective([5.0, 1.0, 2.0])
    assert isinstance(result, float)
    assert result == approx(2.0)


def test_objective_is_the_median_even_count():
    # [1, 10, 2, 3] -> sorted [1, 2, 3, 10] -> median (2 + 3) / 2 = 2.5. (Mean 4.0, max 10, lower/upper middle 2 / 3.)
    assert gates.objective([1.0, 10.0, 2.0, 3.0]) == approx(2.5)


def test_objective_single_task():
    assert gates.objective([0.7]) == approx(0.7)


@pytest.mark.parametrize("position", [0, 2, 4])
def test_objective_any_nan_is_nan(position):
    # One task's objective is NaN -> the objective is NaN (a skipped NaN would give the median of the rest, 2.5).
    values = [1.0, 2.0, 3.0, 4.0]
    values.insert(position, NAN)
    result = gates.objective(values)
    assert isinstance(result, float) and math.isnan(result)


@pytest.mark.parametrize("empty", [[], ()])
def test_objective_of_no_tasks_is_nan(empty):
    result = gates.objective(empty)
    assert isinstance(result, float) and math.isnan(result)


# ====================================================================================================================
MUTATION_SELF_CHECK = """Mutation self-check: plausible wrong rulers, and which test kills each.

A test suite that passes a wrong ruler measures nothing, so each test was proven able to fail. Lane T wrote a scratch
reference ruler (142 / 142 pass) and 64 mutants of it, each one plausible mistake, in the gitignored
outputs/lane_t_mutants/ (make_mutants.py builds them; run_one.py injects a variant as trajectory_tracking_agent.ruler
through sys.modules and runs this file; run_mutants.py prints the table). Re-run:
    cd /home/bam/trajectory_tracking_agent && uv run python outputs/lane_t_mutants/run_mutants.py
Run 2026-11-24: 64 / 64 killed.

The five named in the brief, with the reasoning and then what actually went red:

1. RMS over ALL samples (moving ignored). Resting samples 1000 mm off turn 2.5 mm into ~707 mm; exact resting samples
   dilute 2.0 to 1.41. Killed by test_tool_track_only_moving_samples_count, test_tool_track_resting_samples_do_not_dilute,
   test_metrics_compose_on_rest_move_rest.
2. Saturation |tau| > 0.98 cap instead of >=. 147.0 N*m on a 150 cap (and 27.44 on 28, and -147) stops counting.
   Killed by test_saturation_exactly_0p98_of_the_cap_counts, test_saturation_negative_torque_counts_by_magnitude.
3. Stop error averaged over the WHOLE stop. The 50 mm error before the last 0.1 s pulls the mean to 30 mm.
   Killed by test_stop_error_ignores_error_before_the_last_0p1_s.
4. Objective = max instead of median. [5, 1, 2] -> 5, not 2; [1, 10, 2, 3] -> 10, not 2.5.
   Killed by test_objective_is_the_median_odd_count, test_objective_is_the_median_even_count.
5. NaN treated as pass (a gate written "fail when over the bound", NaN kept as a number: NaN > 1.0 is False).
   Killed by test_gate_verdicts_fail_closed[nan-*]. Note: dropping only the isnan() filter is an EQUIVALENT mutant
   (NaN <= 1.0 and NaN == 0 are already False), which is why this mutant makes both edits.

The rest (mutant -> killing tests):
- moving: 1e-3 rad/s (arm_motion_bench) -> every_joint_just_below_0p06; 0.06 unconverted -> any_one_joint_just_above;
  AND not OR -> tool_alone / joints_alone / just_above; per-axis speed -> tool_speed_just_above; t ignored ->
  tool_speed_just_above, tool_alone; signed joint speed -> any_one_joint_just_above (sign -1), joints_alone;
  3-sample smoothed target -> rest_move_rest_is_exactly_the_move, compose.
- stop_windows: samples x dt duration -> rest_of_0p19_s, 50hz_host_rate; no float tolerance -> exactly_0p2_s,
  50hz_host_rate; > 0.2 s -> exactly_0p2_s; t1 one period past the last rest -> 7 tests; indices not seconds -> 7 tests;
  leading rest dropped -> leading_rest_is_a_stop, always_at_rest, compose; trailing rest dropped -> ending_at_rest,
  leading_rest, always_at_rest, compose.
- stop_error: mean of per-sample distances, max in window, the sample at t1 only, last 0.05 s, last 4 samples ->
  zero_mean_oscillation; first 0.1 s of the stop -> ignores_error_before; mean over stops, one stop's target for all ->
  worst_stop_against_its_own_target, compose; no stops -> NaN -> no_stops_is_zero; metres out -> 5 tests.
- tool_track: sum / all N -> resting_samples_do_not_dilute; RMS over 3N components -> constant_2mm and 5 more; max over
  all samples -> only_moving_samples_count; no moving -> 0.0 -> no_moving_samples_is_nan.
- saturation: share of joint-samples, a fraction not % -> any_joint, exactly_0p98, own_cap, negative_torque; joint 0's
  cap for all -> own_cap, exactly_0p98, negative_torque; signed torque -> negative_torque.
- limits: >= 1.05 x -> exactly_1p05; no 5 % allowance -> between_limit_and_1p05; violations not samples ->
  samples_not_violations; on-limit counts -> on_the_limit; signed velocity -> above_1p05; joint 0's limits for all ->
  own_limits (+3); numpy int returned -> returns_int.
- floor: <= floor -> exactly_on_the_floor (+4); points not samples -> samples_not_points; 1 mm tolerance ->
  point_below (+2); floor_z ignored -> custom_floor_z; tool point only -> samples_not_points, custom_floor_z.
- gates: a missing KPI read as 0 -> fail_closed[missing-limit_violations]; completed truthy (NaN passes) ->
  fail_closed[nan-completed]; stop < 1.0 -> stop_error_max_mm_at_most_1mm[1.0]; saturation bound 0.02 -> every gate
  test; verdict as numpy bool -> every gate test; reads "floor_clearance" as the KPI -> every gate test; PREFERS a
  "floor_clearance" key over "floor_clearance_violations" -> floor_clearance_does_not_read_the_verdict_name.
- admissible: empty -> True -> fails_closed_on_no_tasks; only the verdicts present -> task_missing_a_gate; any task
  enough -> any_one_failed_gate (+2).
- objective: nanmedian -> any_nan_is_nan; mean -> median_odd / median_even; lower middle on even counts ->
  median_even; no tasks -> 0.0 -> of_no_tasks_is_nan.
"""
