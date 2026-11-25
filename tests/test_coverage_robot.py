"""The arm and the recordings on the Datasets page (site/datasets/<robot>/: robot/, rrd-*.rrd, rrd_inputs.json), written
by tools/build_coverage.py with tools/ruler_urdf.py.

The oracle is the ruler itself: the deployment's tool_position (OBJECTIVES §2, the number the objective is computed
from), never the build's code. The committed URDF is read with its own small forward kinematics here (the XML's joint
origins and axes, nothing shared with the build), and over every joint sample of every tape its tool point must sit
within 1 mm of the ruler's, mapped into the URDF's root from the two documented frames (station.json's base_in_cell and
Menagerie's base body in the ruler's world). The tool path the recordings draw (the build's tool_poses) is held to the
same arm. Universal Robots' own URDF fails the same gate (measured 1.446 mm), which is why the chain is the ruler's.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
PAGE = SITE / "datasets" / "ur5e"
ROBOT = PAGE / "robot"
URDF = ROBOT / "ur5e_alone.urdf"
DATASET = REPO / "datasets" / "ur5e_alone" / "workspace" / "v2"
BENCH = Path(os.environ.get("TTA_ARM_MOTION_BENCH", REPO.parent / "arm_motion_bench"))
GATE_M = 0.001  # a recording of the ruler's trajectory may put the tool at most 1 mm from the ruler's tool point

pytestmark = pytest.mark.skipif(not URDF.exists(), reason="site/datasets/ur5e/robot not built")


def _rpy(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = np.cos(roll), np.sin(roll), np.cos(pitch), np.sin(pitch), np.cos(yaw), np.sin(yaw)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _about(axis, angles: np.ndarray) -> np.ndarray:
    """(N, 3, 3): Rodrigues' rotation about `axis` by each angle."""
    k = np.asarray(axis, float) / np.linalg.norm(axis)
    cross = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    a = np.asarray(angles, float)[:, None, None]
    return np.eye(3) + np.sin(a) * cross + (1 - np.cos(a)) * (cross @ cross)


def urdf_fk(path: Path, joint_names, q: np.ndarray) -> tuple[str, dict[str, np.ndarray]]:
    """Every link's pose (N, 4, 4) in the URDF's root for joint angles q (N, J): this test's own FK of the XML."""
    robot = ET.parse(path).getroot()
    joints = list(robot.iter("joint"))
    children = {j.find("child").get("link") for j in joints}
    (root,) = [link.get("name") for link in robot.iter("link") if link.get("name") not in children]
    values = dict(zip(joint_names, np.asarray(q, float).T, strict=True))
    n = len(q)
    poses = {root: np.broadcast_to(np.eye(4), (n, 4, 4))}
    while joints:
        for joint in [j for j in joints if j.find("parent").get("link") in poses]:
            origin = joint.find("origin")
            fixed = np.eye(4)
            fixed[:3, :3] = _rpy(*(float(v) for v in origin.get("rpy", "0 0 0").split()))
            fixed[:3, 3] = [float(v) for v in origin.get("xyz", "0 0 0").split()]
            motion = np.broadcast_to(np.eye(4), (n, 4, 4)).copy()
            if joint.get("type") in ("revolute", "continuous"):
                motion[:, :3, :3] = _about([float(v) for v in joint.find("axis").get("xyz").split()], values[joint.get("name")])
            poses[joint.find("child").get("link")] = poses[joint.find("parent").get("link")] @ fixed @ motion
            joints.remove(joint)
    return root, poses


def _tapes():
    from robot_msgs import load_npz

    for tape in sorted((DATASET / "tapes").glob("*.npz")):
        yield tape.stem, load_npz(tape)


def _cell_from_ruler() -> np.ndarray:
    """The ruler's world -> the cell (the URDF's root), from the two frames as documented: the ruler's world holds
    Menagerie's base body at its pose there; the cell holds it at station.json's base_in_cell."""
    import mujoco

    from robot_controllers.bench.ur5e import load_model

    model = load_model(frictionloss=False)
    data = mujoco.MjData(model)
    mujoco.mj_kinematics(model, data)
    base = model.body("base").id
    world_base = np.eye(4)
    world_base[:3, :3] = data.xmat[base].reshape(3, 3)
    world_base[:3, 3] = data.xpos[base]
    base_in_cell = np.asarray(json.loads((DATASET / "station.json").read_text())["base_in_cell"], float)
    return base_in_cell @ np.linalg.inv(world_base)


def _ruler_tool_in_cell(q: np.ndarray, transform: np.ndarray) -> np.ndarray:
    from trajectory_tracking_agent.ruler.deployment import deployment

    return np.asarray(deployment("ur5e_alone").tool_position(q), float) @ transform[:3, :3].T + transform[:3, 3]


def _ruler_urdf():
    sys.path.insert(0, str(REPO / "tools"))
    spec = importlib.util.spec_from_file_location("ruler_urdf", REPO / "tools" / "ruler_urdf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_urdf_arm_puts_the_rulers_tool_point_where_the_ruler_does():
    """Every joint sample of all 54 tapes: the committed URDF's `tool` link within 1 mm of the ruler's tool point (the
    measured maximum is printed; 2.3e-08 m when written, 2026-11-25), and its `tool` link is the flange site 0.1 m out."""
    transform = _cell_from_ruler()
    worst, samples, tapes = 0.0, 0, 0
    for name, trajectory in _tapes():
        q = np.asarray(trajectory.positions, float)
        root, poses = urdf_fk(URDF, trajectory.joint_names, q)
        error = np.linalg.norm(poses["tool"][:, :3, 3] - _ruler_tool_in_cell(q, transform), axis=1)
        worst, samples, tapes = max(worst, float(error.max())), samples + len(q), tapes + 1
    assert root == "cell"
    assert tapes == 54 and samples > 10_000, (tapes, samples)
    print(f"URDF tool vs the ruler's tool point over {tapes} tapes, {samples} samples: max {worst * 1e3:.6f} mm")
    assert worst < GATE_M, f"the URDF's tool is {worst * 1e3:.3f} mm from the ruler's (gate 1 mm)"
    offset = ET.parse(URDF).getroot().find("joint[@name='wrist_3_link_to_tool']/origin").get("xyz")
    assert np.allclose([float(v) for v in offset.split()], [0.0, 0.1, 0.0]), offset  # OBJECTIVES §2: 0.1 m along wrist_3


def test_the_recordings_tool_path_is_the_ruler_tool_point_on_that_arm():
    """The tool PoseTrajectory each .rrd draws (the build's tool_poses) is the ruler's tool point in the URDF's root:
    within 1 mm of the URDF's tool link, and its orientation is the tool link's (the TCP tab's angles)."""
    tool_poses = _ruler_urdf().tool_poses
    worst, worst_turn = 0.0, 0.0
    for name, trajectory in _tapes():
        q = np.asarray(trajectory.positions, float)
        positions, rotations = tool_poses("ur5e_alone", q)
        _, poses = urdf_fk(URDF, trajectory.joint_names, q)
        worst = max(worst, float(np.linalg.norm(poses["tool"][:, :3, 3] - positions, axis=1).max()))
        relative = np.einsum("nji,njk->nik", poses["tool"][:, :3, :3], rotations)
        worst_turn = max(worst_turn, float(np.degrees(np.arccos(np.clip((np.trace(relative, axis1=1, axis2=2) - 1) / 2, -1, 1))).max()))
    print(f"tool path vs the URDF's tool: max {worst * 1e3:.6f} mm, {worst_turn:.6f} deg")
    assert worst < GATE_M and worst_turn < 0.01, (worst, worst_turn)


@pytest.mark.skipif(not (BENCH / "src" / "arm_motion_bench" / "robots" / "ur5e_description").is_dir(),
                    reason=f"no arm_motion_bench checkout at {BENCH}")
def test_universal_robots_own_urdf_misses_the_same_gate():
    """WHY the chain is the ruler's: ur_description's UR5e (the datasheet's DH lengths) puts its flange up to 1.4 mm from
    the ruler's tool point (MuJoCo Menagerie's lengths). If this goes red, the stock URDF has become the ruler's arm."""
    stock = BENCH / "src" / "arm_motion_bench" / "robots" / "ur5e_description" / "ur5e_collision.urdf"
    transform = _cell_from_ruler()
    worst = 0.0
    for name, trajectory in _tapes():
        q = np.asarray(trajectory.positions, float)
        _, poses = urdf_fk(stock, trajectory.joint_names, q)  # its root base_link_ur is the cell (identity mount)
        worst = max(worst, float(np.linalg.norm(poses["wrist_3_link"][:, :3, 3] - _ruler_tool_in_cell(q, transform), axis=1).max()))
    print(f"ur_description's flange vs the ruler's tool point: max {worst * 1e3:.3f} mm")
    assert worst > GATE_M, worst


def test_the_arm_ships_its_meshes_and_their_bsd_licence():
    """Relative mesh paths that exist (nothing names this machine), ur_description's licence beside them, and the page
    credits it with a link."""
    meshes = [mesh.get("filename") for mesh in ET.parse(URDF).getroot().iter("mesh")]
    assert len(meshes) == 7
    for filename in meshes:
        assert filename.startswith("meshes/") and (ROBOT / filename).is_file(), filename
    licence = (ROBOT / "LICENSE.ur_description").read_text()
    assert "Redistribution and use in source and binary forms" in licence and "Neither the name" in licence
    page = (PAGE / "index.html").read_text()
    assert 'href="robot/LICENSE.ur_description"' in page and "ur_description" in page and "BSD-3-Clause" in page
    assert '<footer class="page-foot">' in page


def test_every_trajectory_opens_its_recording_from_pages_in_the_rerun_version_that_wrote_it():
    """One .rrd per trajectory row, at the row's rrd_url on GitHub Pages, listed in rrd_inputs.json; the record's web
    viewer is app.rerun.io at the SDK version rrd_inputs.json says wrote the files; each file under GitHub's 100 MiB."""
    rows = json.loads((PAGE / "trajectories.json").read_text())["rows"]
    record = json.loads((PAGE / "rrd_inputs.json").read_text())
    shipped = sorted(p.name for p in PAGE.glob("*.rrd"))
    assert len(rows) == 54 and sorted(row["rrd"] for row in rows) == shipped == sorted(record["files"])
    for row in rows:
        assert row["rrd_url"] == f"https://zacharyyamaoka.github.io/trajectory_tracking_agent/datasets/ur5e/{row['rrd']}"
    assert re.fullmatch(r"\d+\.\d+\.\d+", record["rerun_sdk"])
    base = (PAGE / "coverage.base").read_text()
    assert f"href: 'https://app.rerun.io/version/{record['rerun_sdk']}/index.html?url={{rrd_url}}'" in base
    assert "href: '{rrd|path}'" in base and "/__rerun/open" not in base  # a static host: no native-viewer POST
    assert record["ghosts"] is False
    assert max(p.stat().st_size for p in PAGE.glob("*.rrd")) <= 100 * 1024 * 1024


DATA_UI_CSS = SITE / "vendor" / "data-ui" / "data-ui.css"
HOST_PAGES = (SITE / "deployments" / "index.html", PAGE / "index.html", SITE / "models-datasets" / "index.html")


def test_no_host_page_defines_a_token_name_data_ui_reads_from_its_host():
    """data-ui falls back to shadcn's token names (`var(--data-subtle, var(--muted, …))`: --muted is a soft background
    there, --accent a hover fill). A host page that defines one for its own text colour paints data-ui's pills and tabs
    with it (the dark "Showing" pills, lane COV2): the names are read from the vendored data-ui.css itself."""
    css = DATA_UI_CSS.read_text()
    host_names = set(re.findall(r"var\(--data-[a-z0-9-]+,\s*var\((--[a-z0-9-]+)", css))
    assert {"--muted", "--accent", "--border", "--background"} <= host_names, sorted(host_names)
    for page in HOST_PAGES:
        styles = "".join(re.findall(r"<style>(.*?)</style>", page.read_text(), re.S))
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", styles))
        assert not defined & host_names, f"{page.relative_to(REPO)} defines {sorted(defined & host_names)}"
