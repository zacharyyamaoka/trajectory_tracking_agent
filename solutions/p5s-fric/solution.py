"""p5s-fric: p5s-bus-enc with the friction feed-forward identified from dev runs instead of the given Coulomb term.

Parent p5s-bus-enc. One change: the feed-forward is the given `rigid_body` model (10 % wrong, robot_controllers' base
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
    return LayoutController(trajectory, config)
