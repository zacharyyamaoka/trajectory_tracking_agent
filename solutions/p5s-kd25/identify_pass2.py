"""Second joint-error pass at the gains this lineage now sends: gravity shapes and the friction basis, fitted jointly.

    uv run --all-extras python solutions/p5s-pass2/identify_pass2.py p5s-vlag 4.0 2.0   # -> pass2.json

Signal: KP_SCALE·kp_j·e_j + KD_SCALE·kd_j·ė_j, the torque the board's PD actually produced from the error (kp, kd: the
deployment's board; the scales: what the source solution sends). Regressors per joint, least squares with ridge 1e-3 on
every moving sample (any joint's target moving): the 13 gravity shapes of identify_gravity.py and the odd friction basis
of identify_friction2.py in the joint's own target velocity. Only run-record outputs are read.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
from robot_controllers.bench.ur5e import ur5e_board_config

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "outputs" / "runs"
SCALES = (0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2)
RIDGE = 1e-3


def gravity_shapes(q: np.ndarray) -> np.ndarray:
    q = np.atleast_2d(q)
    a2, a23, a234, a5 = q[:, 1], q[:, 1] + q[:, 2], q[:, 1] + q[:, 2] + q[:, 3], q[:, 4]
    return np.column_stack([
        np.ones(len(q)), np.cos(a2), np.sin(a2), np.cos(a23), np.sin(a23), np.cos(a234), np.sin(a234),
        np.cos(a234) * np.cos(a5), np.sin(a234) * np.cos(a5), np.cos(a234) * np.sin(a5), np.sin(a234) * np.sin(a5),
        np.sin(a5), np.cos(a5),
    ])


def friction_basis(qd: np.ndarray) -> np.ndarray:
    qd = np.asarray(qd, dtype=float)
    return np.stack([np.tanh(qd / s) for s in SCALES] + [qd], axis=-1)


def main(source: str, kp_scale: float, kd_scale: float) -> None:
    files = sorted(glob.glob(str(RUNS / source / "dev" / "*.json")))
    if not files:
        raise SystemExit(f"no run records for {source}: run tta evaluate {source} first")
    board = ur5e_board_config()  # the deployment's public `board`
    kp, kd = kp_scale * np.asarray(board.kp_nm_rad), kd_scale * np.asarray(board.kd_nm_s_rad)
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
        TE.append(kp * (np.asarray(record["q"], dtype=float) - q_target)
                  + kd * (np.asarray(record["qd"], dtype=float) - qd_target))
    q, qd, te = np.vstack(Q), np.vstack(QD), np.vstack(TE)
    moving = np.concatenate(MV)
    shapes = gravity_shapes(q)
    out = {"source": source, "tasks": len(files), "kp_scale": kp_scale, "kd_scale": kd_scale,
           "scales_rad_s": list(SCALES), "ridge": RIDGE, "joints": {}}
    for j, name in enumerate(names):
        A = np.column_stack([shapes[moving], friction_basis(qd[moving, j])])
        y = te[moving, j]
        w = np.linalg.solve(A.T @ A + RIDGE * len(y) * np.eye(A.shape[1]), A.T @ y)
        before, after = float(np.sqrt(np.mean(y**2))), float(np.sqrt(np.mean((y - A @ w) ** 2)))
        out["joints"][name] = {"gravity_nm": [float(v) for v in w[:13]], "friction_nm": [float(v) for v in w[13:]],
                               "samples": int(moving.sum()), "rms_before_nm": before, "rms_after_nm": after}
        print(f"{name:20s} rms {before:.3f} -> {after:.3f} N·m")
    (HERE / "pass2.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]))
