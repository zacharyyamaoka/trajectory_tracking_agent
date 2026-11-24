"""Identify the given model's gravity error per joint from the *joint errors* of dev runs (not the board torque).

    uv run --all-extras python solutions/p5s-grav/identify_gravity.py p5s-chord   # writes gravity.json beside it

WHY the joint error and not the board's torque: the board's applied torque carries +-10 N·m of quantisation buzz on the
big joints (kd times a velocity estimated from 2^14 counts), while the joint error is clean and, at the low frequencies
gravity lives at, the board's PD turns it into torque exactly: an arm ahead of its target by e has had a torque excess
of kp·e + kd·ė (kp, kd: `deployment.board`, public). Only run-record outputs are read (outputs/runs/<source>/dev):
target and measured joints, time. The fit:

    kp_j e_j + kd_j ė_j  =  sum_m c_jm phi_m(q_target)        over samples where |qd_target_j| >= 0.02 rad/s

phi = 1, cos/sin(q2), cos/sin(q2+q3), cos/sin(q2+q3+q4), cos/sin(q2+q3+q4)·cos(q5), cos/sin(q2+q3+q4)·sin(q5), sin(q5),
cos(q5): the shapes a gravity torque can take on an arm whose lift, elbow and wrist_1 axes are parallel and horizontal and
whose pan axis is vertical (joint angles only; no masses or lengths assumed). The solution subtracts the fitted torque.
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
MOVING_RAD_S = 0.02
FEATURES = ("1", "c2", "s2", "c23", "s23", "c234", "s234", "c234c5", "s234c5", "c234s5", "s234s5", "s5", "c5")


def features(q: np.ndarray) -> np.ndarray:
    q = np.atleast_2d(q)
    a2, a23, a234, a5 = q[:, 1], q[:, 1] + q[:, 2], q[:, 1] + q[:, 2] + q[:, 3], q[:, 4]
    return np.column_stack([
        np.ones(len(q)), np.cos(a2), np.sin(a2), np.cos(a23), np.sin(a23), np.cos(a234), np.sin(a234),
        np.cos(a234) * np.cos(a5), np.sin(a234) * np.cos(a5), np.cos(a234) * np.sin(a5), np.sin(a234) * np.sin(a5),
        np.sin(a5), np.cos(a5),
    ])


def main(source: str) -> None:
    files = sorted(glob.glob(str(RUNS / source / "dev" / "*.json")))
    if not files:
        raise SystemExit(f"no run records for {source}: run tta evaluate {source} first")
    # WHY the board config from robot_controllers: it is the deployment's public `board` field (same object)
    board = ur5e_board_config()
    kp, kd = np.asarray(board.kp_nm_rad), np.asarray(board.kd_nm_s_rad)
    Q, QD, E, ED = [], [], [], []
    names = None
    for path in files:
        record = json.loads(Path(path).read_text())
        names = record["joint_names"]
        q_target = np.asarray(record["q_target"], dtype=float)
        Q.append(q_target)
        QD.append(np.asarray(record["qd_target"], dtype=float))
        E.append(np.asarray(record["q"], dtype=float) - q_target)
        ED.append(np.asarray(record["qd"], dtype=float) - np.asarray(record["qd_target"], dtype=float))
    q, qd, e, ed = (np.vstack(v) for v in (Q, QD, E, ED))
    torque_error = kp * e + kd * ed
    phi = features(q)
    out = {"source": source, "tasks": len(files), "features": list(FEATURES), "moving_rad_s": MOVING_RAD_S,
           "signal": "kp*e + kd*edot (deployment.board gains), N·m; + = the arm was ahead: excess torque", "joints": {}}
    for j, name in enumerate(names):
        use = np.abs(qd[:, j]) >= MOVING_RAD_S
        coef, *_ = np.linalg.lstsq(phi[use], torque_error[use, j], rcond=None)
        before = float(np.sqrt(np.mean(torque_error[use, j] ** 2)))
        after = float(np.sqrt(np.mean((torque_error[use, j] - phi[use] @ coef) ** 2)))
        out["joints"][name] = {"coef_nm": [float(c) for c in coef], "samples": int(use.sum()),
                               "rms_before_nm": before, "rms_after_nm": after}
        print(f"{name:20s} n {use.sum():5d}  kp*e+kd*edot rms {before:.3f} -> {after:.3f} N·m")
    (HERE / "gravity.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "p5s-chord")
