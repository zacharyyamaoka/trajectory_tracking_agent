"""Second friction pass: the torque error left as a function of the TARGET joint velocity, from dev joint errors.

    uv run --all-extras python solutions/p5s-fric2/identify_friction2.py p5s-grav   # writes friction2.json beside it

Signal as identify_gravity.py: kp·e + kd·ė per joint (deployment board gains; + = the arm was ahead, excess torque),
from run-record outputs only. Fit per joint, every sample whose target joint velocity is not zero, ridge 1e-3:

    kp_j e_j + kd_j ė_j = sum_s w_js tanh(qd_target_j / s) + w_j qd_target_j,   s in SCALES

Odd in qd (friction is), zero at rest (a stop's hold is the board's PD; dry friction there is anywhere in its band).
WHY the target velocity and not the measured one: the feed-forward is evaluated on the plan, so the curve to correct is
the error as a function of what the plan says, including how a joint sticks when its target creeps (pan at
0.001-0.02 rad/s was ~0.9 N·m short in p5s-grav, ~0.5 N·m over at 0.05-0.1 rad/s).
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
AT_REST_RAD_S = 1e-6


def basis(qd: np.ndarray) -> np.ndarray:
    qd = np.asarray(qd, dtype=float)
    return np.stack([np.tanh(qd / s) for s in SCALES] + [qd], axis=-1)


def main(source: str) -> None:
    files = sorted(glob.glob(str(RUNS / source / "dev" / "*.json")))
    if not files:
        raise SystemExit(f"no run records for {source}: run tta evaluate {source} first")
    board = ur5e_board_config()  # the deployment's public `board`
    kp, kd = np.asarray(board.kp_nm_rad), np.asarray(board.kd_nm_s_rad)
    QD, TE = [], []
    names = None
    for path in files:
        record = json.loads(Path(path).read_text())
        names = record["joint_names"]
        q_target = np.asarray(record["q_target"], dtype=float)
        qd_target = np.asarray(record["qd_target"], dtype=float)
        QD.append(qd_target)
        TE.append(kp * (np.asarray(record["q"], dtype=float) - q_target)
                  + kd * (np.asarray(record["qd"], dtype=float) - qd_target))
    qd, te = np.vstack(QD), np.vstack(TE)
    out = {"source": source, "tasks": len(files), "scales_rad_s": list(SCALES), "ridge": RIDGE,
           "signal": "kp*e + kd*edot (N·m), + = excess torque", "joints": {}}
    for j, name in enumerate(names):
        use = np.abs(qd[:, j]) > AT_REST_RAD_S
        A, y = basis(qd[use, j]), te[use, j]
        weights = np.linalg.solve(A.T @ A + RIDGE * len(y) * np.eye(A.shape[1]), A.T @ y)
        before, after = float(np.sqrt(np.mean(y**2))), float(np.sqrt(np.mean((y - A @ weights) ** 2)))
        out["joints"][name] = {"weights_nm": [float(w) for w in weights], "samples": int(use.sum()),
                               "rms_before_nm": before, "rms_after_nm": after}
        print(f"{name:20s} n {use.sum():5d} rms {before:.3f} -> {after:.3f} N·m  w " + " ".join(f"{w:+.2f}" for w in weights))
    (HERE / "friction2.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "p5s-grav")
