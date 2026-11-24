"""p5s-bus: P5s (model + Coulomb at plan time, board PD, secant_mid_ff) with the lookahead read from the deployment's bus.

Parent p5s. One change: the lookahead is each joint's command delay on `deployment.bus` (a public deployment field,
robot_controllers `timing.lookahead_from`), not robot_controllers' "calibrated" lookahead.

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
    # the one change: a BusTiming as the "calibration" makes config_spec read lookahead_from(bus) = each command delay
    spec = config_spec(CONFIG, scenario, calibration=deployment.bus)
    return spec.build(trajectory, control_period_s=1.0 / deployment.host_rate_hz)
