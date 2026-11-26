"""Fit the additional term from the parent's saved dev trajectories.

    uv run --all-extras python solutions/p5s-friction-asym/identify_pass.py

The parent model is read afresh on every run. Estimate excess feedforward from the
position and velocity tracking errors with the same PD gains as the parent.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from robot_controllers.bench.ur5e import UR5E_JOINTS, ur5e_board_config

from solution import KD_SCALE, KP_SCALE, asymmetric_friction_basis

HERE = Path(__file__).resolve().parent
SOURCE = "p5s-pass3"
RUNS = HERE.parents[1] / "outputs" / "runs" / SOURCE / "dev"
EXPECTED_RECORDS = 42
# Reuse the midpoint of the parent's established friction scales for the transition to Coulomb drag.
SCALE_RAD_S = 0.035
RIDGE = 1e-3


def moving_samples(path: Path, kp: np.ndarray, kd: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    record = json.loads(path.read_text())
    if (record["schema"], record["solution"], record["split"], record["task"]) != (
        "tta.run_record/1", SOURCE, "dev", path.stem
    ) or tuple(record["joint_names"]) != UR5E_JOINTS:
        raise ValueError(f"{path.name}: unexpected run record identity or joint order")

    target_velocity = np.asarray(record["qd_target"], dtype=float)
    position_error = np.asarray(record["q"], dtype=float) - np.asarray(record["q_target"], dtype=float)
    velocity_error = np.asarray(record["qd"], dtype=float) - target_velocity
    moving = np.asarray(record["moving"], dtype=bool)
    return target_velocity[moving], (kp * position_error + kd * velocity_error)[moving]


def main() -> None:
    records = sorted(RUNS.glob("*.json"))
    if len(records) != EXPECTED_RECORDS:
        raise SystemExit(f"expected {EXPECTED_RECORDS} saved dev records for {SOURCE}, found {len(records)}")

    board = ur5e_board_config()
    kp = KP_SCALE * np.asarray(board.kp_nm_rad)
    kd = KD_SCALE * np.asarray(board.kd_nm_s_rad)
    velocities, errors = zip(*(moving_samples(path, kp, kd) for path in records), strict=True)
    basis = asymmetric_friction_basis(np.vstack(velocities), SCALE_RAD_S)
    excess_torque = np.vstack(errors)
    if len(basis) == 0 or not np.isfinite(basis).all() or not np.isfinite(excess_torque).all():
        raise ValueError("the moving samples must contain finite target velocities and tracking errors")

    # A positive tracking error corresponds to excess feedforward, so subtract the fitted component.
    coefficient = -np.sum(basis * excess_torque, axis=0) / (np.sum(basis**2, axis=0) + RIDGE * len(basis))
    residual = excess_torque + basis * coefficient
    rms_before = np.sqrt(np.mean(excess_torque**2, axis=0))
    rms_after = np.sqrt(np.mean(residual**2, axis=0))
    model = json.loads((HERE.parent / SOURCE / "model.json").read_text())
    model["basis"]["asymmetric_friction_scale_rad_s"] = SCALE_RAD_S
    fit = {}
    for joint, correction, before, after in zip(UR5E_JOINTS, coefficient, rms_before, rms_after, strict=True):
        model["joints"][joint]["asymmetric_friction_nm"] = float(correction)
        fit[joint] = {"rms_before_nm": float(before), "rms_after_nm": float(after)}
        print(f"{joint:20} coefficient {correction:+.5f} N·m, residual RMS {before:.5f} → {after:.5f} N·m")
    model["passes"].append({
        "what": "bounded even-velocity term fitted to PD-error torque",
        "source": SOURCE,
        "gains": f"kp x{KP_SCALE:g}, kd x{KD_SCALE:g}",
        "ridge": RIDGE,
        "in_sample": fit,
    })
    (HERE / "model.json").write_text(json.dumps(model, indent=1, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
