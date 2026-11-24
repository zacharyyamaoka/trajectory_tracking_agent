"""p5s-chord: p5s-fric with the position target moved off the chord, onto the least-squares line of the curve.

Parent p5s-fric. One change: each command's position is the sampled reference minus a(s + T/2)·T²/12 (a the
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
    feedforward = IdentifiedFriction(given, trajectory.joint_names)
    board = deployment.board
    board_lead_s = board.encoder_delay_s + 1.0 / board.rate_hz  # 0.5 ms + 0.25 ms
    bus_delay_s = deployment.bus.per_joint(len(deployment.joint_names))
    lookahead_s = tuple(max(0.0, float(delay) - board_lead_s) for delay in bus_delay_s)
    layout = Layout("plan", "board", lookahead_s=lookahead_s, interpolation="secant_mid_ff")
    config = LayoutConfig(feedforward=feedforward, feedback=None, layout=layout,
                          control_period_s=1.0 / deployment.host_rate_hz)
    return ChordCorrected(LayoutController(trajectory, config), trajectory, lookahead_s, 1.0 / deployment.host_rate_hz)
