"""p5s-fric2-pass2: a niche at the boards' own configured gains: p5s-fric2 plus one more joint-error pass.

Parent p5s-fric2. One change: the feed-forward also subtracts, per joint, the 13 gravity shapes, the odd friction basis
and a term in the joint's own target acceleration, with weights `identify_pass2.py` fitted jointly to p5s-fric2's dev
joint errors as torque at the configured gains (`pass2.json`).

WHY a niche (gen-1 lane): the main line went to kp x4 (p5s-kp4 onwards), which the twin rewards because it has no
compliance. This line keeps the gains the boards are configured with, so it is the more transferable candidate; it
takes the same identification step p5s-pass2 took on the stiff line (-27 % there), plus the qdd term that p5s-vlag
handled physically on the stiff line (here it is fitted: at 6 Hz the board-lag lead is not its static value).

p5s-fric2 (parent p5s-grav, one change: the feed-forward also subtracts, per joint, f_j(qd) = sum_s w_js tanh(qd / s) + w_j qd
(s = 2, 5, 10, 20, 50, 100, 200 mrad/s) with w fitted by `identify_friction2.py` to p5s-grav's dev joint errors as
torque (kp·e + kd·ė, deployment board gains) against the target joint velocity (`friction2.json`).

WHY (gen-1 lane): 43 % of p5s-grav's squared tool error is at tool speeds under 0.1 m/s. Binned by target velocity,
pan and lift are ~0.9 N·m short when their target creeps at 1-20 mrad/s (they stick, e.g. pan in workspace-dev-009 lags
0.05 deg into its stop) and ~0.5 N·m over at 50-100 mrad/s. The first friction fit (identify.py) was against the
measured velocity of the board torque; this one is against what the plan says, which is what the feed-forward reads.

Before that, p5s-grav (parent p5s-chord, one change: the feed-forward subtracts, per joint, a torque sum_m c_jm phi_m(q) whose shapes phi are the
trigonometric forms a gravity torque takes on this arm (1, cos/sin of q2, q2+q3, q2+q3+q4, those times cos/sin q5) and
whose coefficients `identify_gravity.py` fits to p5s-chord's dev joint errors as torque, kp·e + kd·ė with the
deployment's board gains (`gravity.json`).

WHY (gen-1 lane): every solution so far, p4s included, has lift +0.0099 deg, elbow +0.0075 deg and wrist_1 +0.015 deg
of constant lead; that is a torque excess shaped like gravity (the given model's links are 10 % off). The joint error is
a clean torque sensor at low frequency (the board's tau is not: kd times a 2^14-count velocity estimate buzzes by
+-10 N·m). In-sample, kp·e + kd·ė rms: lift 1.40 -> 0.64 N·m, elbow 0.55 -> 0.30, wrist_1 0.106 -> 0.036.

Kept from p5s-chord (its parent p5s-fric, one change: each command's position is the sampled reference minus a(s + T/2)·T²/12 (a the
trajectory's own acceleration in the middle of the host period T, per joint at its own lookahead), velocity unchanged.

WHY (gen-1 lane): between two commands the board walks its setpoint in a straight line at the secant velocity, so over
each 20 ms it tracks the chord of the curve, which sits above a convex stretch by (a/2)·tau·(T - tau), on average
a·T²/12. The arm low-passes the reference and follows that mean: every joint of p5s-fric leads by +0.0021..0.0029 deg
per rad/s² (wrists; regression of joint error on qdd), and T²/12 at 50 Hz is 0.0019 deg per rad/s². The line
p(s) - a·T²/12 + v_secant·tau is the least-squares fit of the parabola over the period: mean error 0.

Kept from p5s-fric (its parent p5s-bus-enc, one change: the feed-forward is the given `rigid_body` model (10 % wrong, robot_controllers' base
scenario) plus, per joint, `Fc tanh(qd / vs) + b qd` with Fc, vs, b identified by `identify.py` from p5s-bus-enc's dev
run records (measured q, qd, the boards' applied torque; nothing from the plant) and stored in `identified.json`.
The given model's own Coulomb term (`rigid_body_coulomb`: one frictionloss per joint, 10 % high, tanh(qd / 0.01)) is
dropped.

WHY (gen-1 lane): binning the board torque minus the given rigid_body model by measured joint velocity shows each
joint's friction curve. wrist_2's builds up slowly (0.19 N·m at 0.05-0.1 rad/s, 0.45 at 0.1-0.2, 0.77 above 0.2) and
wrist_3 has almost none (0.015 N·m), so the given Coulomb at full strength above 0.01 rad/s over-pushes them: in
p5s-bus-enc wrist_2 led its target by +0.127 deg in the direction of motion (regression on sign(qd)), wrist_3 by
+0.38 deg. The fitted numbers (identify.py p5s-bus-enc):

    joint     Fc (N·m)  vs (rad/s)  b (N·m·s/rad)
    pan        3.786     0.020        +0.041
    lift       3.487     0.020        +0.018
    elbow      3.847     0.035        -0.056
    wrist_1    0.802     0.050        -0.034
    wrist_2    0.815     0.200        -0.040
    wrist_3    0.015     0.075        +0.082

Kept from p5s-bus-enc: model at plan time (the column is evaluated once per trajectory sample), board PD at the boards'
own gains, secant_mid_ff interpolation, lookahead_j = bus command delay_j - (board encoder delay + one board tick).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.scenarios import base_scenario
from robot_controllers.controllers.layout import LayoutConfig, LayoutController
from robot_controllers.models import Layout

IDENTIFIED = json.loads((Path(__file__).resolve().parent / "identified.json").read_text())
GRAVITY = json.loads((Path(__file__).resolve().parent / "gravity.json").read_text())
FRICTION2 = json.loads((Path(__file__).resolve().parent / "friction2.json").read_text())
PASS2 = json.loads((Path(__file__).resolve().parent / "pass2.json").read_text())


class Pass2Corrected:
    """`ff(q, qd, qdd)` minus pass 2's gravity shapes, friction curve and qdd term (pure; (n,) or (N, n))."""

    def __init__(self, base, joint_names):
        self.base = base
        self.gravity = np.array([PASS2["joints"][name]["gravity_nm"] for name in joint_names]).T  # (13, n)
        self.friction = np.array([PASS2["joints"][name]["friction_nm"] for name in joint_names])  # (n, S + 1)
        self.acceleration = np.array([PASS2["joints"][name]["qdd_nm_s2_rad"] for name in joint_names])
        self.scales = np.asarray(PASS2["scales_rad_s"], dtype=float)

    def __call__(self, q, qd, qdd):
        qd = np.asarray(qd, dtype=float)
        gravity = gravity_features(q) @ self.gravity
        if np.ndim(q) == 1:
            gravity = gravity[0]
        terms = np.concatenate([np.tanh(qd[..., None] / self.scales), qd[..., None]], axis=-1)
        return (np.asarray(self.base(q, qd, qdd), dtype=float) - gravity - np.sum(terms * self.friction, axis=-1)
                - self.acceleration * np.asarray(qdd, dtype=float))


class FrictionCorrected:
    """`ff(q, qd, qdd)` minus the second-pass friction curve f_j(qd_j) (pure; (n,) or (N, n))."""

    def __init__(self, base, joint_names):
        self.base = base
        self.scales = np.asarray(FRICTION2["scales_rad_s"], dtype=float)
        self.weights = np.array([FRICTION2["joints"][name]["weights_nm"] for name in joint_names])  # (n, S + 1)

    def __call__(self, q, qd, qdd):
        qd = np.asarray(qd, dtype=float)
        terms = np.concatenate([np.tanh(qd[..., None] / self.scales), qd[..., None]], axis=-1)  # (..., n, S + 1)
        return np.asarray(self.base(q, qd, qdd), dtype=float) - np.sum(terms * self.weights, axis=-1)


def gravity_features(q):
    """The shapes of a gravity torque on this arm, (N, 6) -> (N, 13); see identify_gravity.py."""
    q = np.atleast_2d(np.asarray(q, dtype=float))
    a2, a23, a234, a5 = q[:, 1], q[:, 1] + q[:, 2], q[:, 1] + q[:, 2] + q[:, 3], q[:, 4]
    return np.column_stack([
        np.ones(len(q)), np.cos(a2), np.sin(a2), np.cos(a23), np.sin(a23), np.cos(a234), np.sin(a234),
        np.cos(a234) * np.cos(a5), np.sin(a234) * np.cos(a5), np.cos(a234) * np.sin(a5), np.sin(a234) * np.sin(a5),
        np.sin(a5), np.cos(a5),
    ])


class GravityCorrected:
    """`ff(q, qd, qdd)` minus the identified gravity-shaped torque excess (pure; (n,) or (N, n))."""

    def __init__(self, base, joint_names):
        self.base = base
        self.coef = np.array([GRAVITY["joints"][name]["coef_nm"] for name in joint_names]).T  # (13, n)

    def __call__(self, q, qd, qdd):
        values = np.asarray(self.base(q, qd, qdd), dtype=float)
        correction = gravity_features(q) @ self.coef
        return values - (correction[0] if np.ndim(q) == 1 else correction)


class IdentifiedFriction:
    """`ff(q, qd, qdd)`: a given model plus per-joint `Fc tanh(qd / vs) + b qd` (pure; (n,) or (N, n))."""

    def __init__(self, base, joint_names):
        rows = [IDENTIFIED["joints"][name] for name in joint_names]
        self.base = base
        self.coulomb = np.array([row["coulomb_nm"] for row in rows])
        self.vs = np.array([row["vs_rad_s"] for row in rows])
        self.viscous = np.array([row["viscous_nm_s_rad"] for row in rows])

    def __call__(self, q, qd, qdd):
        qd = np.asarray(qd, dtype=float)
        return np.asarray(self.base(q, qd, qdd), dtype=float) + self.coulomb * np.tanh(qd / self.vs) + self.viscous * qd


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
    given = registered_arm(deployment.arm).feedforward("rigid_body", scenario.model_error)
    feedforward = GravityCorrected(IdentifiedFriction(given, trajectory.joint_names), trajectory.joint_names)
    feedforward = FrictionCorrected(feedforward, trajectory.joint_names)
    feedforward = Pass2Corrected(feedforward, trajectory.joint_names)
    board = deployment.board
    board_lead_s = board.encoder_delay_s + 1.0 / board.rate_hz  # 0.5 ms + 0.25 ms
    bus_delay_s = deployment.bus.per_joint(len(deployment.joint_names))
    lookahead_s = tuple(max(0.0, float(delay) - board_lead_s) for delay in bus_delay_s)
    layout = Layout("plan", "board", lookahead_s=lookahead_s, interpolation="secant_mid_ff")
    config = LayoutConfig(feedforward=feedforward, feedback=None, layout=layout,
                          control_period_s=1.0 / deployment.host_rate_hz)
    return ChordCorrected(LayoutController(trajectory, config), trajectory, lookahead_s, 1.0 / deployment.host_rate_hz)
