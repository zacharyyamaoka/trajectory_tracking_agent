"""P7s from robot_controllers' population: model at plan time, computed-torque gains re-sent each tick, calibrated lookahead, secant_mid_ff.

Generation 0 (hand-written): the config exactly as robot_controllers grades it on the UR5e base scenario (every model it
is given 10 % wrong, the boards' own gains x1), built for this deployment's host rate and bus. "calibrated" lookahead is
robot_controllers' own bus calibration (its calibration target at this bus and rate, never a task of this repo).
"""

from __future__ import annotations

import dataclasses

from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.population import config, config_spec
from robot_controllers.bench.scenarios import base_scenario

CONFIG = "P7s"


def build(trajectory, deployment):
    """A robot_controllers LayoutController (a robot_msgs JointController) for `trajectory` on `deployment`."""
    scenario = dataclasses.replace(
        base_scenario(deployment.arm), host_rate_hz=deployment.host_rate_hz, bus=deployment.bus
    )
    if config(CONFIG).ff_model == "trajectory" and trajectory.effort is None:
        # WHY fill the effort column: the "as built" feed-forward is the column a planner fills from the model it has
        # (robot_controllers scenarios.GivenEffortScript), so it is the arm's rigid_body model under the same model error
        model = registered_arm(deployment.arm).feedforward("rigid_body", scenario.model_error)
        effort = model(trajectory.positions, trajectory.velocities, trajectory.accelerations)
        trajectory = dataclasses.replace(trajectory, effort=effort)
    spec = config_spec(CONFIG, scenario)
    return spec.build(trajectory, control_period_s=1.0 / deployment.host_rate_hz)
