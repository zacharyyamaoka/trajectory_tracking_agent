"""Lane E's tests of the frozen dataset and the deployment: sha256s, joint order, the mount, the limits."""

from __future__ import annotations

import json
import math
import shutil

import numpy as np
import pytest

from trajectory_tracking_agent.ruler import dataset
from trajectory_tracking_agent.ruler.deployment import deployment


def test_verify_is_clean():
    assert dataset.verify() == []


def test_split_counts_and_order():
    dev, holdout = dataset.tasks("dev"), dataset.tasks("holdout")
    assert len(dev) == 42 and len(holdout) == 12
    assert [task.id for task in dev] == [f"workspace-dev-{k:03d}" for k in range(42)]
    assert sum(task.duration_s for task in dev) == pytest.approx(99.36, abs=0.01)  # the manifest's duration_rung_1_s
    with pytest.raises(ValueError):
        dataset.tasks("test")


def test_every_tape_is_in_ur5e_joint_order_from_rest():
    from robot_controllers.bench.ur5e import UR5E_JOINTS

    for split in dataset.SPLITS:
        for task in dataset.tasks(split):
            trajectory = task.trajectory
            assert tuple(trajectory.joint_names) == UR5E_JOINTS
            assert trajectory.t[0] == 0.0 and np.allclose(np.diff(trajectory.t), 0.01)
            assert np.allclose(trajectory.velocities[[0, -1]], 0.0)  # starts and ends at rest
            assert trajectory.effort is None  # the tape gives no feed-forward; a solution brings its own


@pytest.fixture
def dataset_copy(tmp_path, monkeypatch):
    copy = tmp_path / "v2"
    shutil.copytree(dataset.DATASET_DIR, copy)
    monkeypatch.setattr(dataset, "DATASET_DIR", copy)
    monkeypatch.setattr(dataset, "TAPES_DIR", copy / "tapes")
    monkeypatch.setattr(dataset, "TAPES_MANIFEST", copy / "tapes_manifest.json")
    dataset._rows.cache_clear()
    dataset._trajectory.cache_clear()
    yield copy
    dataset._rows.cache_clear()
    dataset._trajectory.cache_clear()


def test_verify_catches_a_changed_tape(dataset_copy):
    tape = dataset_copy / "tapes" / "workspace-dev-007.npz"
    data = bytearray(tape.read_bytes())
    data[-100] ^= 0x01
    tape.write_bytes(bytes(data))
    problems = dataset.verify()
    assert any("tapes/workspace-dev-007.npz: sha256" in problem for problem in problems)


def test_verify_catches_a_new_file_and_a_missing_one(dataset_copy):
    (dataset_copy / "tapes" / "extra.npz").write_bytes(b"x")
    (dataset_copy / "rejections.jsonl").unlink()
    problems = dataset.verify()
    assert any("extra.npz: not in tapes_manifest.json" in problem for problem in problems)
    assert any("rejections.jsonl: missing" in problem for problem in problems)


def test_verify_catches_a_manifest_rewritten_to_match_a_new_tape(dataset_copy):
    # Forging tapes_manifest.json is not enough: the tape must also be the one arm_motion_bench's manifest lists.
    tape = dataset_copy / "tapes" / "workspace-dev-003.npz"
    tape.write_bytes(tape.read_bytes() + b"\0")
    record = json.loads((dataset_copy / "tapes_manifest.json").read_text())
    record["files"]["tapes/workspace-dev-003.npz"] = dataset.sha256(tape)
    (dataset_copy / "tapes_manifest.json").write_text(json.dumps(record))
    problems = dataset.verify()
    assert any("not the one arm_motion_bench's manifest lists" in problem for problem in problems)


def test_deployment_is_objectives_section_2():
    from robot_controllers.bench.ur5e import UR5E_TRUTH, ur5e_board_config

    dep = deployment("ur5e_alone")
    assert dep.host_rate_hz == 50.0
    assert dep.bus.source.startswith("datasheet") and len(dep.bus.per_joint(6)) == 6
    assert dep.board == ur5e_board_config() and dep.torque_cap_nm == (150.0,) * 3 + (28.0,) * 3
    assert dep.torque_cap_nm == UR5E_TRUTH.torque_cap_nm
    assert dep.floor_z_m == 0.0 and dep.gravity_m_s2 == (0.0, 0.0, -9.81)
    assert dep.velocity_max_rad_s == (math.pi,) * 6  # 180 deg/s, the UR5e datasheet
    assert dep.position_min_rad[2] == -3.1415 and dep.position_max_rad[2] == 3.1415  # the elbow
    json.dumps(dep.record())
    with pytest.raises(ValueError):
        deployment("bam_fb")


def test_the_mount_matches_the_datasets_floor_mount_up_to_a_yaw():
    # The dataset's stored TCP (flange + 0.144 m) is Rz(pi) of this model's flange + 0.144 m along the flange normal:
    # the same base on the same floor, turned 180 deg about the vertical axis (no height or distance changes).
    import mujoco
    from robot_controllers.bench.ur5e import load_model

    model = load_model(frictionloss=False)
    data = mujoco.MjData(model)
    site = model.site("tool").id
    yaw = np.diag([-1.0, -1.0, 1.0])
    for task_id in ("workspace-dev-000", "workspace-dev-019", "workspace-holdout-005"):
        stored = np.load(dataset.TAPES_DIR / f"{task_id}.npz")["tcp_pos"]
        positions = dataset.task(task_id).trajectory.positions
        for row in range(0, len(positions), 17):
            data.qpos[:] = positions[row]
            mujoco.mj_kinematics(model, data)
            tcp = data.site_xpos[site] + 0.144 * data.site_xmat[site].reshape(3, 3)[:, 2]
            np.testing.assert_allclose(yaw @ tcp, stored[row], atol=1e-12)


def test_link_points_put_the_base_on_the_floor_and_the_tool_last():
    dep = deployment()
    points = dep.link_points(np.zeros((2, 6)))
    assert points.shape == (2, 8, 3)  # base, six links, the tool
    np.testing.assert_allclose(points[:, 0], 0.0)
    np.testing.assert_allclose(points[:, -1], dep.tool_position(np.zeros((2, 6))))
    assert np.isnan(dep.link_points(np.full((1, 6), np.nan))).all()  # a NaN pose fails the floor gate
