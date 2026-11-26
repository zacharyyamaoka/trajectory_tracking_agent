"""Repeat the p5s-pass3 fit with equal total weight per dev task.

    uv run --all-extras python solutions/p5s-task-balanced-fit/identify_pass.py p5s-onefit

Use the board's configured PD gains and the candidate's gain multipliers to infer excess feedforward from
the recorded joint position and velocity errors. The bases and residual match the original pass.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from robot_controllers.bench.ur5e import UR5E_JOINTS, ur5e_board_config

from solution import KD_SCALE, KP_SCALE, friction_basis, gravity_shapes

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "outputs" / "runs"
RIDGE = 1e-3


def read_moving_samples(source: str):
    records = sorted((RUNS / source / "dev").glob("*.json"))
    if len(records) != 42:
        raise ValueError(f"expected 42 dev run records for {source}, found {len(records)}")

    board = ur5e_board_config()
    kp = KP_SCALE * np.asarray(board.kp_nm_rad)
    kd = KD_SCALE * np.asarray(board.kd_nm_s_rad)
    positions, velocities, errors, task_sizes = [], [], [], []
    for path in records:
        record = json.loads(path.read_text())
        if tuple(record["joint_names"]) != UR5E_JOINTS:
            raise ValueError(f"{path.name} lists different joint names")
        moving = np.asarray(record["moving"], dtype=bool)
        moving_count = int(moving.sum())
        if moving_count == 0:
            raise ValueError(f"{path.name} has no moving samples")
        q_target = np.asarray(record["q_target"], dtype=float)[moving]
        qd_target = np.asarray(record["qd_target"], dtype=float)[moving]
        q_error = np.asarray(record["q"], dtype=float)[moving] - q_target
        qd_error = np.asarray(record["qd"], dtype=float)[moving] - qd_target
        positions.append(q_target)
        velocities.append(qd_target)
        errors.append(kp * q_error + kd * qd_error)
        task_sizes.append(moving_count)

    return np.vstack(positions), np.vstack(velocities), np.vstack(errors), np.array(task_sizes)


def fit(source: str, weighting: str):
    model = json.loads((HERE.parent / source / "model.json").read_text())
    scales = np.asarray(model["basis"]["friction_scales_rad_s"], dtype=float)
    positions, velocities, errors, task_sizes = read_moving_samples(source)
    shapes = gravity_shapes(positions)
    # WHY: the objective aggregates scores by task, so trajectories with more moving samples should not
    # automatically have greater influence on the fit. Normalize the ridge by the same total weight.
    sample_weights = np.repeat(1.0 / task_sizes, task_sizes) if weighting == "task" else np.ones(len(positions))
    root_weight = np.sqrt(sample_weights)
    penalty = RIDGE * sample_weights.sum()

    report = {}
    for joint, name in enumerate(UR5E_JOINTS):
        features = np.column_stack([shapes, friction_basis(velocities[:, joint], scales)])
        error = errors[:, joint]
        weighted_features = features * root_weight[:, None]
        weighted_error = error * root_weight
        correction = np.linalg.solve(
            weighted_features.T @ weighted_features + penalty * np.eye(features.shape[1]),
            weighted_features.T @ weighted_error,
        )
        gravity_count = shapes.shape[1]
        row = model["joints"][name]
        row["gravity_nm"] = (np.asarray(row["gravity_nm"]) - correction[:gravity_count]).tolist()
        row["friction_nm"] = (np.asarray(row["friction_nm"]) - correction[gravity_count:]).tolist()
        after = error - features @ correction
        report[name] = {
            "rms_before_nm": float(np.sqrt(np.average(error**2, weights=sample_weights))),
            "rms_after_nm": float(np.sqrt(np.average(after**2, weights=sample_weights))),
        }

    pass_record = {
        "what": "gravity shapes + friction vs target qd, joint errors",
        "source": source,
        "gains": f"kp x{KP_SCALE:g}, kd x{KD_SCALE:g}",
        "ridge": RIDGE,
        "in_sample": report,
    }
    if weighting == "task":
        pass_record.update({"weighting": "equal total weight per task", "tasks": len(task_sizes)})
    model["passes"].append(pass_record)
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("p5s-onefit",))
    parser.add_argument("--weighting", choices=("task", "sample"), default="task")
    parser.add_argument("--output", type=Path, default=HERE / "model.json")
    args = parser.parse_args()
    model = fit(args.source, args.weighting)
    args.output.write_text(json.dumps(model, indent=1) + "\n")
    for name, metrics in model["passes"][-1]["in_sample"].items():
        print(f"{name:20s} rms {metrics['rms_before_nm']:.3f} -> {metrics['rms_after_nm']:.3f} N·m")


if __name__ == "__main__":
    main()
