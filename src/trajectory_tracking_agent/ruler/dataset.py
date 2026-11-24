"""The dataset v1 `ur5e_alone/workspace/v2` (OBJECTIVES §3): the frozen tasks and their speed-1.0 tapes.

    tasks("dev")                       # 42 Task(id, split, kind, trajectory, duration_s, meta), in the dataset's order
    tasks("holdout")                   # 12; scored only by evaluate(..., split="holdout"), for reporting
    verify()                           # [] when every sha256 (dataset + tapes) and every structural check holds

The folder is a byte-for-byte copy of arm_motion_bench `datasets/ur5e_alone/workspace/v2/` (manifest.json, tasks.jsonl,
station.json, rejections.jsonl) plus `tapes/<task_id>.npz`, the rung-1.0 tapes arm_motion_bench's own generator writes
(robot_msgs `save_npz` of the bam_ruckig-timed JointTrajectory, with the dataset station's TCP as `tcp_pos` / `tcp_rot`,
which the ruler ignores). `tapes_manifest.json` records the sha256 of every file here; each tape's sha256 is also the one
arm_motion_bench's manifest lists, so the chain back to the generator is unbroken. See the folder's README.md.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_DIR = REPO_ROOT / "datasets" / "ur5e_alone" / "workspace" / "v2"
TAPES_DIR = DATASET_DIR / "tapes"
TAPES_MANIFEST = DATASET_DIR / "tapes_manifest.json"
DATASET_FILES: tuple[str, ...] = ("manifest.json", "tasks.jsonl", "station.json", "rejections.jsonl")
SPLITS: tuple[str, ...] = ("dev", "holdout")
EXPECTED_COUNTS: Mapping[str, int] = {"dev": 42, "holdout": 12}  # OBJECTIVES §3
SPEED = 1.0  # ruler v1 scores speed 1.0 only

__all__ = ["DATASET_DIR", "SPLITS", "Task", "sha256", "task", "tasks", "verify"]


@dataclass(frozen=True)
class Task:
    """One frozen task: `trajectory` is the robot_msgs JointTrajectory a solution is built from (UR5E_JOINTS order,
    t from 0, positions / velocities / accelerations, no effort column), `meta` its tasks.jsonl row (minus the
    trajectory)."""

    id: str
    split: str
    kind: str
    order: int
    trajectory: Any = field(repr=False)
    meta: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def duration_s(self) -> float:
        return float(self.trajectory.t[-1])


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@functools.lru_cache(maxsize=1)
def _rows() -> tuple[dict[str, Any], ...]:
    lines = (DATASET_DIR / "tasks.jsonl").read_text().splitlines()
    return tuple(json.loads(line) for line in lines if line.strip())


def _check_joints(trajectory: Any, task_id: str) -> None:
    from robot_controllers.bench.ur5e import UR5E_JOINTS

    # WHY an explicit check (lane E brief): the plant, the boards and the tool FK index joints in UR5E_JOINTS order; a
    # tape in another order would be scored on the wrong joints without any error
    if tuple(trajectory.joint_names) != UR5E_JOINTS:
        raise ValueError(f"{task_id}: tape joints {tuple(trajectory.joint_names)} are not UR5E_JOINTS {UR5E_JOINTS}")


@functools.lru_cache(maxsize=64)
def _trajectory(task_id: str) -> Any:
    from robot_msgs import load_npz

    trajectory = load_npz(TAPES_DIR / f"{task_id}.npz")
    _check_joints(trajectory, task_id)
    return trajectory


def tasks(split: str = "dev") -> tuple[Task, ...]:
    """Every task of `split`, in the dataset's order. Raises ValueError for another split name."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    rows = sorted((row for row in _rows() if row["split"] == split), key=lambda row: (row["order"], row["task_id"]))
    return tuple(
        Task(
            id=row["task_id"],
            split=row["split"],
            kind=row["kind"],
            order=int(row["order"]),
            trajectory=_trajectory(row["task_id"]),
            meta={key: value for key, value in row.items() if key != "keyposes"},
        )
        for row in rows
    )


def task(task_id: str) -> Task:
    for split in SPLITS:
        for item in tasks(split):
            if item.id == task_id:
                return item
    raise KeyError(f"no task {task_id!r}")


def verify() -> list[str]:
    """Re-check the frozen dataset; [] when it is intact. Checks, failing closed:

    1. every file in tapes_manifest.json exists with that sha256, and nothing else sits in the folder or tapes/;
    2. tasks.jsonl's sha256 is the one arm_motion_bench's manifest froze (`tasks_sha256`);
    3. every tape's sha256 is the one arm_motion_bench's manifest lists for it (`files`);
    4. every task has exactly one tape, the split counts are 42 / 12, and every tape's joints are UR5E_JOINTS in order,
       its clock starts at 0 and increases, and every array is finite.
    """
    import numpy as np

    problems: list[str] = []
    if not TAPES_MANIFEST.exists():
        return [f"{TAPES_MANIFEST} is missing"]
    record = json.loads(TAPES_MANIFEST.read_text())
    listed: dict[str, str] = dict(record.get("files", {}))
    if not listed:
        problems.append("tapes_manifest.json lists no files")
    for name, digest in sorted(listed.items()):
        path = DATASET_DIR / name
        if not path.exists():
            problems.append(f"{name}: missing")
        elif sha256(path) != digest:
            problems.append(f"{name}: sha256 {sha256(path)} != tapes_manifest.json {digest}")
    present = {str(p.relative_to(DATASET_DIR)) for p in DATASET_DIR.rglob("*") if p.is_file()}
    expected = set(listed) | {"tapes_manifest.json", "README.md"}
    for name in sorted(present - expected):
        problems.append(f"{name}: not in tapes_manifest.json (a frozen folder gains no files)")
    for name in DATASET_FILES:
        if name not in listed:
            problems.append(f"{name}: not recorded in tapes_manifest.json")
    if problems:
        return problems  # the rest reads these files

    upstream = json.loads((DATASET_DIR / "manifest.json").read_text())
    if sha256(DATASET_DIR / "tasks.jsonl") != upstream.get("tasks_sha256"):
        problems.append("tasks.jsonl: sha256 differs from arm_motion_bench's manifest tasks_sha256")
    upstream_files = upstream.get("files", {})
    tape_names = sorted(name for name in listed if name.startswith("tapes/"))
    for name in tape_names:
        if upstream_files.get(Path(name).name) != listed[name]:
            problems.append(f"{name}: sha256 is not the one arm_motion_bench's manifest lists for {Path(name).name}")

    rows = _rows()
    ids = [row["task_id"] for row in rows]
    if len(set(ids)) != len(ids):
        problems.append("tasks.jsonl repeats a task id")
    if sorted(f"tapes/{task_id}.npz" for task_id in ids) != tape_names:
        problems.append("the tapes are not exactly one per task")
    for split, count in EXPECTED_COUNTS.items():
        found = sum(1 for row in rows if row["split"] == split)
        if found != count or upstream.get("counts", {}).get(split, {}).get("total") != count:
            problems.append(f"{split}: {found} tasks, the frozen dataset has {count}")
    for task_id in ids:
        try:
            trajectory = _trajectory(task_id)
        except Exception as error:  # noqa: BLE001 - every unreadable tape is a finding
            problems.append(f"{task_id}: {type(error).__name__}: {error}")
            continue
        t = np.asarray(trajectory.t, dtype=float)
        arrays = [t, trajectory.positions, trajectory.velocities, trajectory.accelerations]
        if any(a is None or not np.isfinite(np.asarray(a, dtype=float)).all() for a in arrays):
            problems.append(f"{task_id}: a missing or non-finite array")
        elif t[0] != 0.0 or not (np.diff(t) > 0.0).all():
            problems.append(f"{task_id}: the clock does not start at 0 and increase")
    return problems
