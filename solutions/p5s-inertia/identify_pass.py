"""Fit an inertia-augmented residual from a source solution's saved dev run records.

    uv run --all-extras python solutions/p5s-inertia/identify_pass.py p5s-onefit

Signal: M(q)·ë + KD_SCALE kd·ė + KP_SCALE kp·e, with e = measured − target. The board gains and mass matrix come
from the given model and the source controller. A positive residual means excess feedforward torque. Keep the source
model's gravity and friction bases, ridge, and moving samples. Subtract the fitted residual from the source weights.
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.scenarios import base_scenario
from robot_controllers.bench.ur5e import ur5e_board_config

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "outputs" / "runs"
RIDGE = 1e-3


def scale(source: Path, name: str) -> float:
    match = re.search(rf"^{name} = ([0-9.]+)$", (source / "solution.py").read_text(), re.MULTILINE)
    if match is None:
        raise SystemExit(f"{source.name}/solution.py has no '{name} = <number>' line")
    return float(match.group(1))


def main(source: str) -> None:
    files = sorted(glob.glob(str(RUNS / source / "dev" / "*.json")))
    if not files:
        raise SystemExit(f"no run records for {source}: run tta evaluate {source} first")
    sys.path.insert(0, str(HERE))
    from solution import friction_basis, gravity_shapes  # noqa: E402 - this folder's own bases

    source_folder = HERE.parent / source
    model = json.loads((source_folder / "model.json").read_text())
    scales = np.asarray(model["basis"]["friction_scales_rad_s"], dtype=float)
    kp_scale, kd_scale = scale(source_folder, "KP_SCALE"), scale(source_folder, "KD_SCALE")
    board = ur5e_board_config()  # the deployment's public `board`
    kp, kd = kp_scale * np.asarray(board.kp_nm_rad), kd_scale * np.asarray(board.kd_nm_s_rad)
    scenario = base_scenario("ur5e")
    mass_matrix = registered_arm("ur5e").mass_matrix(scenario.model_error)
    Q, QD, TE, MV = [], [], [], []
    names = None
    for path in files:
        record = json.loads(Path(path).read_text())
        names = record["joint_names"]
        q_target = np.asarray(record["q_target"], dtype=float)
        qd_target = np.asarray(record["qd_target"], dtype=float)
        Q.append(q_target)
        QD.append(qd_target)
        MV.append(np.asarray(record["moving"], dtype=bool))
        position_error = np.asarray(record["q"], dtype=float) - q_target
        velocity_error = np.asarray(record["qd"], dtype=float) - qd_target
        # WHY differentiate within each run: the reset between trajectories is not an acceleration sample.
        acceleration_error = np.gradient(velocity_error, np.asarray(record["t"], dtype=float), axis=0, edge_order=2)
        inertial_torque = (mass_matrix(q_target) @ acceleration_error[..., None])[..., 0]
        TE.append(kp * position_error + kd * velocity_error + inertial_torque)
    q, qd, te = np.vstack(Q), np.vstack(QD), np.vstack(TE)
    moving = np.concatenate(MV)
    shapes = gravity_shapes(q[moving])
    report = {}
    for j, name in enumerate(names):
        A = np.column_stack([shapes, friction_basis(qd[moving, j], scales)])
        y = te[moving, j]
        w = np.linalg.solve(A.T @ A + RIDGE * len(y) * np.eye(A.shape[1]), A.T @ y)
        n_gravity = shapes.shape[1]
        row = model["joints"][name]
        row["gravity_nm"] = [float(a - b) for a, b in zip(row["gravity_nm"], w[:n_gravity], strict=True)]
        row["friction_nm"] = [float(a - b) for a, b in zip(row["friction_nm"], w[n_gravity:], strict=True)]
        report[name] = {"rms_before_nm": float(np.sqrt(np.mean(y**2))),
                        "rms_after_nm": float(np.sqrt(np.mean((y - A @ w) ** 2)))}
        print(f"{name:20s} rms {report[name]['rms_before_nm']:.3f} -> {report[name]['rms_after_nm']:.3f} N·m")
    model["passes"].append({"what": "gravity and friction from PD plus inertial tracking error torque", "source": source,
                            "gains": f"kp x{kp_scale:g}, kd x{kd_scale:g}", "ridge": RIDGE, "in_sample": report})
    (HERE / "model.json").write_text(json.dumps(model, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
