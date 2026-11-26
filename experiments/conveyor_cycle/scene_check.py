"""Check that the Scene DB conveyor export matches the frozen planner fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mujoco
import numpy as np

EXPORT_TOLERANCE_M = 1e-6  # MJCF serializes the cell's metre-scale coordinates to six significant digits.


def compare(station_path: Path, scene_path: Path):
    station = json.loads(station_path.read_text())
    model = mujoco.MjModel.from_xml_path(str(scene_path.resolve()))
    data = mujoco.MjData(model)
    mujoco.mj_kinematics(model, data)
    boxes = [geom for geom in range(model.ngeom) if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_BOX
             and model.geom_contype[geom]]
    matched = {}
    for box in station["cell"]["boxes"]:
        half_size = np.asarray(box["size_m"]) / 2.0
        matching = [model.geom(geom).name for geom in boxes
                    if np.allclose(model.geom_size[geom], half_size, atol=EXPORT_TOLERANCE_M, rtol=0.0)
                    and np.allclose(data.geom_xpos[geom], box["centre_m"], atol=EXPORT_TOLERANCE_M, rtol=0.0)
                    and np.allclose(data.geom_xmat[geom].reshape(3, 3), np.eye(3), atol=1e-10, rtol=0.0)]
        if len(matching) != 1:
            raise ValueError(f"expected one collision box for {box['name']}, found {matching}")
        matched[box["name"]] = matching[0]

    pan = [joint for joint in range(model.njnt) if model.joint(joint).name.endswith("shoulder_pan_joint")]
    if len(pan) != 1:
        raise ValueError("expected one UR5e shoulder pan joint")
    base = model.body_parentid[model.jnt_bodyid[pan[0]]]
    expected_mount = np.asarray(station["base_in_cell"])
    np.testing.assert_allclose(data.xpos[base], expected_mount[:3, 3], atol=EXPORT_TOLERANCE_M, rtol=0.0)
    np.testing.assert_allclose(data.xmat[base].reshape(3, 3), expected_mount[:3, :3], atol=1e-10, rtol=0.0)
    return {"matched_collision_boxes": matched, "export_tolerance_m": EXPORT_TOLERANCE_M, "mount_matches_frozen_station": True,
            "scene_joints": model.njnt, "scene_actuators": model.nu}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("station", type=Path)
    parser.add_argument("scene", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.station, args.scene), indent=2))


if __name__ == "__main__":
    main()
