"""p5s-damping185-mount-aware: rotate the inherited axial gravity compensation with the arm mount.

The public base-frame gravity is -Z for the upright arm and +Z for the upside-down portal. Both the
given model's gravity term and the parent's fitted upright gravity residual are linear in signed
axial gravity. Reorient those alone, with no new fit and no change to the upright calculation.

The controller, all of it (gen-1 lane lineage p5s -> p5s-bus -> p5s-bus-enc -> p5s-fric -> p5s-chord -> p5s-grav ->
p5s-fric2 -> p5s-kp2 -> p5s-kp4 -> p5s-vlag -> p5s-pass2; each step's WHY is in that solution's docstring):

- **Feed-forward at plan time** (once per trajectory sample, sampled at the middle of each host period, secant_mid_ff):
  the given `rigid_body` model (10 % wrong, robot_controllers' base scenario) with the mounted gravity term,
  plus the identified friction `sum_s w_js tanh(qd_j / s) + w_j qd_j` and mounted gravity error
  `sum_m c_jm phi_m(q)` (model.json), minus `kd_j tau_v qdd_j`,
  the torque the board's own damping adds while accelerating because its velocity estimate lags by
  tau_v = encoder delay + 1/(2 pi velocity filter Hz) = 1.3 ms.
- **Feedback on the board**: PD at kp 4 x and kd 2 x the boards' configured gains (`deployment.board`), sent with every
  command. Transfer risk: the twin has no compliance, so stiffness is cheap here.
- **Timing**: each joint samples its reference at bus command delay - (encoder delay + one board tick) ahead, so the
  board's PD balances with the joint on the target at the same instant.
- **Shape**: each command's position is the sample minus a(s + T/2) T²/12, so the board's straight walk over a host
  period is the least-squares line of the curve.

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
KD_SCALE = 1.85
REFERENCE_GRAVITY_M_S2 = -9.81


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


class IdentifiedModel:
    """`ff(q, qd, qdd)`: the given model + model.json's friction and gravity terms - kd tau_v qdd (pure; (n,) or (N, n))."""

    def __init__(self, given, joint_names, kd_tau_v, gravity_scale=1.0, given_gravity=None):
        rows = [MODEL["joints"][name] for name in joint_names]
        self.given = given
        self.scales = np.asarray(MODEL["basis"]["friction_scales_rad_s"], dtype=float)
        self.friction = np.array([row["friction_nm"] for row in rows])  # (n, S + 1)
        self.gravity = np.array([row["gravity_nm"] for row in rows]).T  # (13, n)
        self.kd_tau_v = np.asarray(kd_tau_v, dtype=float)
        self.gravity_scale = gravity_scale
        self.given_gravity = given_gravity

    def __call__(self, q, qd, qdd):
        gravity = gravity_shapes(q) @ self.gravity
        if np.ndim(q) == 1:
            gravity = gravity[0]
        friction = np.sum(friction_basis(qd, self.scales) * self.friction, axis=-1)
        given = np.asarray(self.given(q, qd, qdd), dtype=float)
        if self.given_gravity is not None:
            # WHY subtract only the nominal static term: flipping the entire model also flips inertia and Coriolis.
            given = given + (self.gravity_scale - 1.0) * self.given_gravity(q, qd, qdd)
            gravity = self.gravity_scale * gravity
        return given + friction + gravity - self.kd_tau_v * np.asarray(qdd, dtype=float)


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
    velocity_lag_s = board.encoder_delay_s + 1.0 / (2.0 * np.pi * board.velocity_filter_hz)
    gravity = np.asarray(deployment.gravity_m_s2, dtype=float)
    if gravity.shape != (3,) or not np.isfinite(gravity).all() or np.any(np.abs(gravity[:2]) > 1e-9):
        raise ValueError("mount-aware feedforward requires vertical gravity in the arm's base frame")
    gravity_scale = float(gravity[2] / REFERENCE_GRAVITY_M_S2)
    make_model = registered_arm(deployment.arm).feedforward
    given = make_model("rigid_body", scenario.model_error)
    given_gravity = None if gravity_scale == 1.0 else make_model("gravity", scenario.model_error)
    feedforward = IdentifiedModel(given, trajectory.joint_names, np.asarray(kd) * velocity_lag_s,
                                  gravity_scale, given_gravity)
    board_lead_s = board.encoder_delay_s + 1.0 / board.rate_hz  # 0.5 ms + 0.25 ms
    bus_delay_s = deployment.bus.per_joint(len(deployment.joint_names))
    lookahead_s = tuple(max(0.0, float(delay) - board_lead_s) for delay in bus_delay_s)
    layout = Layout("plan", "board", lookahead_s=lookahead_s, interpolation="secant_mid_ff")
    config = LayoutConfig(feedforward=feedforward, feedback=PD(kp, kd), layout=layout, control_period_s=period_s)
    return ChordCorrected(LayoutController(trajectory, config), trajectory, lookahead_s, period_s)
