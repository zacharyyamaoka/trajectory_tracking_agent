"""p5s-bus-enc: p5s-bus with the board's own lead taken out of the lookahead.

Parent p5s-bus. One change: lookahead_j = bus command delay_j - board encoder delay - one board tick (all public
deployment fields: `deployment.bus`, `deployment.board.encoder_delay_s`, `deployment.board.rate_hz`).

WHY (gen-1 lane, p5s-bus dev run records): every big joint and wrist_1 *leads* its target by 0.042-0.046 deg per rad/s
(regression of joint error on qd over all moving samples), i.e. 0.73-0.80 ms. The board explains it: it walks its
setpoint by velocity*dt before it uses it (0.25 ms at 4 kHz) and closes on a position measured 0.5 ms ago, so at constant
speed its PD balances with the joint (0.25 + 0.5) ms ahead of the setpoint. Sampling the reference that much less
ahead puts the joint on the target at the same instant.

Kept from p5s-bus:

WHY (gen-1 lane, from p4s/p5s dev run records): the calibration's "friction-aware bus delay" for the UR5e at 50 Hz is
1.25/2.5/4.5/8.75/10.75/8.0 ms against the bus's 1.25/2.5/3.75/5.0/6.25/7.5 ms. The extra 3.75/4.5 ms on the wrists is
dry-friction lag the calibration folded into a time shift: in p4s, wrist_1 leads by up to 0.55 deg at 3 rad/s
(workspace-dev-038). p5s adds the Coulomb term to the feed-forward *and* keeps that inflated lookahead, so friction is
compensated twice (p5s tool_lag_ms -3.8, wrist_1 0.5 deg RMS). With Coulomb in the feed-forward the lookahead only
has to cover the bus.
"""

from __future__ import annotations

import dataclasses

from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.population import config, config_spec
from robot_controllers.bench.scenarios import base_scenario

CONFIG = "P5s"


def build(trajectory, deployment):
    """A robot_controllers LayoutController (a robot_msgs JointController) for `trajectory` on `deployment`."""
    scenario = dataclasses.replace(
        base_scenario(deployment.arm), host_rate_hz=deployment.host_rate_hz, bus=deployment.bus
    )
    if config(CONFIG).ff_model == "trajectory" and trajectory.effort is None:
        model = registered_arm(deployment.arm).feedforward("rigid_body", scenario.model_error)
        effort = model(trajectory.positions, trajectory.velocities, trajectory.accelerations)
        trajectory = dataclasses.replace(trajectory, effort=effort)
    board = deployment.board
    board_lead_s = board.encoder_delay_s + 1.0 / board.rate_hz  # 0.5 ms + 0.25 ms
    bus_delay_s = deployment.bus.per_joint(len(deployment.joint_names))
    lookahead_s = tuple(max(0.0, float(delay) - board_lead_s) for delay in bus_delay_s)
    spec = config_spec(CONFIG, scenario, calibration=lookahead_s)
    return spec.build(trajectory, control_period_s=1.0 / deployment.host_rate_hz)
