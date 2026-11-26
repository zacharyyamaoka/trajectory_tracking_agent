"""How model.json was made: the exact sum of p5s-pass2's four stacked fits, re-expressed on one basis (no new data).

    uv run --all-extras python solutions/p5s-onefit/merge_stack.py   # reads p5s-pass2's json files, writes model.json

p5s-pass2's feed-forward was: given rigid_body + Fc tanh(qd/vs) + b qd (identified.json, from p5s-bus-enc's board
torque) - gravity shapes . c (gravity.json, p5s-chord's joint errors) - friction basis . w (friction2.json, p5s-grav's
joint errors) - (gravity shapes . g + friction basis . w) (pass2.json, p5s-vlag's joint errors at kp x4 / kd x2), minus
the board-lag term kd 1.3 ms qdd (code, from public board fields). model.json holds the *added* weights on
  friction: tanh(qd / s) for s in SCALES, and qd         gravity: the 13 shapes of identify_pass.gravity_shapes
so that ff = given rigid_body + friction . basis(qd) + gravity . shapes(q) - kd tau_v qdd.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "p5s-pass2"
SCALES = (0.002, 0.005, 0.01, 0.02, 0.035, 0.05, 0.075, 0.1, 0.2)


def main() -> None:
    identified = json.loads((SOURCE / "identified.json").read_text())
    gravity = json.loads((SOURCE / "gravity.json").read_text())
    friction2 = json.loads((SOURCE / "friction2.json").read_text())
    pass2 = json.loads((SOURCE / "pass2.json").read_text())
    joints = {}
    for name, row in identified["joints"].items():
        friction = [0.0] * (len(SCALES) + 1)  # last = the linear qd term
        friction[SCALES.index(row["vs_rad_s"])] += row["coulomb_nm"]
        friction[-1] += row["viscous_nm_s_rad"]
        for scales, weights in ((friction2["scales_rad_s"], friction2["joints"][name]["weights_nm"]),
                                (pass2["scales_rad_s"], pass2["joints"][name]["friction_nm"])):
            for s, w in zip(scales, weights[:-1], strict=True):
                friction[SCALES.index(s)] -= w
            friction[-1] -= weights[-1]
        shapes = [-(a + b) for a, b in zip(gravity["joints"][name]["coef_nm"], pass2["joints"][name]["gravity_nm"], strict=True)]
        joints[name] = {"friction_nm": friction, "gravity_nm": shapes}
    model = {
        "basis": {"friction": [f"tanh(qd/{s:g})" for s in SCALES] + ["qd"], "friction_scales_rad_s": list(SCALES),
                  "gravity": ["1", "c2", "s2", "c23", "s23", "c234", "s234", "c234c5", "s234c5", "c234s5", "s234s5", "s5", "c5"]},
        "sign": "added to the given rigid_body feed-forward (N·m)",
        "passes": [
            {"what": "friction vs measured qd, board torque", "source": identified["source"], "gains": "x1"},
            {"what": "gravity shapes, joint errors", "source": gravity["source"], "gains": "x1"},
            {"what": "friction vs target qd, joint errors", "source": friction2["source"], "gains": "x1"},
            {"what": "gravity shapes + friction vs target qd, joint errors", "source": pass2["source"], "gains": "kp x4, kd x2"},
        ],
        "joints": joints,
    }
    (HERE / "model.json").write_text(json.dumps(model, indent=1) + "\n")
    print("wrote", HERE / "model.json")


if __name__ == "__main__":
    main()
