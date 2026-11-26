"""p5s-filter-history: use the board-rate target velocity history in p5s-pass3's damping compensation.

Parent p5s-pass3. Its fitted model and board commands stay in place. The only change is replacing the acceleration-based
velocity lag correction with the target velocity minus its delayed, filtered estimate at each plan sample.

p5s-onefit: p5s-pass2's controller with its four stacked fits merged into one model.json (merge_stack.py, no new data).

The controller, all of it (gen-1 lane lineage p5s -> p5s-bus -> p5s-bus-enc -> p5s-fric -> p5s-chord -> p5s-grav ->
p5s-fric2 -> p5s-kp2 -> p5s-kp4 -> p5s-vlag -> p5s-pass2; each step's WHY is in that solution's docstring):

- **Feed-forward at plan time** (once per trajectory sample, sampled at the middle of each host period, secant_mid_ff):
  the given `rigid_body` model (10 % wrong, robot_controllers' base scenario), plus the identified friction
  `sum_s w_js tanh(qd_j / s) + w_j qd_j` and gravity error `sum_m c_jm phi_m(q)` (model.json), minus
  `kd_j * (qd_target_j - qd_filtered_j)`. The target approximation uses the public encoder delay, backward
  difference and filter coefficient without assuming the encoder's actual quantized position.
- **Feedback on the board**: PD at kp 4 x and kd 2 x the boards' configured gains (`deployment.board`), sent with every
  command. Transfer risk: the twin has no compliance, so stiffness is cheap here.
- **Timing**: each joint samples its reference at bus command delay - (encoder delay + one board tick) ahead, so the
  board's PD balances with the joint on the target at the same instant.
- **Shape**: each command's position is the sample minus a(s + T/2) T²/12, so the board's straight walk over a host
  period is the least-squares line of the curve, not its chord.

Everything identified comes from dev run records (measured joints and the boards' applied torque, outputs of
`tta evaluate`), never from the plant; everything else is a public deployment field or a given model.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.scenarios import base_scenario
from robot_controllers.controllers.layout import LayoutConfig, LayoutController
from robot_controllers.models import PD, Layout

MODEL = json.loads((Path(__file__).resolve().parent / "model.json").read_text())
KP_SCALE = 4.0
KD_SCALE = 2.0


def gravity_shapes(q):
    """The shapes a gravity torque takes on this arm (pan axis vertical; lift, elbow, wrist_1 parallel): (N, 6) -> (N, 13)."""
    q = np.atleast_2d(np.asarray(q, dtype=float))
    a2, a23, a234, a5 = q[:, 1], q[:, 1] + q[:, 2], q[:, 1] + q[:, 2] + q[:, 3], q[:, 4]
    return np.column_stack([
        np.ones(len(q)), np.cos(a2), np.sin(a2), np.cos(a23), np.sin(a23), np.cos(a234), np.sin(a234),
        np.cos(a234) * np.cos(a5), np.sin(a234) * np.cos(a5), np.cos(a234) * np.sin(a5), np.sin(a234) * np.sin(a5),
        np.sin(a5), np.cos(a5),
    ])


def friction_basis(qd, scales):
    """Odd in qd, zero at rest: tanh(qd / s) for each scale, then qd: (..., n) -> (..., n, S + 1)."""
    qd = np.asarray(qd, dtype=float)
    return np.concatenate([np.tanh(qd[..., None] / scales), qd[..., None]], axis=-1)


def target_velocity_lag(sample_times, target_velocities, board):
    """Ideal target minus the board's filtered velocity estimate, sampled at the plan knots."""
    times = np.asarray(sample_times, dtype=float) - sample_times[0]
    velocities = np.asarray(target_velocities, dtype=float)
    if len(times) == 1:
        return velocities.copy()

    dt = board.dt_s
    ticks = np.arange(int(np.ceil(times[-1] / dt)) + 1) * dt
    delayed_times = np.clip(ticks - board.delay_ticks * dt, 0.0, times[-1])
    intervals = np.diff(times)[:, None]
    slopes = np.diff(velocities, axis=0) / intervals
    knot_displacement = np.vstack([np.zeros(velocities.shape[1]),
                                   np.cumsum(0.5 * intervals * (velocities[:-1] + velocities[1:]), axis=0)])
    segment = np.minimum(np.searchsorted(times, delayed_times, side="right") - 1, len(times) - 2)
    local_time = (delayed_times - times[segment])[:, None]
    # WHY integrate: the board differentiates two delayed positions. An interval average of the reference
    # velocity is that backward difference, including when the board interval spans two tape segments.
    delayed_displacement = knot_displacement[segment] + local_time * (
        velocities[segment] + 0.5 * local_time * slopes[segment]
    )
    filtered = np.zeros((len(ticks), velocities.shape[1]))  # the board resets at rest
    alpha = board.filter_alpha
    for tick, encoder_velocity in enumerate(np.diff(delayed_displacement, axis=0) / dt, start=1):
        previous = filtered[tick - 1]
        filtered[tick] = previous + alpha * (encoder_velocity - previous)
    # A board holds its estimate between ticks. The small tolerance covers float rounding on exact grid points.
    knot_ticks = np.floor(times / dt + 1e-9).astype(int)
    return velocities - filtered[knot_ticks]


class IdentifiedModel:
    """`ff(q, qd, qdd)`: the given model + model.json's friction and gravity terms (pure; (n,) or (N, n))."""

    def __init__(self, given, joint_names):
        rows = [MODEL["joints"][name] for name in joint_names]
        self.given = given
        self.scales = np.asarray(MODEL["basis"]["friction_scales_rad_s"], dtype=float)
        self.friction = np.array([row["friction_nm"] for row in rows])  # (n, S + 1)
        self.gravity = np.array([row["gravity_nm"] for row in rows]).T  # (13, n)

    def __call__(self, q, qd, qdd):
        gravity = gravity_shapes(q) @ self.gravity
        if np.ndim(q) == 1:
            gravity = gravity[0]
        friction = np.sum(friction_basis(qd, self.scales) * self.friction, axis=-1)
        return np.asarray(self.given(q, qd, qdd), dtype=float) + friction + gravity


class ChordCorrected:
    """The layout controller with each command's position moved by -a(s + T/2)·T²/12 (everything else its own)."""

    def __init__(self, inner, trajectory, lookahead_s, period_s):
        self._inner = inner
        self._t = np.asarray(trajectory.t, dtype=float)
        self._end = float(self._t[-1])
        self._acceleration = np.asarray(trajectory.accelerations, dtype=float)
        self._lookahead = np.asarray(lookahead_s, dtype=float)
        self._period = float(period_s)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def tick(self, state, dt):
        command, defines = self._inner.tick(state, dt)
        if self._inner.status != "running" and self._inner.status != "done":
            return command, defines  # an abort's hold is the JTC's, untouched
        middle = self._inner.clock_s + self._lookahead + 0.5 * self._period
        shift = np.zeros(len(middle))
        for joint, when in enumerate(middle):
            if when < self._end:  # held at rest after the end: no curvature
                shift[joint] = np.interp(when, self._t, self._acceleration[:, joint]) * self._period**2 / 12.0
        position = np.asarray(command.position, dtype=float) - shift
        return dataclasses.replace(command, position=position), defines


def build(trajectory, deployment):
    """A robot_controllers LayoutController (a robot_msgs JointController) for `trajectory` on `deployment`."""
    scenario = dataclasses.replace(
        base_scenario(deployment.arm), host_rate_hz=deployment.host_rate_hz, bus=deployment.bus
    )
    board = deployment.board
    period_s = 1.0 / deployment.host_rate_hz
    kp = tuple(KP_SCALE * float(k) for k in board.kp_nm_rad)
    kd = tuple(KD_SCALE * float(k) for k in board.kd_nm_s_rad)
    given = registered_arm(deployment.arm).feedforward("rigid_body", scenario.model_error)
    model = IdentifiedModel(given, trajectory.joint_names)
    lag_torque = np.asarray(kd) * target_velocity_lag(trajectory.t, trajectory.velocities, board)

    def feedforward(q, qd, qdd):
        # WHY keep the correction on the original plan grid: the layout still samples every other term at
        # each joint's existing midpoint reference time.
        return model(q, qd, qdd) - lag_torque

    board_lead_s = board.encoder_delay_s + 1.0 / board.rate_hz  # 0.5 ms + 0.25 ms
    bus_delay_s = deployment.bus.per_joint(len(deployment.joint_names))
    lookahead_s = tuple(max(0.0, float(delay) - board_lead_s) for delay in bus_delay_s)
    layout = Layout("plan", "board", lookahead_s=lookahead_s, interpolation="secant_mid_ff")
    config = LayoutConfig(feedforward=feedforward, feedback=PD(kp, kd), layout=layout, control_period_s=period_s)
    return ChordCorrected(LayoutController(trajectory, config), trajectory, lookahead_s, period_s)
