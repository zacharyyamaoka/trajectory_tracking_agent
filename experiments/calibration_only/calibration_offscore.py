"""Run a deterministic, simulation-only identification proof on generated tapes."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.loop import run_episode
from robot_msgs.trajectory import JointLimits
from robot_trajectories import JointSpace, chain, hold, multisine
from trajectory_tracking_agent.evaluate import TIME_BOX_FACTOR, _SolutionSpec, _rung, _score
from trajectory_tracking_agent.ruler.deployment import deployment

import calibration_model as candidate


# The second pair changes both the phase seed and the centre. Separate generated validation tapes are not ruler splits.
TRAIN_CASES = ((2718, (0, 0, 0, 0, 0, 0)), (2818, (15, 20, -11, 16, -18, 5)))
VALIDATION_CASES = ((3141, (-10, 8, 6, -10, 12, 4)), (3241, (8, -12, 12, 9, 16, -4)))


def build_tape(dep, case):
    seed, centre_offset_deg = case
    centre = np.asarray(registered_arm(dep.arm).home_q) + np.deg2rad(centre_offset_deg)
    extent = np.deg2rad(11.0)
    limits = JointLimits(
        joint_names=dep.joint_names,
        min_position=np.maximum(dep.position_min_rad, centre - extent),
        max_position=np.minimum(dep.position_max_rad, centre + extent),
        max_velocity=dep.velocity_max_rad_s,
        max_acceleration=np.full(len(dep.joint_names), 12.0),  # excitation design parameter, not a physical rating
    )
    space = JointSpace.from_limits(limits, home=centre, rate_hz=100.0)
    excitation = multisine(space, band_hz=(0.2, 1.6), period_s=8, periods=1, seed=seed)
    tape = chain(excitation, hold(space, duration_s=0.6, start=excitation))
    if tape.effort is not None or np.any(dep.link_points(tape.positions)[:, :, 2] < dep.floor_z_m):
        raise ValueError(f"calibration seed {seed} does not have a clean kinematic reference")
    return tape


class Recorder:
    """Record the exact messages already delivered through the controller boundary."""

    def __init__(self, inner, states):
        self.inner = inner
        self.states = states

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def tick(self, state, dt):
        self.states.append(state)
        return self.inner.tick(state, dt)


def run(dep, tape, seed, coefficients):
    states = []
    public = SimpleNamespace(arm=dep.arm, host_rate_hz=dep.host_rate_hz, board=dep.board, bus=dep.bus)

    def build(reference, _):
        return Recorder(candidate.build(reference, public, coefficients), states)

    task = SimpleNamespace(id=f"calibration-{seed}", kind="multisine", trajectory=tape)
    start = time.perf_counter()
    limit = TIME_BOX_FACTOR * float(tape.t[-1])
    spec = _SolutionSpec("unfitted" if coefficients is None else "calibration-fit", build, dep, start + limit, limit)
    log = run_episode(spec, _rung(task, dep), seed=0, plant_factory=dep.plant)
    scored = _score(task, dep, log, spec, time.perf_counter() - start, limit)
    if spec.failure or spec.watched.failure or any(event["kind"] in {"abort", "diverged"} for event in log.events):
        raise RuntimeError(f"calibration seed {seed} failed to finish: {scored['notes']}")
    if len(states) != len(log.tick_t):
        raise RuntimeError(f"calibration seed {seed} has an incomplete host observation record")

    sample_times = np.array([state.header.stamp for state in states])
    np.testing.assert_array_equal(sample_times, log.state_stamp)
    times, keep = np.unique(sample_times, return_index=True)
    positions = np.array([states[index].position for index in keep])
    velocities = np.array([states[index].velocity for index in keep])
    # Align the reference to when the actual sample was taken, not when its bus reply reached the host.
    valid = (times > float(tape.t[0])) & (times < float(tape.t[-1]))
    ref = tape.resample(times[valid])
    moving = np.any(np.abs(ref.velocities) > np.deg2rad(0.06), axis=1)
    observations = (ref.positions[moving], ref.velocities[moving],
                    (positions[valid] - ref.positions)[moving], (velocities[valid] - ref.velocities)[moving])
    summary = {"tool_track_rms_mm": scored["objective"], "gates": scored["verdicts"], "gate_inputs": scored["kpis"],
               "moving_observations": int(moving.sum()), "host_ticks": len(states)}
    return summary, observations


def main(output: Path):
    dep = deployment("ur5e_alone")
    training = []
    observations = []
    validation = []
    for case in TRAIN_CASES:
        seed = case[0]
        tape = build_tape(dep, case)
        initial, observation = run(dep, tape, seed, None)
        training.append({"seed": seed, "centre_deg_from_home": case[1], "tape_sha256": tape_digest(tape), **initial})
        observations.append(observation)
    coefficients, design = candidate.fit(observations, np.asarray(dep.board.kp_nm_rad), np.asarray(dep.board.kd_nm_s_rad))
    for case in VALIDATION_CASES:
        seed = case[0]
        tape = build_tape(dep, case)
        before, _ = run(dep, tape, seed, None)
        after, _ = run(dep, tape, seed, coefficients)
        validation.append({"seed": seed, "centre_deg_from_home": case[1], "tape_sha256": tape_digest(tape),
                           "unfitted": before, "fitted": after})
    digests = [row["tape_sha256"] for row in [*training, *validation]]
    if len(set(digests)) != len(digests):
        raise ValueError("calibration training and validation tapes overlap")
    result = {"scope": "simulation-only off-score experiment", "model_joint_order": dep.joint_names,
              "feature_names": candidate.FEATURE_NAMES, "learned_feedforward_coefficients": coefficients.tolist(),
              "feature_matrix_diagnostics_by_joint": design,
              "training": training, "independent_validation": validation}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for row in validation:
        print(f"calibration validation {row['seed']}: {row['unfitted']['tool_track_rms_mm']:.6f} -> "
              f"{row['fitted']['tool_track_rms_mm']:.6f} mm; fitted gates {row['fitted']['gates']}")
    print(output)


def tape_digest(tape):
    digest = hashlib.sha256()
    for array in (tape.t, tape.positions, tape.velocities, tape.accelerations):
        digest.update(np.asarray(array, dtype="<f8").tobytes())
    return digest.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="write compact calibration evidence JSON here")
    main(parser.parse_args().output)
