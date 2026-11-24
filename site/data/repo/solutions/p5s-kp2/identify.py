"""Identify per-joint friction (and, beside it, gravity / inertia scale residuals) from dev run records.

    uv run --all-extras python solutions/p5s-fric/identify.py p5s-bus-enc   # writes solutions/p5s-fric/identified.json

Only the black box's outputs (outputs/runs/<source>/dev/*.json, written by `tta evaluate`): measured joint angles and
velocities (the joint encoders), the board's applied torque (what a moteus reports), and time. Nothing from the plant.

Per joint j, over every sample with |qd_j| >= 0.002 rad/s (below that the joint may be stuck and dry friction is
anywhere inside its band), least squares on

    tau_j - ff_j(q, qd, qdd) = Fc_j tanh(qd_j / vs_j) + b_j qd_j + alpha_j g_j(q) + beta_j (M(q) qdd)_j + d_j

where ff is the given rigid_body model (10 % wrong, robot_controllers' base scenario), g its gravity, M(q) qdd its
inertia torque, qdd the gradient of the measured qd, and vs_j picked from a grid by residual. Only the friction part
(Fc, vs, b) is used by p5s-fric; alpha, beta, d are recorded so the next solution can use them.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
from robot_controllers.bench.arms import arm as registered_arm
from robot_controllers.bench.scenarios import base_scenario

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "outputs" / "runs"
VS_GRID = (0.002, 0.005, 0.01, 0.02, 0.035, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3)
STUCK_RAD_S = 0.002


def load(source: str):
    files = sorted(glob.glob(str(RUNS / source / "dev" / "*.json")))
    if not files:
        raise SystemExit(f"no run records under {RUNS / source / 'dev'}: run tta evaluate {source} first")
    rows = {"q": [], "qd": [], "qdd": [], "tau": []}
    names = None
    for path in files:
        record = json.loads(Path(path).read_text())
        names = record["joint_names"]
        t = np.asarray(record["t"], dtype=float)
        qd = np.asarray(record["qd"], dtype=float)
        rows["q"].append(np.asarray(record["q"], dtype=float))
        rows["qd"].append(qd)
        rows["qdd"].append(np.gradient(qd, t, axis=0))
        rows["tau"].append(np.asarray(record["tau"], dtype=float))
    return names, len(files), {k: np.vstack(v) for k, v in rows.items()}


def main(source: str) -> None:
    names, task_count, data = load(source)
    q, qd, qdd, tau = data["q"], data["qd"], data["qdd"], data["tau"]
    model = registered_arm("ur5e").feedforward("rigid_body", base_scenario("ur5e").model_error)
    zeros = np.zeros_like(q)
    ff = model(q, qd, qdd)
    gravity = model(q, zeros, zeros)
    inertia = model(q, zeros, qdd) - gravity
    residual = tau - ff
    out = {"source": source, "tasks": task_count, "samples": int(len(q)), "stuck_rad_s": STUCK_RAD_S,
           "model": "given rigid_body (base_scenario('ur5e').model_error)", "joints": {}}
    for j, name in enumerate(names):
        use = np.abs(qd[:, j]) >= STUCK_RAD_S
        best = None
        for vs in VS_GRID:
            A = np.c_[np.tanh(qd[use, j] / vs), qd[use, j], gravity[use, j], inertia[use, j], np.ones(use.sum())]
            coef, *_ = np.linalg.lstsq(A, residual[use, j], rcond=None)
            rms = float(np.sqrt(np.mean((residual[use, j] - A @ coef) ** 2)))
            if best is None or rms < best[0]:
                best = (rms, vs, coef)
        rms, vs, coef = best
        out["joints"][name] = {
            "coulomb_nm": float(coef[0]), "vs_rad_s": vs, "viscous_nm_s_rad": float(coef[1]),
            "gravity_scale": float(coef[2]), "inertia_scale": float(coef[3]), "bias_nm": float(coef[4]),
            "residual_rms_nm": rms, "raw_rms_nm": float(np.sqrt(np.mean(residual[use, j] ** 2))), "samples": int(use.sum()),
        }
    (HERE / "identified.json").write_text(json.dumps(out, indent=1) + "\n")
    for name, row in out["joints"].items():
        print(f"{name:20s} Fc {row['coulomb_nm']:+6.3f} vs {row['vs_rad_s']:.3f} b {row['viscous_nm_s_rad']:+6.3f} "
              f"g {row['gravity_scale']:+6.3f} M {row['inertia_scale']:+6.3f} d {row['bias_nm']:+6.3f}  "
              f"rms {row['raw_rms_nm']:.2f} -> {row['residual_rms_nm']:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "p5s-bus-enc")
