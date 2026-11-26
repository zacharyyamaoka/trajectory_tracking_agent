"""Check the stock six-drive MuJoCo gear model before a tracking transfer replay."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import mujoco
import numpy as np
from sim2real.sim.homing.fullarm_plant import build_rig

ROLES = ("J1", "J2", "C1", "W1", "W2", "W3")


def check_twin():
    rigid, geared = build_rig("B0"), build_rig("B2")
    base, model, wrapper = rigid.model, geared.model, geared.backlash
    if wrapper is None or len(wrapper.joints) != len(ROLES) or model.nq - base.nq != len(ROLES):
        raise ValueError("the full arm needs six separate motor and gap pairs")
    if model.neq != base.neq or model.neq != len(geared.closures) or not geared.closures:
        raise ValueError("the gear model lost the five-bar loop closure")
    rows = {}
    for role in ROLES:
        actuator = geared.bundle.joint(role).name
        joint = wrapper.joints[actuator]
        motor_qpos = geared.qpos_adr(role)
        data = mujoco.MjData(model)
        mujoco.mj_kinematics(model, data)
        start = geared.link_rad(data, role)
        body_positions, body_rotations = data.xpos.copy(), data.xmat.copy()
        delta = joint.spec.half_gap_rad * 0.5
        data.qpos[joint.gap_qpos] += delta
        data.qpos[motor_qpos] -= delta
        mujoco.mj_kinematics(model, data)
        # WHY check a paired perturbation: a joint outside the gear's link frame would corrupt the closed-chain FK.
        np.testing.assert_allclose(geared.link_rad(data, role), start, atol=1e-12, rtol=0)
        np.testing.assert_allclose(data.xpos, body_positions, atol=1e-12, rtol=0)
        np.testing.assert_allclose(data.xmat, body_rotations, atol=1e-12, rtol=0)
        data.qpos[motor_qpos] += delta
        np.testing.assert_allclose(geared.link_rad(data, role) - start, delta, atol=1e-12, rtol=0)
        rows[role] = {"gear_clearance_deg": float(np.rad2deg(joint.spec.total_gap_rad)),
                      "mesh_stiffness_nm_per_rad": joint.spec.mesh_stiffness_nm_per_rad,
                      "link_change_at_fixed_encoder_deg": float(np.rad2deg(delta))}
    friction = model.tendon_frictionloss.tolist()
    if len(friction) != len(ROLES) or min(friction) <= 0:
        raise ValueError("the geared model has no friction on an output tendon")
    return {"schema": "tta.bam-fb-stock-gear-check/1", "mujoco": mujoco.__version__,
            "scope": "stock homing model topology and kinematics. Gear clearances are hidden simulation parameters.",
            "rigid_joint_coordinates": base.nq, "geared_joint_coordinates": model.nq,
            "loop_closures": model.neq, "output_tendon_friction_nm": friction, "drives": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim2real", type=Path, required=True)
    parser.add_argument("--robot-stack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check_twin()
    for name, path in (("sim2real", args.sim2real), ("robot_stack", args.robot_stack)):
        result[f"{name}_commit"] = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
