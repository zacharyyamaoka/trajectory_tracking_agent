"""Fit an acceleration coefficient per joint from the parent's saved dev runs.

    uv run --all-extras python solutions/p5s-accel-residual/identify_pass.py

The fit adds a feedforward basis at the parent's fixed gains. The PD-error
torque is the fit target, and the parent model is read afresh on every run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.scenarios import base_scenario
from robot_controllers.bench.ur5e import UR5E_JOINTS, ur5e_board_config

from solution import KD_SCALE, KP_SCALE

HERE = Path(__file__).resolve().parent
SOURCE = "p5s-pass3"
RUNS = HERE.parents[1] / "outputs" / "runs" / SOURCE / "dev"
EXPECTED_RECORDS = 42


def moving_samples(path: Path, kp: np.ndarray, kd: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    record = json.loads(path.read_text())
    if (record["schema"], record["solution"], record["split"], record["task"]) != (
        "tta.run_record/1", SOURCE, "dev", path.stem
    ) or tuple(record["joint_names"]) != UR5E_JOINTS:
        raise ValueError(f"{path.name}: unexpected run record identity or joint order")

    clock = np.asarray(record["t"], dtype=float)
    if len(clock) < 3 or not np.isfinite(clock).all() or not np.all(np.diff(clock) > 0):
        raise ValueError(f"{path.name}: expected at least three strictly increasing timestamps")
    target_position = np.asarray(record["q_target"], dtype=float)
    target_velocity = np.asarray(record["qd_target"], dtype=float)
    # Differentiate on this run's own clock before masking to avoid stitching unrelated motions.
    target_acceleration = np.gradient(target_velocity, clock, axis=0, edge_order=2)
    position_error = np.asarray(record["q"], dtype=float) - target_position
    velocity_error = np.asarray(record["qd"], dtype=float) - target_velocity
    moving = np.asarray(record["moving"], dtype=bool)
    return target_position[moving], target_acceleration[moving], (kp * position_error + kd * velocity_error)[moving]


def main() -> None:
    records = sorted(RUNS.glob("*.json"))
    if len(records) != EXPECTED_RECORDS:
        raise SystemExit(f"expected {EXPECTED_RECORDS} saved dev records for {SOURCE}, found {len(records)}")
    board = ur5e_board_config()
    kp = KP_SCALE * np.asarray(board.kp_nm_rad)
    kd = KD_SCALE * np.asarray(board.kd_nm_s_rad)
    positions, accelerations, errors = zip(*(moving_samples(path, kp, kd) for path in records), strict=True)
    position = np.vstack(positions)
    acceleration = np.vstack(accelerations)
    excess_torque = np.vstack(errors)
    if not len(position) or not all(np.isfinite(array).all() for array in (position, acceleration, excess_torque)):
        raise ValueError("the moving samples must contain finite targets and tracking errors")

    stock = registered_arm("ur5e")
    scenario = base_scenario("ur5e")
    inertia = stock.mass_matrix(scenario.model_error)(position)
    inertia_prior = scenario.model_error.scale * np.median(np.diagonal(inertia, axis1=1, axis2=2), axis=0)
    if not np.isfinite(inertia_prior).all() or not np.all(inertia_prior > 0):
        raise ValueError("the given model must have a positive finite diagonal inertia and error scale")

    torque_power = np.mean(excess_torque**2, axis=0)
    # WHY: shrink weakly excited joints by the given inertia error scale. Count one
    # independent run per task so correlated 100 Hz samples do not overwhelm the prior.
    ridge = torque_power / (len(records) * inertia_prior**2)
    curvature = np.mean(acceleration**2, axis=0) + ridge
    # Positive error torque indicates excess feedforward. Apply the negative fitted term.
    coefficient = np.divide(
        -np.mean(acceleration * excess_torque, axis=0),
        curvature,
        out=np.zeros(len(UR5E_JOINTS)),
        where=curvature > 0,
    )
    residual = excess_torque + acceleration * coefficient
    rms_after = np.sqrt(np.mean(residual**2, axis=0))

    model = json.loads((HERE.parent / SOURCE / "model.json").read_text())
    fit = {}
    for joint, correction, prior, before, after in zip(
        UR5E_JOINTS, coefficient, inertia_prior, np.sqrt(torque_power), rms_after, strict=True
    ):
        model["joints"][joint]["acceleration_residual_kg_m2"] = float(correction)
        fit[joint] = {
            "inertia_prior_kg_m2": float(prior),
            "rms_before_nm": float(before),
            "rms_after_nm": float(after),
        }
        print(f"{joint:20} coefficient {correction:+.5f} kg·m², residual RMS {before:.5f} → {after:.5f} N·m")
    model["passes"].append({
        "what": "diagonal target-acceleration basis fitted to PD-error torque",
        "source": SOURCE,
        "gains": f"kp x{KP_SCALE:g}, kd x{KD_SCALE:g}",
        "in_sample": fit,
    })
    (HERE / "model.json").write_text(json.dumps(model, indent=1, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
