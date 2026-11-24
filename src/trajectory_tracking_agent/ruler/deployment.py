"""Deployment v1 `ur5e_alone` (OBJECTIVES §2): the robot, its plant and boards, the bus, the host rate and the scene.

    dep = deployment("ur5e_alone")
    dep.host_rate_hz, dep.bus, dep.board            # 50 Hz, the datasheet bus for six devices, the UR5e boards
    dep.tool_position(q)                            # (6,) -> (3,), (N, 6) -> (N, 3): the flange site `tool`
    dep.link_points(q)                              # (N, 6) -> (N, 9, 3): every body origin + the tool (floor gate)
    dep.plant()                                     # a fresh Ur5ePlant on dep.board (the ruler's, never a solution's)

Everything physical is imported from robot_controllers at its installed version, never copied or edited here
(`package_versions()` records which). The joint limits are the frozen dataset's (`station.json`), checked at load
against the MuJoCo model's ranges and the boards' caps; a disagreement refuses to build the deployment (fail closed).

The mount (checked 2026-11-24, `datasets/ur5e_alone/workspace/v2/README.md`): robot_controllers' bare UR5e keeps
Menagerie's base body (origin at the world origin, Rz(pi)); arm_motion_bench's floor mount puts the same base at the
origin with an identity quaternion. Over every sample of all 54 tapes the dataset's TCP equals Rz(pi) applied to this
model's flange + 0.144 m to 1e-15 m, so the two scenes differ only by a yaw about the vertical base axis: the floor plane
(z = 0 at the base), gravity (-z) and every distance the ruler measures are identical.
"""

from __future__ import annotations

import functools
import importlib.metadata
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

DEPLOYMENTS: tuple[str, ...] = ("ur5e_alone",)
HOST_RATE_HZ = 50.0  # the rig's host rate (robot_controllers BASE_RATE_HZ)
FLOOR_Z_M = 0.0  # the floor plane under the base
TOOL_OFFSET_M = 0.1  # the flange site `tool`, 0.1 m along wrist_3
LIMIT_TOLERANCE_RAD = 1e-5  # station.json's 2 pi vs the MJCF's 6.28319

__all__ = ["DEPLOYMENTS", "Deployment", "deployment", "package_versions"]


@dataclass(frozen=True)
class Deployment:
    """What a solution is given about where it runs (OBJECTIVES §2). Read-only; the ruler builds the plant from it."""

    name: str
    ruler: str
    title: str
    arm: str  # the robot_controllers arm registry name
    joint_names: tuple[str, ...]
    host_rate_hz: float
    bus: Any  # robot_controllers.timing.BusTiming
    board: Any  # robot_controllers.bench.board.BoardConfig
    torque_cap_nm: tuple[float, ...]
    position_min_rad: tuple[float, ...]
    position_max_rad: tuple[float, ...]
    velocity_max_rad_s: tuple[float, ...]
    floor_z_m: float
    tool_site: str
    tool_offset_m: float
    gravity_m_s2: tuple[float, float, float]

    @property
    def host_period_s(self) -> float:
        return 1.0 / self.host_rate_hz

    @property
    def timing(self) -> Any:
        """The robot_controllers HostTiming the bus implies at the host rate: no wake jitter, no stalls, and each command
        sent at its wake time (`include_compute=False`).

        WHY the send time leaves out the tick's CPU time (lane E, 2026-11-24, measured): with robot_controllers' default
        (send = wake + the tick's measured CPU time) a tick of 0.1-0.3 ms latches on one 0.25 ms board tick or the next at
        random, so the score depends on host load: p6s (feed-forward at the host, mj_inverse every tick) scored 0.832 and
        0.823 mm on two identical single-worker dev runs (one task 6.7 % apart), the size of the gap between the top two
        solutions. Without it two runs are bit-identical. It also keeps OBJECTIVES §4's word: `host_compute_ms_p95` is a
        diagnostic, "reported, never optimized", so the tick's cost must not leak into the objective as noise. A slow
        tick is still bounded by the 10x wall-time box and shows in `host_compute_ms_p95`.
        """
        from robot_controllers.bench.types import HostTiming

        return HostTiming.from_bus(self.bus, self.host_rate_hz, include_compute=False)

    def tool_position(self, q: Any) -> np.ndarray:
        """The tool point (m, world = base frame) for joint angles q: (6,) -> (3,), (N, 6) -> (N, 3)."""
        from robot_controllers.bench.ur5e import tool_position

        return tool_position(q)

    def link_points(self, q: Any) -> np.ndarray:
        """Every body origin of the bare model (base included) and the tool point: (N, 6) -> (N, bodies + 1, 3)."""
        return _link_kinematics()(q)

    def plant(self) -> Any:
        """A fresh Ur5ePlant (the "truth": armature, dry friction, damping) behind this deployment's boards."""
        from robot_controllers.bench.ur5e import Ur5ePlant

        return Ur5ePlant(board_config=self.board)

    def record(self) -> dict[str, Any]:
        """JSON-safe: what a scorecard says the deployment was."""
        from dataclasses import asdict

        return {
            "name": self.name,
            "ruler": self.ruler,
            "title": self.title,
            "arm": self.arm,
            "joint_names": list(self.joint_names),
            "host_rate_hz": self.host_rate_hz,
            "bus": {
                "command_delay_ms": [round(1e3 * v, 9) for v in self.bus.per_joint(len(self.joint_names))],
                "reply_delay_ms": 1e3 * self.bus.reply_delay_s,
                "jitter_ms": 1e3 * self.bus.jitter_s,
                "source": self.bus.source,
            },
            "board": asdict(self.board),
            "torque_cap_nm": list(self.torque_cap_nm),
            "position_min_rad": list(self.position_min_rad),
            "position_max_rad": list(self.position_max_rad),
            "velocity_max_rad_s": list(self.velocity_max_rad_s),
            "send_time": "the host's wake time (include_compute=False: the tick's CPU time is reported as "
            "host_compute_ms_p95, never added to the bus)",
            "floor_z_m": self.floor_z_m,
            "tool_site": self.tool_site,
            "tool_offset_m": self.tool_offset_m,
            "gravity_m_s2": list(self.gravity_m_s2),
            "plant": "robot_controllers.bench.ur5e.Ur5ePlant (UR5E_TRUTH: armature, frictionloss, damping)",
        }


class _LinkKinematics:
    """Body origins + the tool site on a private copy of the bare model (mj_kinematics only)."""

    def __init__(self) -> None:
        import mujoco

        from robot_controllers.bench.ur5e import TOOL_SITE, load_model

        self._mujoco = mujoco
        self.model = load_model(frictionloss=False)
        self.data = mujoco.MjData(self.model)
        self.site = self.model.site(TOOL_SITE).id
        self.bodies = list(range(1, self.model.nbody))  # 0 is the world

    def __call__(self, q: Any) -> np.ndarray:
        rows = np.atleast_2d(np.asarray(q, dtype=np.float64))
        out = np.empty((rows.shape[0], len(self.bodies) + 1, 3))
        for row in range(rows.shape[0]):
            if not np.isfinite(rows[row]).all():
                out[row] = np.nan  # fail closed: a NaN pose is below every floor
                continue
            self.data.qpos[:] = rows[row]
            self._mujoco.mj_kinematics(self.model, self.data)
            out[row, :-1] = self.data.xpos[self.bodies]
            out[row, -1] = self.data.site_xpos[self.site]
        return out


@functools.lru_cache(maxsize=1)
def _link_kinematics() -> _LinkKinematics:
    return _LinkKinematics()


def _station() -> dict[str, Any]:
    from trajectory_tracking_agent.ruler.dataset import DATASET_DIR

    return json.loads((DATASET_DIR / "station.json").read_text())


@functools.lru_cache(maxsize=4)
def deployment(name: str = "ur5e_alone") -> Deployment:
    """The deployment `name` (only `ur5e_alone` in ruler v1). Raises ValueError for any other name, and RuntimeError when
    the frozen dataset's station disagrees with robot_controllers' UR5e (joint names, limits, caps, gravity)."""
    if name not in DEPLOYMENTS:
        raise ValueError(f"no deployment {name!r}; ruler v1 has {DEPLOYMENTS}")
    from robot_controllers.bench.scenarios import BASE_RATE_HZ, datasheet_bus
    from robot_controllers.bench.ur5e import TOOL_SITE, UR5E_JOINTS, UR5E_TRUTH, load_model, ur5e_board_config

    station = _station()
    joints = station["joints"]
    names = tuple(joint["name"] for joint in joints)
    problems = []
    if names != UR5E_JOINTS:
        problems.append(f"station joints {names} != robot_controllers UR5E_JOINTS {UR5E_JOINTS}")
    low = tuple(float(joint["position_min_rad"]) for joint in joints)
    high = tuple(float(joint["position_max_rad"]) for joint in joints)
    speed = tuple(float(joint["velocity_max_rad_s"]) for joint in joints)
    caps = tuple(float(joint["torque_cap_nm"]) for joint in joints)
    board = ur5e_board_config()
    if caps != tuple(board.torque_cap_nm) or caps != tuple(UR5E_TRUTH.torque_cap_nm):
        problems.append(f"station torque caps {caps} != the boards' {board.torque_cap_nm}")
    model = load_model(frictionloss=False)
    for index, joint_name in enumerate(UR5E_JOINTS[: len(low)]):
        model_low, model_high = (float(v) for v in model.jnt_range[model.joint(joint_name).id])
        if abs(model_low - low[index]) > LIMIT_TOLERANCE_RAD or abs(model_high - high[index]) > LIMIT_TOLERANCE_RAD:
            problems.append(f"{joint_name}: station range ({low[index]}, {high[index]}) != MJCF ({model_low}, {model_high})")
    gravity = tuple(float(v) for v in model.opt.gravity)
    if gravity != (0.0, 0.0, -9.81):
        problems.append(f"gravity {gravity} is not (0, 0, -9.81): the floor would not be under the arm")
    base = model.body("base")
    if np.any(np.asarray(base.pos) != 0.0):
        problems.append(f"the base body is at {base.pos}, not on the floor at the origin")
    if not all(math.isfinite(v) and v > 0.0 for v in speed):
        problems.append(f"velocity limits {speed} must be finite and > 0")
    if HOST_RATE_HZ != BASE_RATE_HZ:
        problems.append(f"host rate {HOST_RATE_HZ} != robot_controllers' base rate {BASE_RATE_HZ}")
    if problems:
        raise RuntimeError("deployment ur5e_alone refuses to build:\n- " + "\n- ".join(problems))
    return Deployment(
        name=name,
        ruler="v1",
        title="UR5e (MuJoCo Menagerie, the robot_controllers truth plant) alone on the floor, moteus boards, 50 Hz host",
        arm="ur5e",
        joint_names=UR5E_JOINTS,
        host_rate_hz=HOST_RATE_HZ,
        bus=datasheet_bus("ur5e"),
        board=board,
        torque_cap_nm=caps,
        position_min_rad=low,
        position_max_rad=high,
        velocity_max_rad_s=speed,
        floor_z_m=FLOOR_Z_M,
        tool_site=TOOL_SITE,
        tool_offset_m=TOOL_OFFSET_M,
        gravity_m_s2=gravity,
    )


# ── provenance ──────────────────────────────────────────────────────────────────────────────────────────────


def _git(directory: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(directory), *args], capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()

    try:
        root = Path(run("rev-parse", "--show-toplevel"))
        return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "src")), "repo": root.name}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None, "repo": None}


@functools.lru_cache(maxsize=1)
def package_versions() -> dict[str, dict[str, Any]]:
    """robot_controllers' and robot_msgs' installed version and the git commit of the tree they were imported from."""
    import robot_controllers
    import robot_msgs

    out = {}
    for name, module in (("robot_controllers", robot_controllers), ("robot_msgs", robot_msgs)):
        try:
            version = importlib.metadata.version(name.replace("_", "-"))
        except importlib.metadata.PackageNotFoundError:
            version = getattr(module, "__version__", None)
        out[name] = {"version": version, **_git(Path(module.__file__).resolve().parent)}
    return out
