"""The ruler's arm as a URDF, for the Datasets page's Rerun recordings (robot_msgs' stock JointTrajectory viewer draws
a JointTrajectory as the URDF it is given): site/datasets/<robot>/robot/.

    import ruler_urdf
    ruler_urdf.write(out_dir, "ur5e_alone")          # <deployment>.urdf + meshes/ + LICENSE.ur_description
    ruler_urdf.tool_poses("ur5e_alone", q)           # the ruler's tool point (and the tool site's axes) in the URDF root
    ruler_urdf.cell_from_ruler("ur5e_alone")         # 4 x 4: the ruler's world -> the URDF's root link `cell`

WHY the ruler's kinematics, not ur_description's (lane COV2, 2026-11-25, measured): Universal Robots' ur_description
URDF (arm_motion_bench robots/ur5e_description, the file its own workbench draws) has the UR5e datasheet's DH lengths
(d1 0.1625, a3 0.3922, d4 0.1333, d5 0.0997, d6 0.0996 m); the ruler's plant is MuJoCo Menagerie's UR5e (0.163, 0.392,
0.134, 0.100, 0.100). Over all 12 870 samples of the 54 tapes its flange sits up to 1.446 mm from the ruler's tool point
(0.690 mm at best per tape), over the 1 mm a recording of the ruler's trajectory may be off. So the chain here is read
from the ruler's own model (robot_controllers.bench.ur5e.load_model: each body's offset and rotation, each joint's axis
and range, the tool site), and only ur_description's collision meshes dress it, each placed on its Menagerie body where
ur_description puts it at the zero pose. tests/test_coverage_robot.py holds the FK to the ruler's tool point (and shows
the stock URDF failing the same gate).

The root link is `cell`, the deployment's frame (station.json's `base_in_cell`: Menagerie's base body on the floor), the
pattern of arm_motion_bench's mounted_urdf(base_in_cell); the ruler's world is Menagerie's (the base body at Rz(pi)), so
a ruler position p maps to cell_from_ruler @ p. Mesh paths are relative (meshes/<file>), so nothing names this machine.
Runs in this repo's venv (robot_controllers, mujoco); the meshes and their licence are read from an arm_motion_bench
checkout beside this one (or TTA_ARM_MOTION_BENCH).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
ARM_MOTION_BENCH = Path(os.environ.get("TTA_ARM_MOTION_BENCH", REPO.parent / "arm_motion_bench"))
UR_DESCRIPTION = ARM_MOTION_BENCH / "src" / "arm_motion_bench" / "robots" / "ur5e_description"
UR_URDF = UR_DESCRIPTION / "ur5e_collision.urdf"
LICENSE = "LICENSE.ur_description"
ROOT = "cell"
TOOL_LINK = "tool"
# Menagerie's body -> ur_description's link that carries its mesh (the rest share a name)
MESH_LINK = {"base": "base_link_inertia"}
UR_ROOT = "base_link_ur"  # ur_description's root: Menagerie's base body frame (x out along the arm at the zero pose)


def _dataset_dir(deployment: str) -> Path:
    """The ruler's dataset of this deployment (OBJECTIVES §3): its station.json holds the mount."""
    folders = sorted(p.parent for p in (REPO / "datasets" / deployment).glob("*/v*/station.json"))
    if len(folders) != 1:
        raise ValueError(f"datasets/{deployment}: expected one dataset with a station.json, found {len(folders)}")
    return folders[0]


def base_in_cell(deployment: str) -> np.ndarray:
    mount = np.asarray(json.loads((_dataset_dir(deployment) / "station.json").read_text())["base_in_cell"], float)
    if mount.shape != (4, 4):
        raise ValueError(f"station.json base_in_cell must be 4 x 4, got {mount.shape}")
    return mount


@functools.lru_cache(maxsize=1)
def _model():
    from robot_controllers.bench.ur5e import load_model

    return load_model(frictionloss=False)


def _quat_matrix(quat) -> np.ndarray:
    w, x, y, z = (float(v) for v in quat)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def _pose(rotation, translation) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = rotation
    out[:3, 3] = translation
    return out


def _rpy(rotation: np.ndarray) -> tuple[float, float, float]:
    """URDF rpy (R = Rz(yaw) Ry(pitch) Rx(roll)) of a rotation matrix."""
    pitch = float(np.arcsin(-np.clip(rotation[2, 0], -1.0, 1.0)))
    if abs(rotation[2, 0]) < 1 - 1e-12:
        roll = float(np.arctan2(rotation[2, 1], rotation[2, 2]))
        yaw = float(np.arctan2(rotation[1, 0], rotation[0, 0]))
    else:  # gimbal lock: put the whole turn in yaw
        roll, yaw = 0.0, float(np.arctan2(-rotation[0, 1], rotation[1, 1]))
    return roll, pitch, yaw


def _rpy_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = np.cos(roll), np.sin(roll), np.cos(pitch), np.sin(pitch), np.cos(yaw), np.sin(yaw)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _number(value: float) -> str:
    value = 0.0 if abs(value) < 1e-15 else float(value)
    return repr(value)


def _origin(parent: ET.Element, pose: np.ndarray) -> None:
    ET.SubElement(parent, "origin", xyz=" ".join(_number(v) for v in pose[:3, 3]),
                  rpy=" ".join(_number(v) for v in _rpy(pose[:3, :3])))


def _ur_links_at_zero() -> tuple[dict[str, np.ndarray], dict[str, list[tuple[np.ndarray, str]]]]:
    """ur_description at the zero pose: every link's pose in its root, and each link's collision meshes (origin, file)."""
    robot = ET.parse(UR_URDF).getroot()
    poses = {UR_ROOT: np.eye(4)}
    joints = list(robot.iter("joint"))
    while joints:
        progressed = False
        for joint in list(joints):
            parent, child = joint.find("parent").get("link"), joint.find("child").get("link")
            if parent not in poses:
                continue
            origin = joint.find("origin")
            xyz = [float(v) for v in (origin.get("xyz", "0 0 0") if origin is not None else "0 0 0").split()]
            rpy = [float(v) for v in (origin.get("rpy", "0 0 0") if origin is not None else "0 0 0").split()]
            poses[child] = poses[parent] @ _pose(_rpy_matrix(*rpy), xyz)
            joints.remove(joint)
            progressed = True
        if not progressed:
            raise ValueError(f"{UR_URDF.name}: joints not connected to {UR_ROOT}")
    meshes: dict[str, list[tuple[np.ndarray, str]]] = {}
    for link in robot.iter("link"):
        for collision in link.iter("collision"):
            origin = collision.find("origin")
            xyz = [float(v) for v in (origin.get("xyz", "0 0 0") if origin is not None else "0 0 0").split()]
            rpy = [float(v) for v in (origin.get("rpy", "0 0 0") if origin is not None else "0 0 0").split()]
            mesh = collision.find("geometry/mesh")
            meshes.setdefault(link.get("name"), []).append((_pose(_rpy_matrix(*rpy), xyz), mesh.get("filename")))
    return poses, meshes


def _menagerie_at_zero() -> dict[str, np.ndarray]:
    """The ruler model's bodies at the zero pose, in its base body's frame (= ur_description's root, see UR_ROOT)."""
    import mujoco

    model = _model()
    data = mujoco.MjData(model)
    mujoco.mj_kinematics(model, data)
    base = model.body("base").id
    world_base = _pose(data.xmat[base].reshape(3, 3), data.xpos[base])
    return {model.body(b).name: np.linalg.inv(world_base) @ _pose(data.xmat[b].reshape(3, 3), data.xpos[b])
            for b in range(1, model.nbody)}


def cell_from_ruler(deployment: str) -> np.ndarray:
    """4 x 4: a point in the ruler's world (robot_controllers' bare UR5e, Menagerie's base body at Rz(pi)) -> the
    deployment's cell frame, the URDF's root. Read from the two documented frames, never fitted: base_in_cell after
    the inverse of the base body's pose in the ruler's world."""
    import mujoco

    model = _model()
    data = mujoco.MjData(model)
    mujoco.mj_kinematics(model, data)
    base = model.body("base").id
    world_base = _pose(data.xmat[base].reshape(3, 3), data.xpos[base])
    return base_in_cell(deployment) @ np.linalg.inv(world_base)


def tool_poses(deployment: str, q) -> tuple[np.ndarray, np.ndarray]:
    """The ruler's tool point for joint angles q (N, 6), in the URDF's root (`cell`): positions (N, 3) from the ruler's
    own deployment.tool_position (OBJECTIVES §2, the number the objective is computed from), and the tool site's axes
    (N, 3, 3) from the same model, for the recording's TCP orientation tab."""
    import mujoco

    from robot_controllers.bench.ur5e import TOOL_SITE
    from trajectory_tracking_agent.ruler.deployment import deployment as ruler_deployment

    rows = np.atleast_2d(np.asarray(q, dtype=float))
    transform = cell_from_ruler(deployment)
    positions = np.asarray(ruler_deployment(deployment).tool_position(rows), float) @ transform[:3, :3].T + transform[:3, 3]
    model = _model()
    data = mujoco.MjData(model)
    site = model.site(TOOL_SITE).id
    rotations = np.empty((rows.shape[0], 3, 3))
    for index, row in enumerate(rows):
        data.qpos[:] = row
        mujoco.mj_kinematics(model, data)
        rotations[index] = transform[:3, :3] @ data.site_xmat[site].reshape(3, 3)
    return positions, rotations


def urdf_text(deployment: str) -> str:
    """The deployment's URDF: robot_controllers' UR5e chain under `cell`, ur_description's collision meshes on it."""
    from robot_controllers.bench.ur5e import TOOL_SITE

    model = _model()
    station = json.loads((_dataset_dir(deployment) / "station.json").read_text())
    limits = {joint["name"]: joint for joint in station["joints"]}
    ur_poses, ur_meshes = _ur_links_at_zero()
    bodies = _menagerie_at_zero()

    robot = ET.Element("robot", name="ur5e")
    ET.SubElement(robot, "link", name=ROOT)
    for b in range(1, model.nbody):
        name = model.body(b).name
        link = ET.SubElement(robot, "link", name=name)
        ur_link = MESH_LINK.get(name, name)
        if ur_link not in ur_poses:
            raise ValueError(f"{UR_URDF.name} has no link {ur_link!r} for the ruler's body {name!r}")
        # the mesh where ur_description puts it at the zero pose, in this body's frame
        body_from_ur = np.linalg.inv(bodies[name]) @ ur_poses[ur_link]
        for index, (origin, filename) in enumerate(ur_meshes.get(ur_link, [])):
            collision = ET.SubElement(link, "collision", name=f"{name}_collision_{index}")
            _origin(collision, body_from_ur @ origin)
            ET.SubElement(ET.SubElement(collision, "geometry"), "mesh", filename=f"meshes/{Path(filename).name}")
        parent = model.body_parentid[b]
        if parent == 0:  # the base: mounted in the cell as the deployment's station mounts it
            joint = ET.SubElement(robot, "joint", name=f"{ROOT}_to_{name}", type="fixed")
            ET.SubElement(joint, "parent", link=ROOT)
            ET.SubElement(joint, "child", link=name)
            _origin(joint, base_in_cell(deployment))
            continue
        offset = _pose(_quat_matrix(model.body_quat[b]), model.body_pos[b])
        if model.body_jntnum[b] != 1:
            raise ValueError(f"body {name!r}: expected one joint, found {model.body_jntnum[b]}")
        j = model.body_jntadr[b]
        if model.jnt_type[j] != 3 or np.any(model.jnt_pos[j] != 0):  # 3: a hinge at the body's origin
            raise ValueError(f"joint {model.joint(j).name!r}: only a hinge at its body's origin is written")
        joint_name = model.joint(j).name
        joint = ET.SubElement(robot, "joint", name=joint_name, type="revolute")
        ET.SubElement(joint, "parent", link=model.body(parent).name)
        ET.SubElement(joint, "child", link=name)
        _origin(joint, offset)
        ET.SubElement(joint, "axis", xyz=" ".join(_number(v) for v in model.jnt_axis[j]))
        low, high = (float(v) for v in model.jnt_range[j])
        given = limits[joint_name]
        ET.SubElement(joint, "limit", lower=_number(low), upper=_number(high),
                      effort=_number(float(given["torque_cap_nm"])), velocity=_number(float(given["velocity_max_rad_s"])))
    site = model.site(TOOL_SITE).id
    ET.SubElement(robot, "link", name=TOOL_LINK)
    joint = ET.SubElement(robot, "joint", name=f"{model.body(model.site_bodyid[site]).name}_to_{TOOL_LINK}", type="fixed")
    ET.SubElement(joint, "parent", link=model.body(model.site_bodyid[site]).name)
    ET.SubElement(joint, "child", link=TOOL_LINK)
    _origin(joint, _pose(_quat_matrix(model.site_quat[site]), model.site_pos[site]))
    ET.indent(robot, space="  ")
    header = (
        f"\n  GENERATED by tools/build_coverage.py (tools/ruler_urdf.py; never edit, rebuild) for deployment {deployment}.\n"
        "  The chain is the ruler's UR5e: robot_controllers.bench.ur5e.load_model (MuJoCo Menagerie's UR5e), each body's\n"
        f"  offset, joint axis and range, the tool site `{TOOL_SITE}` as the link `{TOOL_LINK}`; limits' effort and velocity\n"
        "  are the frozen dataset's station.json. Root `cell`: the deployment's frame (station.json base_in_cell).\n"
        "  The meshes are Universal Robots' ur_description UR5e collision meshes (BSD-3-Clause, LICENSE.ur_description\n"
        "  beside this file), each placed on its body where ur_description puts it at the zero pose.\n"
    )
    return '<?xml version="1.0"?>\n<!--' + header + "-->\n" + ET.tostring(robot, encoding="unicode") + "\n"


def write(out: Path, deployment: str) -> dict:
    """<out>/<deployment>.urdf, <out>/meshes/*.stl and <out>/LICENSE.ur_description; returns the files and their sha256."""
    if not UR_URDF.exists():
        raise FileNotFoundError(f"no arm_motion_bench ur5e_description at {UR_DESCRIPTION} (set TTA_ARM_MOTION_BENCH)")
    out = Path(out)
    (out / "meshes").mkdir(parents=True, exist_ok=True)
    text = urdf_text(deployment)
    urdf = out / f"{deployment}.urdf"
    urdf.write_text(text)
    wanted = {Path(mesh.get("filename")).name for mesh in ET.fromstring(text.split("-->", 1)[1]).iter("mesh")}
    for stale in (out / "meshes").iterdir():
        if stale.name not in wanted:
            stale.unlink()
    for name in sorted(wanted):
        shutil.copyfile(UR_DESCRIPTION / "meshes" / name, out / "meshes" / name)
    shutil.copyfile(UR_DESCRIPTION / LICENSE, out / LICENSE)
    files = [urdf, out / LICENSE, *sorted((out / "meshes").iterdir())]
    return {path.relative_to(out).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
