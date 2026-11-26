"""A board-PD driver using the pendulum model identified from development JointState messages."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from robot_controllers.bench.arms import arm
from robot_controllers.controllers.layout import LayoutConfig, LayoutController
from robot_controllers.models import Layout, PD


@dataclass(frozen=True)
class Feedforward:
    coefficients: dict
    damping_lag: float

    def __call__(self, angle, speed, acceleration):
        model = self.coefficients
        return (model["gravity_sin_nm"] * np.sin(angle) + model["gravity_cos_nm"] * np.cos(angle)
                + model["coulomb_nm"] * np.tanh(speed / 0.03) + model["viscous_nm_s_rad"] * speed
                + (model["inertia_kg_m2"] - self.damping_lag) * acceleration)


class ChordController:
    def __init__(self, inner, target, period, lookahead):
        self.inner = inner
        self.target = target
        self.period = period
        self.lookahead = lookahead

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def tick(self, state, dt):
        command, marks = self.inner.tick(state, dt)
        if self.status == "aborted":
            return command, marks
        midpoint = self.inner.clock_s + self.lookahead + self.period / 2
        acceleration = np.interp(midpoint, self.target.t, self.target.accelerations[:, 0], right=0.0)
        # WHY subtract this offset: the board walks a straight line between commands. Use its least-squares fit
        # to the curved target, reducing the error from a chord through the two endpoints.
        return replace(command, position=command.position - acceleration * self.period ** 2 / 12), marks


@dataclass(frozen=True)
class IdentifiedSpec:
    scenario: object
    coefficients: dict
    gain_scale: float = 1.0
    damping_scale: float = 1.0
    name: str = "can11_identified_feedforward"

    def build(self, target, **_overrides):
        board = arm(self.scenario.arm).board_config()
        period = 1.0 / self.scenario.host_rate_hz
        kp = board.kp_nm_rad[0] * self.gain_scale
        kd = board.kd_nm_s_rad[0] * self.damping_scale
        # WHY subtract board lookahead and the damping lag separately: advancing the position setpoint would otherwise
        # double-count the board's own tick, while the filtered velocity adds a separate acceleration-dependent torque.
        board_lead = board.encoder_delay_s + 1.0 / board.rate_hz
        lookahead = self.scenario.bus.per_joint(1)[0] - board_lead
        velocity_lag = board.encoder_delay_s + 1.0 / (2 * np.pi * board.velocity_filter_hz)
        config = LayoutConfig(feedforward=Feedforward(self.coefficients, kd * velocity_lag), feedback=PD((kp,), (kd,)),
                              layout=Layout("plan", "board", lookahead_s=lookahead, interpolation="secant_mid_ff"),
                              control_period_s=period)
        return ChordController(LayoutController(target, config), target, period, lookahead)
