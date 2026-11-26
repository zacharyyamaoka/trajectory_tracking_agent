"""A residual fit over reference tapes and the JointState received at each host tick."""

from __future__ import annotations

import numpy as np

from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.scenarios import base_scenario
from robot_controllers.controllers.layout import LayoutConfig, LayoutController
from robot_controllers.models import Layout, PD


FEATURE_NAMES = (
    "bias", "cos_lift", "cos_lift_elbow", "cos_lift_elbow_wrist",
    "sin_lift", "sin_lift_elbow", "sin_lift_elbow_wrist", "tanh_velocity", "velocity",
)


def features(positions: np.ndarray, velocities: np.ndarray) -> np.ndarray:
    """Per-joint gravity shapes, smooth signed friction, and viscous velocity in SI."""
    lift, elbow, wrist = np.moveaxis(positions[..., 1:4], -1, 0)
    lower_angles = np.stack([lift, lift + elbow, lift + elbow + wrist], axis=-1)
    gravity = np.concatenate([np.ones_like(lift)[..., None], np.cos(lower_angles), np.sin(lower_angles)], axis=-1)
    across_joints = np.broadcast_to(gravity[..., None, :], (*velocities.shape, gravity.shape[-1]))
    friction = np.stack([np.tanh(velocities / 0.05), velocities], axis=-1)
    return np.concatenate([across_joints, friction], axis=-1)


def fit(observations, kp, kd, *, ridge=0.001):
    """A positive measured-minus-target error implies a negative feedforward correction."""
    positions, velocities, position_errors, velocity_errors = (
        np.concatenate([observation[column] for observation in observations]) for column in range(4)
    )
    regressors = features(positions, velocities)
    target_torque = -(kp * position_errors + kd * velocity_errors)
    coefficients = []
    design_diagnostics = []
    for joint in range(velocities.shape[1]):
        design = regressors[:, joint, :]
        rank = int(np.linalg.matrix_rank(design))
        if rank != design.shape[1]:
            raise ValueError(f"joint {joint} calibration rank {rank} < {design.shape[1]}")
        penalty = ridge * len(design) * np.eye(design.shape[1])
        coefficients.append(np.linalg.solve(design.T @ design + penalty, design.T @ target_torque[:, joint]))
        design_diagnostics.append({"rank": rank, "condition_number": float(np.linalg.cond(design))})
    return np.asarray(coefficients), design_diagnostics


def build(trajectory, deployment, coefficients):
    scenario = base_scenario(deployment.arm)
    given = registered_arm(deployment.arm).feedforward("rigid_body", scenario.model_error)
    board = deployment.board
    board_lead_s = board.encoder_delay_s + 1.0 / board.rate_hz
    lookahead_s = tuple(max(0.0, float(delay) - board_lead_s) for delay in deployment.bus.per_joint(len(trajectory.joint_names)))
    layout = Layout("plan", "board", lookahead_s=lookahead_s, interpolation="secant_mid_ff")
    feedback = PD(board.kp_nm_rad, board.kd_nm_s_rad)

    def feedforward(q, qd, qdd):
        torque = given(q, qd, qdd)
        if coefficients is None:
            return torque
        return torque + np.sum(features(q, qd) * coefficients, axis=-1)

    config = LayoutConfig(feedforward=feedforward, feedback=feedback, layout=layout,
                          control_period_s=1.0 / deployment.host_rate_hz)
    return LayoutController(trajectory, config)
