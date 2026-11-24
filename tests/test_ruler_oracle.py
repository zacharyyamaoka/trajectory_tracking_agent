"""Independent oracle for the ruler's objective (lane E): tool tracking RMS recomputed without `ruler/metrics.py`.

For one solution (p4s) on three dev tasks (an ISO 9283 path, a joint A->B move, a straight tool line), the episode is run
again straight through robot_controllers (its own Rung, HostTiming, Ur5ePlant and `run_episode`, none of the ruler's
`evaluate` wiring), the measured joints are picked off the log by time (searchsorted, not the ruler's rint indices), both
tool poses come from a MuJoCo model loaded here from robot_controllers' vendored XML (site position and orientation, not
`tool_position`), the error is robot_msgs.compare's PoseTrajectory error, its RMS robot_msgs' `error_stats`, and "moving"
is re-derived here with forward differences. The ruler's `run_task` objective must agree to 1 % (and 0.01 mm).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

ORACLE_SOLUTION = "p4s"
ORACLE_TASKS = ("workspace-dev-000", "workspace-dev-010", "workspace-dev-030")


def _oracle_tool_poses(q: np.ndarray) -> np.ndarray:
    """(N, 4, 4) of the flange site `tool` from a MuJoCo model loaded straight from the vendored XML."""
    import mujoco
    from robot_controllers.bench.ur5e import MODEL_PATH

    model = mujoco.MjModel.from_xml_path(str(MODEL_PATH))
    data = mujoco.MjData(model)
    site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "tool")
    out = np.tile(np.eye(4), (len(q), 1, 1))
    for row, angles in enumerate(q):
        data.qpos[:] = angles
        mujoco.mj_forward(model, data)
        out[row, :3, :3] = data.site_xmat[site].reshape(3, 3)
        out[row, :3, 3] = data.site_xpos[site]
    return out


def _oracle_episode(task, deployment):
    from robot_controllers.bench.loop import run_episode
    from robot_controllers.bench.types import HostTiming, Rung, Scene
    from robot_controllers.bench.ur5e import Ur5ePlant
    from robot_controllers.calibration import datasheet_bus
    from robot_controllers.registry import JOINT_TRAJECTORY

    from trajectory_tracking_agent.population import load_build

    build = load_build(ORACLE_SOLUTION)
    trajectory = task.trajectory

    class Spec:
        name = "oracle"

        def build(self, message, **_):
            return build(message, deployment)

    class Script:
        duration_s = float(trajectory.t[-1])

        def __call__(self, start_q):
            return [(0.0, trajectory)]

    rung = Rung(
        id=f"oracle/{task.id}", title="oracle", box=JOINT_TRAJECTORY, family="free_space", description="oracle",
        duration_s=float(trajectory.t[-1]) + 0.02, inputs=Script(),
        scene=Scene(start_q=tuple(float(v) for v in trajectory.positions[0])),
        timing=HostTiming.from_bus(datasheet_bus(6), 50.0, include_compute=False), plant="ur5e",
    )  # fmt: skip
    return run_episode(Spec(), rung, seed=0, plant_factory=Ur5ePlant)


def _oracle_rms_mm(task, log) -> tuple[float, int]:
    from robot_msgs.compare import compare, error_stats
    from robot_msgs.trajectory import PoseTrajectory

    trajectory = task.trajectory
    t = np.asarray(trajectory.t, dtype=float)
    rows = np.searchsorted(log.t, t - 1e-7)  # the first physics sample at or after each target instant
    assert np.max(np.abs(log.t[rows] - t)) < 1e-6
    q = np.asarray(log.q)[rows]
    target = PoseTrajectory.from_matrices(t, _oracle_tool_poses(np.asarray(trajectory.positions)))
    measured = PoseTrajectory.from_matrices(t, _oracle_tool_poses(q))
    error = compare(target, measured).error
    distance = np.linalg.norm(np.asarray(error.positions), axis=1)
    # moving, re-derived: forward-difference tool speed (last one repeated) or any joint speed, OBJECTIVES' thresholds
    speed = np.linalg.norm(np.diff(target.positions, axis=0), axis=1) / np.diff(t)
    speed = np.append(speed, speed[-1])
    joints = np.max(np.abs(np.asarray(trajectory.velocities)), axis=1)
    moving = (speed > 1e-3) | (joints > math.radians(0.06))
    return 1e3 * float(error_stats(distance[moving]).rms), int(moving.sum())


@pytest.mark.parametrize("task_id", ORACLE_TASKS)
def test_objective_agrees_with_an_independent_oracle(task_id):
    from trajectory_tracking_agent.evaluate import run_task
    from trajectory_tracking_agent.ruler.dataset import task
    from trajectory_tracking_agent.ruler.deployment import deployment

    item = task(task_id)
    ruler = run_task(ORACLE_SOLUTION, task_id)
    oracle_mm, oracle_moving = _oracle_rms_mm(item, _oracle_episode(item, deployment("ur5e_alone")))
    assert ruler["objective"] is not None and oracle_mm > 0.0
    # the two moving masks differ only by differencing at a move's edges (a sample or two), where the error is smallest
    assert abs(ruler["diagnostics"]["moving_samples"] - oracle_moving) <= 4
    assert ruler["objective"] == pytest.approx(oracle_mm, rel=0.01, abs=0.01)
