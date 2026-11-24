"""One more identification pass, added into this folder's model.json (the loop's model-improvement step, one command).

    uv run --all-extras tta new <id> --parent <a solution with model.json> --change "identification pass on <source>"
    uv run --all-extras python solutions/<id>/identify_pass.py <source>     # <source>: a solution with dev run records

Signal: the torque the board's PD produced from the tracking error, KP_SCALE kp_j e_j + KD_SCALE kd_j ė_j (kp, kd: the
deployment's public board gains; the scales: read from this folder's solution.py, which must be what <source> ran).
Positive = the arm was ahead = the feed-forward had that much too much torque. Per joint, ridge-regularised least squares
on every moving sample of <source>'s dev run records (outputs of `tta evaluate`: target and measured joints, nothing from
the plant), on model.json's own bases: the 13 gravity shapes of q_target and the odd friction basis of the joint's
target velocity. The fit is subtracted from model.json's weights and the pass is appended to model.json["passes"].
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
from robot_controllers.bench.ur5e import ur5e_board_config

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "outputs" / "runs"
RIDGE = 1e-3


def scale(name: str) -> float:
    match = re.search(rf"^{name} = ([0-9.]+)$", (HERE / "solution.py").read_text(), re.MULTILINE)
    if match is None:
        raise SystemExit(f"solution.py has no '{name} = <number>' line")
    return float(match.group(1))


def main(source: str) -> None:
    files = sorted(glob.glob(str(RUNS / source / "dev" / "*.json")))
    if not files:
        raise SystemExit(f"no run records for {source}: run tta evaluate {source} first")
    sys.path.insert(0, str(HERE))
    from solution import friction_basis, gravity_shapes  # noqa: E402 - this folder's own bases

    model = json.loads((HERE / "model.json").read_text())
    scales = np.asarray(model["basis"]["friction_scales_rad_s"], dtype=float)
    kp_scale, kd_scale = scale("KP_SCALE"), scale("KD_SCALE")
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
    model["passes"].append({"what": "gravity shapes + friction vs target qd, joint errors", "source": source,
                            "gains": f"kp x{kp_scale:g}, kd x{kd_scale:g}", "ridge": RIDGE, "in_sample": report})
    (HERE / "model.json").write_text(json.dumps(model, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
