"""Build the landing page's data (site/data/) from saved run records, check it, and shoot its media.

    uv run --all-extras python tools/build_site.py build     # site/data/playback/ + site/data/page.json + sources
    uv run --all-extras python tools/build_site.py check     # every shipped number equals its scorecard row, exactly
    uv run --no-project --with playwright==1.64.1 python tools/build_site.py shoot   # headless screenshots + hero video

The page plays back saved runs; nothing is simulated or scored in the browser (Zach, 2026-11-24: "You can just
playback saved runs"). `tta evaluate <id>` already writes one run record per task (`outputs/runs/<id>/dev/<task>.json`,
gitignored: the target, the measured joints and torques, the tool points, and the ruler's own `metrics` / `gates`).
`build` turns the shipped ones into small binary files the page decodes:

- **Which runs ship** (`selection()`, the rule in site/README.md): from `ledger.jsonl`, every scored solution not tagged
  `ablation` on one representative dev task per task kind (the first of each kind in dataset order), plus the best
  admissible solution and the best generation-0 one on all 42 dev tasks. A missing or stale record (its numbers differ
  from the scorecard's) stops the build with the `tta evaluate` command that rewrites it; records are never edited.
- **What the page draws is computed here, natively**: the arm's geom poses per frame from the deployment's own model
  and `mj_kinematics` (checked against `deployment.link_points`), the tool error from `metrics.tool_errors_m`, the stops
  from `metrics.stop_errors_mm`, the lowest moving point from `deployment.link_points`. The browser does no kinematics.
- **The numbers on the cards are the record's own** `metrics` / `gates` (computed by the ruler when the run was
  scored), copied as JSON floats; `check` proves each equals its scorecard's per-task row.

`shoot` drives headless Chromium through Playwright (its cached browser; never a visible window) over a server on
127.0.0.1 it starts and stops itself.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
DATA = SITE / "data"
PLAYBACK = DATA / "playback"
SOURCES = DATA / "solutions"
RUNS = REPO / "outputs" / "runs"
LEDGER = REPO / "ledger.jsonl"
OUTPUTS = REPO / "outputs" / "site"
DATASET_REL = Path("datasets/ur5e_alone/workspace/v2")
GITHUB = "https://github.com/zacharyyamaoka"
REPO_URL = f"{GITHUB}/trajectory_tracking_agent"
ROBOT_MSGS_REPO = REPO / ".." / "robot_msgs"

EXCLUDED_TAG = "ablation"  # ablation solutions test which parts matter; they are not search progress (coordinator, 11-24)
GEN0_TAG = "gen-0"
MAGIC = b"TTAPLAY1"
PLAYBACK_SCHEMA = "tta.playback/1"
INDEX_SCHEMA = "tta.playback_index/1"
SIZE_LIMIT_BYTES = 15 * 1024 * 1024  # all of site/, committed
# WHY 1e-3 mm: the record stores positions rounded to 0.1 um (evaluate._write_record), so the ruler's function re-run
# on the record's arrays reproduces the scored number only to ~1e-4 mm; 1e-3 mm is far below the 3 digits a card shows
CHECK_TOLERANCE_MM = 1e-3

# The stored resolution of each array: display only (the arm, the plots). Every number on a card is the record's own
# float, never one of these.
STEP = {
    "t": 1e-6,  # s
    "q": 1e-7,  # rad: the record's own rounding
    "qd": 1e-5,  # rad/s
    "tau": 1e-4,  # N·m
    "tool": 1e-7,  # m: the record's own rounding
    "error_mm": 1e-5,  # mm
    "geom_pos": 1e-5,  # m: 10 um on a drawn arm (the drawn errors use `tool`, not the arm)
    "geom_quat": 1e-5,
    "lowest": 1e-5,  # m
    "flag": 1,
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _json_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ── the codec: integer arrays, first difference along time, byte planes, gzip ───────────────────────────────


def _pack(ints: Any) -> tuple[bytes, str]:
    """(N, ...) integers -> bytes: each column contiguous, its first difference along time (the first value kept),
    the narrowest signed integer that holds it, little-endian, its bytes split into planes (low bytes first)."""
    import numpy as np

    values = np.asarray(ints, dtype=np.int64)
    rows = values.shape[0]
    columns = values.reshape(rows, -1).T
    delta = np.diff(columns, axis=1, prepend=0)
    peak = int(np.abs(delta).max()) if delta.size else 0
    if peak >= 2**31:
        raise ValueError(f"a step of {peak} does not fit int32")
    size = 1 if peak < 2**7 else 2 if peak < 2**15 else 4
    flat = np.ascontiguousarray(delta.astype(f"<i{size}")).ravel()
    planes = flat.view(np.uint8).reshape(-1, size).T
    return np.ascontiguousarray(planes).tobytes(), f"i{8 * size}"


def _unpack(data: bytes, dtype: str, shape: list[int]) -> Any:
    """The inverse of `_pack`: (N, ...) int64."""
    import numpy as np

    size = int(dtype[1:]) // 8
    count = int(np.prod(shape)) if shape else 0
    planes = np.frombuffer(data, dtype=np.uint8).reshape(size, count)
    delta = np.ascontiguousarray(planes.T).view(f"<i{size}").reshape(-1).astype(np.int64)
    rows = shape[0]
    columns = np.cumsum(delta.reshape(-1, rows), axis=1) if rows else delta.reshape(0, 0)
    return columns.T.reshape(shape)


def _intervals_of(mask: Any) -> list[list[int]]:
    """Runs of True in `mask` as [first, last] row indices."""
    out, start = [], None
    for index, flag in enumerate(mask):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            out.append([start, index - 1])
            start = None
    if start is not None:
        out.append([start, len(mask) - 1])
    return out


def write_playback(path: Path, header: dict[str, Any], arrays: dict[str, tuple[Any, float, str | None]]) -> int:
    """One playback file: gzip(MAGIC + uint32 header length + header JSON + the packed arrays). `arrays` maps a name to
    (integers, step, base): value = (integers + the task file's integers of `base`) x step. Returns the bytes written."""
    payload = bytearray()
    specs: dict[str, Any] = {}
    for name, (ints, step, base) in arrays.items():
        data, dtype = _pack(ints)
        specs[name] = {"shape": list(ints.shape), "step": step, "dtype": dtype, "offset": len(payload), "bytes": len(data)}
        if base:
            specs[name]["base"] = base
        payload += data
    head = json.dumps({**header, "arrays": specs}, separators=(",", ":"), allow_nan=False).encode()
    blob = MAGIC + struct.pack("<I", len(head)) + head + bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(blob, compresslevel=9, mtime=0)  # mtime 0: a rebuild with no change is byte-identical
    path.write_bytes(data)
    return len(data)


def read_playback(path: Path, base: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(header, values, integers) of one playback file; `base` is the task file's integers for a run file. The page's
    decoder (site/assets/playback.js) is this function in JavaScript; `shoot` checks the two agree."""
    blob = gzip.decompress(path.read_bytes())
    if blob[: len(MAGIC)] != MAGIC:
        raise ValueError(f"{path}: not a playback file")
    length = struct.unpack("<I", blob[len(MAGIC): len(MAGIC) + 4])[0]
    start = len(MAGIC) + 4
    header = json.loads(blob[start: start + length])
    payload = blob[start + length:]
    ints, values = {}, {}
    for name, spec in header["arrays"].items():
        array = _unpack(payload[spec["offset"]: spec["offset"] + spec["bytes"]], spec["dtype"], spec["shape"])
        if spec.get("base"):
            array = array + base[spec["base"]]
        ints[name] = array
        values[name] = array * spec["step"]
    return header, values, ints


def _quantize(values: Any, step: float) -> Any:
    import numpy as np

    array = np.asarray(values, dtype=np.float64)
    return np.rint(np.where(np.isfinite(array), array, 0.0) / step).astype(np.int64)


# ── which runs ship: the rule ───────────────────────────────────────────────────────────────────────────────


def _meta(solution_id: str) -> dict[str, Any]:
    path = REPO / "solutions" / solution_id / "meta.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _scorecard(solution_id: str) -> dict[str, Any] | None:
    path = REPO / "solutions" / solution_id / "scorecard.json"
    return json.loads(path.read_text()) if path.exists() else None


def _rank_key(row: dict[str, Any]) -> tuple:
    """OBJECTIVES §4's ranking: admissible by objective, then the rest by gate pass rate, then objective."""
    objective = row["objective"] if isinstance(row.get("objective"), (int, float)) and math.isfinite(row["objective"]) \
        else math.inf
    return (not row["admissible"], 0.0 if row["admissible"] else -(row.get("gate_pass_rate") or 0.0), objective)


def _dev_tasks() -> list[dict[str, Any]]:
    """The dev tasks in dataset order: id, kind, duration (s, from the tape)."""
    from robot_msgs import load_npz

    rows = [row for row in _json_lines(REPO / DATASET_REL / "tasks.jsonl") if row["split"] == "dev"]
    rows.sort(key=lambda row: (row["order"], row["task_id"]))
    return [{"id": row["task_id"], "kind": row["kind"],
             "duration_s": float(load_npz(REPO / DATASET_REL / "tapes" / f"{row['task_id']}.npz").t[-1])} for row in rows]


def _dev_task_kinds() -> list[tuple[str, str]]:
    """(task id, kind) of every dev task in dataset order (no tapes read: for `check` and the tests)."""
    rows = [row for row in _json_lines(REPO / DATASET_REL / "tasks.jsonl") if row["split"] == "dev"]
    rows.sort(key=lambda row: (row["order"], row["task_id"]))
    return [(row["task_id"], row["kind"]) for row in rows]


def selection() -> dict[str, Any]:
    """The rule, read from the ledger (site/README.md states it): the latest dev row of every solution that has a
    scorecard and is not tagged `ablation`; every one of them on the first dev task of each kind; the best admissible
    solution and the best admissible generation-0 solution (`gen-0` tag) on every dev task."""
    latest: dict[str, dict[str, Any]] = {}
    for row in _json_lines(LEDGER):
        if row.get("split") == "dev":
            latest[row["solution"]] = row
    solutions, excluded = [], []
    for solution_id, row in latest.items():
        if not (REPO / "solutions" / solution_id / "scorecard.json").exists():
            continue
        tags = _meta(solution_id).get("tags", [])
        if EXCLUDED_TAG in tags:
            excluded.append(solution_id)
            continue
        solutions.append({"id": solution_id, "objective": row.get("objective"), "admissible": bool(row.get("admissible")),
                          "gate_pass_rate": row.get("gate_pass_rate"), "gen0": GEN0_TAG in tags})
    solutions.sort(key=lambda row: (_rank_key(row), row["id"]))
    admissible = [row for row in solutions if row["admissible"] and math.isfinite(_rank_key(row)[2])]
    best = admissible[0]["id"] if admissible else None
    gen0 = next((row["id"] for row in admissible if row["gen0"]), None)
    tasks = _dev_task_kinds()
    representative, kinds = [], set()
    for task_id, kind in tasks:
        if kind not in kinds:
            kinds.add(kind)
            representative.append(task_id)
    full = [sid for sid in dict.fromkeys([best, gen0]) if sid]
    pairs = {row["id"]: [task_id for task_id, _ in tasks] if row["id"] in full else list(representative)
             for row in solutions}
    return {
        "text": "Every scored solution not tagged `ablation` (from ledger.jsonl, its latest dev row) on the first dev task "
        "of each task kind; the best admissible solution and the best admissible generation-0 solution on all "
        f"{len(tasks)} dev tasks.",
        "solutions": [row["id"] for row in solutions],
        "representative_tasks": representative,
        "full": {"best": best, "gen0_best": gen0},
        "excluded": {EXCLUDED_TAG: sorted(excluded)},
        "pairs": pairs,
        "count": sum(len(tasks_) for tasks_ in pairs.values()),
    }


# ── native precomputation ───────────────────────────────────────────────────────────────────────────────────


class _Poses:
    """The UR5e's geom poses per row of joint angles: the deployment's own model and mj_kinematics (the FK behind
    `deployment.link_points` and `tool_position`), so the browser draws poses and never computes one."""

    def __init__(self, dep: Any) -> None:
        import mujoco

        from robot_controllers.bench.ur5e import load_model

        self.mujoco = mujoco
        self.dep = dep
        self.model = load_model(frictionloss=False)
        self.data = mujoco.MjData(self.model)

    def geoms(self) -> dict[str, Any]:
        m = self.model
        return {"type": m.geom_type.tolist(), "size": m.geom_size.tolist(), "body": m.geom_bodyid.tolist(),
                "count": int(m.ngeom), "bodies": int(m.nbody)}

    def point_names(self) -> list[str]:
        """The points the floor gate reads, as `deployment.link_points` orders them: every body but the world, the tool."""
        return [self.model.body(index).name for index in range(1, self.model.nbody)] + [self.dep.tool_site]

    def __call__(self, q: Any, align: Any = None) -> tuple[Any, Any]:
        """(pos (N, G, 3) m, quat (N, G, 4) w-x-y-z); NaN rows stay NaN. Quaternion signs follow `align` (another
        (N, G, 4) array) when given, else run continuously in time (the same rotation either way; it packs smaller)."""
        import numpy as np

        rows = np.atleast_2d(np.asarray(q, dtype=np.float64))
        count, geoms = rows.shape[0], self.model.ngeom
        pos = np.full((count, geoms, 3), np.nan)
        quat = np.full((count, geoms, 4), np.nan)
        bodies = np.full((count, self.model.nbody - 1, 3), np.nan)
        for index, row in enumerate(rows):
            if not np.isfinite(row).all():
                continue
            self.data.qpos[:] = row
            self.mujoco.mj_kinematics(self.model, self.data)
            pos[index] = self.data.geom_xpos
            bodies[index] = self.data.xpos[1:]
            for geom in range(geoms):
                self.mujoco.mju_mat2Quat(quat[index, geom], self.data.geom_xmat[geom])
        # the same model as the ruler's floor gate: its body origins must be deployment.link_points'
        reference = self.dep.link_points(rows)[:, :-1]
        finite = np.isfinite(reference).all(axis=(1, 2))
        if not np.allclose(bodies[finite], reference[finite], rtol=0.0, atol=1e-12):
            raise SystemExit("the geom poses' model is not deployment.link_points' model")
        for index in range(count):
            for geom in range(geoms):
                previous = align[index, geom] if align is not None else (quat[index - 1, geom] if index else None)
                if previous is not None and np.isfinite(previous).all() and np.dot(quat[index, geom], previous) < 0:
                    quat[index, geom] *= -1.0
        return pos, quat


def _array(record: dict[str, Any], name: str) -> Any:
    import numpy as np

    return np.asarray([[math.nan if v is None else v for v in row] if isinstance(row, list) else
                       (math.nan if row is None else row) for row in record[name]], dtype=np.float64)


def _clean(value: Any) -> Any:
    import numpy as np

    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    return value


def _time_intervals(t: Any, mask: Any) -> list[list[float]]:
    return [[float(t[a]), float(t[b])] for a, b in _intervals_of(mask)]


def _explain(record: dict[str, Any], dep: Any, points: Any) -> dict[str, Any]:
    """What each card's explanation shows, computed with the ruler's own functions on the record's arrays, and each
    one checked against the ruler's number (`checks`; the 4 kHz gates: `subset`)."""
    import numpy as np

    from trajectory_tracking_agent.ruler import metrics

    m = record["metrics"]
    t = np.asarray(record["t"], dtype=np.float64)
    target_tool, tool = _array(record, "tool_target_xyz"), _array(record, "tool_xyz")
    moving = np.asarray(record["moving"], dtype=bool)
    stops = [(float(a), float(b)) for a, b in record["stops"]]
    q, qd, tau = _array(record, "q"), _array(record, "qd"), _array(record, "tau")
    caps = np.asarray(record["tau_cap"], dtype=np.float64)

    def check(name: str, ruler: Any, from_record: float) -> dict[str, Any]:
        ok = (ruler is None and not math.isfinite(from_record)) or (
            ruler is not None and math.isfinite(from_record) and abs(ruler - from_record) <= CHECK_TOLERANCE_MM)
        return {"ruler": ruler, "record": _clean(from_record), "tolerance": CHECK_TOLERANCE_MM, "ok": bool(ok)}

    checks = {
        "tool_track_rms_mm": check("tool_track_rms_mm", m.get("tool_track_rms_mm"),
                                   metrics.tool_track_rms_mm(target_tool, tool, moving)),
        "stop_error_max_mm": check("stop_error_max_mm", m.get("stop_error_max_mm"),
                                   metrics.stop_error_max_mm(t, target_tool, tool, stops)),
    }
    stop_errors = metrics.stop_errors_mm(t, target_tool, tool, stops) if stops else []
    stop_rows = []
    for (t0, t1), error in zip(stops, stop_errors, strict=True):
        start = max(t0, t1 - metrics.HOLD_WINDOW_S)
        window = (t >= start - metrics.TIME_TOLERANCE_S) & (t <= t1 + metrics.TIME_TOLERANCE_S)
        stop_rows.append({"t0": t0, "t1": t1, "hold": [start, t1], "error_mm": _clean(error),
                          "mean_xyz": _clean(tool[window].mean(axis=0)), "target_xyz": _clean(target_tool[window].mean(axis=0)),
                          "samples": int(np.count_nonzero(window))})

    # the violation gates read every 4 kHz physics sample; the record keeps the 100 Hz ones, a subset of them (the
    # target's grid falls on the physics grid exactly), so a violation seen here must be one the ruler counted
    saturated = np.abs(tau) >= metrics.SATURATION_FRACTION * caps
    q_lo, q_hi, qd_max = (np.asarray(record[key], dtype=np.float64) for key in ("q_min", "q_max", "qd_max"))
    outside = (q < q_lo) | (q > q_hi) | (np.abs(qd) > metrics.VELOCITY_LIMIT_ALLOWANCE * qd_max) | ~np.isfinite(q)
    heights = points[:, :, 2]
    below = ~np.all(heights >= float(record["floor_z"]), axis=1)

    def subset(ruler: Any, count: int) -> dict[str, Any]:
        consistent = None if ruler is None else bool(not (count > 0 and ruler == 0))
        return {"ruler": ruler, "record_samples": int(count), "consistent": consistent}

    subsets = {
        "saturation_share_pct": {**subset(m.get("saturation_share_pct"), int(np.count_nonzero(saturated.any(axis=1)))),
                                 "record_share_pct": _clean(metrics.saturation_share_pct(tau, caps))},
        "limit_violations": subset(m.get("limit_violations"), int(np.count_nonzero(outside.any(axis=1)))),
        "floor_clearance": subset(m.get("floor_clearance_violations"), int(np.count_nonzero(below))),
    }

    # the floor: the base origin sits on the plane and the shoulder origins never change height, so the explanation
    # follows the points that move (the gate reads every point, as the ruler does)
    finite = np.isfinite(heights).all(axis=1)
    varies = np.ptp(heights[finite], axis=0) > 1e-6 if finite.any() else np.ones(heights.shape[1], dtype=bool)
    if not varies.any():
        varies[:] = True
    moving_points = np.flatnonzero(varies)
    moving_z = np.where(finite[:, None], heights[:, moving_points], np.inf)
    lowest_moving = moving_z.min(axis=1)
    k = int(np.argmin(lowest_moving))
    point = int(moving_points[int(np.argmin(moving_z[k]))])
    lowest = {"t": float(t[k]), "z": _clean(lowest_moving[k]), "point": point, "xyz": _clean(points[k, point]),
              "fixed_points": {str(int(i)): _clean(heights[finite][0, i]) for i in np.flatnonzero(~varies)} if finite.any() else {},
              "moving_points": moving_points.tolist()}
    return {
        "checks": checks,
        "subset": subsets,
        "stops": stop_rows,
        "moving_samples": int(np.count_nonzero(moving)),
        "saturated_per_joint": np.count_nonzero(saturated, axis=0).tolist(),
        "saturated_intervals": _time_intervals(t, saturated.any(axis=1)),
        "limit_intervals": _time_intervals(t, outside.any(axis=1)),
        "floor_intervals": _time_intervals(t, below),
        "lowest": lowest,
    }


# ── build ───────────────────────────────────────────────────────────────────────────────────────────────────


def _record_problem(solution_id: str, task_id: str, card: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    path = RUNS / solution_id / "dev" / f"{task_id}.json"
    if card is None:
        return None, "no scorecard"
    if not path.exists():
        return None, "no run record"
    record = json.loads(path.read_text())
    row = next((r for r in card["tasks"] if r["task"] == task_id), None)
    if row is None:
        return None, "the scorecard has no row for it"
    want = {"tool_track_rms_mm": row["objective"], **row["kpis"], **row["diagnostics"]}
    if record["metrics"] != want or record["gates"] != row["verdicts"] or record["notes"] != row["notes"]:
        return None, "the record's numbers differ from the scorecard's (stale)"
    return record, None


def export_playback() -> dict[str, Any]:
    """site/data/playback/: one file per shipped task (the target) and per shipped (solution, task) (the run), and the
    index. Refuses on a missing or stale record."""
    import numpy as np

    from trajectory_tracking_agent.ruler import gates, metrics
    from trajectory_tracking_agent.ruler.deployment import deployment

    rule = selection()
    dep = deployment("ur5e_alone")
    poses = _Poses(dep)
    tasks = {row["id"]: row for row in _dev_tasks()}
    cards = {sid: _scorecard(sid) for sid in rule["pairs"]}
    records: dict[tuple[str, str], dict[str, Any]] = {}
    problems = []
    for sid, task_ids in rule["pairs"].items():
        for task_id in task_ids:
            record, why = _record_problem(sid, task_id, cards[sid])
            if why:
                problems.append((sid, task_id, why))
            else:
                records[(sid, task_id)] = record
    if problems:
        stale = sorted({sid for sid, _, _ in problems})
        lines = [f"  {sid} {task}: {why}" for sid, task, why in problems[:12]]
        commands = "\n".join(f"  uv run --all-extras tta evaluate {sid}" for sid in stale)
        raise SystemExit(f"{len(problems)} run records are missing or stale:\n" + "\n".join(lines)
                         + f"\nRewrite them with the evaluator (never by hand):\n{commands}")

    if PLAYBACK.exists():
        shutil.rmtree(PLAYBACK)
    shipped_tasks = [task_id for task_id in tasks if any(task_id in ids for ids in rule["pairs"].values())]
    first = next(iter(records.values()))
    constants = {key: first[key] for key in ("joint_names", "tau_cap", "q_min", "q_max", "qd_max", "floor_z")}

    task_rows, task_state = [], {}
    for task_id in shipped_tasks:
        same = [record for (sid, tid), record in records.items() if tid == task_id]
        target = same[0]
        for other in same[1:]:  # one target per task: every solution's record carries the same tape
            for key in ("t", "q_target", "tool_target_xyz", "moving", "stops"):
                if other[key] != target[key]:
                    raise SystemExit(f"{task_id}: {other['solution']}'s record has a different {key}")
        for record in same:
            for key, value in constants.items():
                if record[key] != value:
                    raise SystemExit(f"{record['solution']} {task_id}: a different {key}")
        q_target = _array(target, "q_target")
        tool_target = _array(target, "tool_target_xyz")
        pos, quat = poses(q_target)
        points = dep.link_points(q_target)
        box = np.concatenate([points.reshape(-1, 3), tool_target])
        ints = {
            "t": (_quantize(target["t"], STEP["t"]), STEP["t"], None),
            "q_target": (_quantize(q_target, STEP["q"]), STEP["q"], None),
            "tool_target": (_quantize(tool_target, STEP["tool"]), STEP["tool"], None),
            "moving": (np.asarray(target["moving"], dtype=np.int64), STEP["flag"], None),
            "geom_pos": (_quantize(pos, STEP["geom_pos"]), STEP["geom_pos"], None),
            "geom_quat": (_quantize(quat, STEP["geom_quat"]), STEP["geom_quat"], None),
        }
        header = {"schema": PLAYBACK_SCHEMA, "file": "task", "task": task_id, "kind": tasks[task_id]["kind"],
                  "duration_s": tasks[task_id]["duration_s"], "samples": len(target["t"]), "stops": target["stops"],
                  "moving_samples": int(np.count_nonzero(target["moving"])),
                  "fit_box": [_clean(np.nanmin(box, axis=0)), _clean(np.nanmax(box, axis=0))]}
        rel = f"tasks/{task_id}.bin.gz"
        size = write_playback(PLAYBACK / rel, header, ints)
        task_state[task_id] = {"ints": {name: value[0] for name, value in ints.items()}, "quat": quat}
        task_rows.append({"id": task_id, "kind": tasks[task_id]["kind"], "duration_s": tasks[task_id]["duration_s"],
                          "samples": len(target["t"]), "file": rel, "bytes": size})

    worst = {"tool_track_rms_mm": 0.0, "stop_error_max_mm": 0.0}
    solution_rows = []
    for sid in rule["solutions"]:
        card = cards[sid]
        meta = _meta(sid)
        shipped: dict[str, Any] = {}
        for task_id in rule["pairs"][sid]:
            record = records[(sid, task_id)]
            base = task_state[task_id]["ints"]
            q = _array(record, "q")
            missing = ~np.isfinite(q).all(axis=1)
            tool, target_tool = _array(record, "tool_xyz"), _array(record, "tool_target_xyz")
            pos, quat = poses(q, align=task_state[task_id]["quat"])
            points = dep.link_points(q)
            errors_mm = 1e3 * metrics.tool_errors_m(target_tool, tool)
            explain = _explain(record, dep, points)
            moving_points = explain["lowest"]["moving_points"]
            mz = np.where(np.isfinite(points[:, moving_points, 2]), points[:, moving_points, 2], np.inf)
            lowest_xyz = points[np.arange(len(points)), np.asarray(moving_points)[np.argmin(mz, axis=1)]]

            def residual(values: Any, step: float, name: str) -> Any:
                out = _quantize(values, step) - base[name]
                out[missing] = 0  # a row with no measurement decodes to the target and is flagged missing
                return out

            ints = {
                "q": (residual(q, STEP["q"], "q_target"), STEP["q"], "q_target"),
                "qd": (_quantize(_array(record, "qd"), STEP["qd"]), STEP["qd"], None),
                "tau": (_quantize(_array(record, "tau"), STEP["tau"]), STEP["tau"], None),
                "tool": (residual(tool, STEP["tool"], "tool_target"), STEP["tool"], "tool_target"),
                "error_mm": (_quantize(errors_mm, STEP["error_mm"]), STEP["error_mm"], None),
                "geom_pos": (residual(pos, STEP["geom_pos"], "geom_pos"), STEP["geom_pos"], "geom_pos"),
                "geom_quat": (residual(quat, STEP["geom_quat"], "geom_quat"), STEP["geom_quat"], "geom_quat"),
                "lowest": (_quantize(lowest_xyz, STEP["lowest"]), STEP["lowest"], None),
            }
            for name, check in explain["checks"].items():
                if not check["ok"]:
                    raise SystemExit(f"{sid} {task_id}: the record's arrays give {name} = {check['record']}, the ruler "
                                     f"{check['ruler']} (tolerance {CHECK_TOLERANCE_MM} mm)")
                if check["ruler"] is not None:
                    worst[name] = max(worst[name], abs(check["ruler"] - check["record"]))
            header = {"schema": PLAYBACK_SCHEMA, "file": "run", "solution": sid, "task": task_id, "split": "dev",
                      "ruler": record["ruler"], "record_schema": record["schema"], "samples": len(record["t"]),
                      "metrics": record["metrics"], "gates": record["gates"], "notes": record["notes"],
                      "missing": _intervals_of(missing), "explain": explain}
            rel = f"runs/{sid}/{task_id}.bin.gz"
            size = write_playback(PLAYBACK / rel, header, ints)
            shipped[task_id] = {"file": rel, "bytes": size, "objective": record["metrics"]["tool_track_rms_mm"],
                                "pass": all(record["gates"].get(gate) is True for gate in gates.GATES)}
        code = card.get("code", {})
        solution_rows.append({
            "id": sid, "parent": meta.get("parent"), "change": meta.get("change", ""), "tags": meta.get("tags", []),
            "objective": card["objective"], "admissible": card["admissible"], "gate_pass_rate": card["gate_pass_rate"],
            "scored": {"commit": code.get("repo_commit"), "dirty": code.get("repo_dirty"), "evaluated": card.get("evaluated"),
                       "solution_sha256": code.get("solution_sha256"),
                       "robot_controllers": {k: code.get("robot_controllers", {}).get(k) for k in ("version", "commit")},
                       "robot_msgs": {k: code.get("robot_msgs", {}).get(k) for k in ("version", "commit")}},
            "tasks": shipped,
        })

    index = {
        "schema": INDEX_SCHEMA,
        "rule": {key: rule[key] for key in ("text", "representative_tasks", "full", "excluded", "count")},
        "codec": {"magic": MAGIC.decode(), "steps": STEP,
                  "doc": "gzip(magic + uint32 LE header length + header JSON + arrays). Each array: integers, each column "
                         "contiguous, first difference along time, narrowest signed int, bytes in planes (low first); "
                         "value = (cumsum + the task file's integers of `base`) x step. `missing`: rows with no measurement."},
        "deployment": {**constants, "saturation_fraction": metrics.SATURATION_FRACTION,
                       "velocity_allowance": metrics.VELOCITY_LIMIT_ALLOWANCE, "hold_window_s": metrics.HOLD_WINDOW_S,
                       "plant_rate_hz": float(dep.board.rate_hz), "host_rate_hz": dep.host_rate_hz, "record_rate_hz": 100.0,
                       "thresholds": {gate: list(gates.THRESHOLDS[gate]) for gate in gates.GATES}},
        "geoms": poses.geoms(),
        "point_names": poses.point_names(),
        "tasks": task_rows,
        "solutions": solution_rows,
        "check_worst_mm": worst,
    }
    index["bytes"] = sum(row["bytes"] for row in task_rows) + sum(
        task["bytes"] for row in solution_rows for task in row["tasks"].values())
    (PLAYBACK / "index.json").write_text(json.dumps(index, indent=1, allow_nan=False) + "\n")
    return index


def mirror_sources(index: dict[str, Any]) -> list[str]:
    """site/data/solutions/<id>/solution.py: byte copies of every shipped solution's code (the page's code view)."""
    if SOURCES.exists():
        shutil.rmtree(SOURCES)
    out = []
    for row in index["solutions"]:
        source = REPO / "solutions" / row["id"] / "solution.py"
        target = SOURCES / row["id"] / "solution.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        out.append(target.relative_to(SITE).as_posix())
    return out


# ── page data ──────────────────────────────────────────────────────────────────────────────────────────────

ROBOT_MSGS_TYPES = (  # the vocabulary the black box speaks, in the order the page lists it
    "JointTrajectory", "JointState", "JointController", "ServoCommand", "ServoState", "Header",
)


def _objectives_block() -> str:
    text = (REPO / "OBJECTIVES.md").read_text()
    match = re.search(r"## 1\. The black box\s+```python\n(.*?)```", text, re.S)
    return match.group(1).rstrip() if match else ""


def _robot_msgs_types() -> list[dict[str, Any]]:
    """Each type's source lines in robot_msgs at its committed HEAD (found by `class <Name>`)."""
    repo = ROBOT_MSGS_REPO.resolve()
    commit = _git(repo, "rev-parse", "HEAD").strip()
    sources = sorted((repo / "src" / "robot_msgs").rglob("*.py"))
    out = []
    for name in ROBOT_MSGS_TYPES:
        for path in sources:
            lines = path.read_text().splitlines()
            start = next((i for i, line in enumerate(lines) if re.match(rf"class {name}\b", line)), None)
            if start is not None:
                break
        else:
            raise SystemExit(f"robot_msgs has no class {name}")
        end = start + 1
        while end < len(lines) and (not lines[end].strip() or lines[end].startswith((" ", "\t", ")"))):
            end += 1
        while end > start and not lines[end - 1].strip():
            end -= 1
        decorator = start
        while decorator > 0 and lines[decorator - 1].startswith("@"):
            decorator -= 1
        rel = path.relative_to(repo)
        module = ".".join(path.relative_to(repo / "src").with_suffix("").parts)
        doc = re.search(r'"""(.*?)(?:\n\s*\n|""")', "\n".join(lines[start:end]), re.S)
        fields = [line.strip().removesuffix(": ...").removesuffix(":") for line in lines[start + 1:end]
                  if re.match(r"\s{4}([a-z_]\w*:\s|def [a-z]\w*\()", line)]
        out.append({
            "name": name, "module": module,
            "url": f"{GITHUB}/robot_msgs/blob/{commit}/{rel.as_posix()}#L{decorator + 1}-L{end}",
            "lines": [decorator + 1, end],
            "summary": " ".join(doc.group(1).split()) if doc else "",
            "fields": fields[:14],
        })
    return out


def leaderboard() -> dict[str, Any]:
    """Every scored solution not tagged `ablation`, from its scorecard, in OBJECTIVES §4's ranking."""
    rows, excluded = [], []
    for card_path in sorted((REPO / "solutions").glob("*/scorecard.json")):
        card = json.loads(card_path.read_text())
        meta = _meta(card_path.parent.name)
        if EXCLUDED_TAG in meta.get("tags", []):
            excluded.append(card_path.parent.name)
            continue
        rows.append({
            "id": card_path.parent.name, "parent": meta.get("parent"), "change": meta.get("change", ""),
            "split": card.get("split"), "objective": card.get("objective"), "admissible": card.get("admissible"),
            "gate_pass_rate": card.get("gate_pass_rate"),
            "failed_gates": card.get("failed_gates", {}), "diagnostics": card.get("diagnostics", {}),
        })
    rows.sort(key=lambda row: (_rank_key(row), row["id"]))
    best = next((row["id"] for row in rows if row["admissible"]), None)
    return {"rows": rows, "best": best, "scored": bool(rows), "excluded": {EXCLUDED_TAG: excluded},
            "progress_svg": (SITE / "progress.svg").exists()}


def page_data() -> dict[str, Any]:
    board = leaderboard()
    status_path = REPO / "status.json"
    best = board["best"]
    source = REPO / "solutions" / best / "solution.py" if best else None
    return {
        # only the KPI and the queue's top: status.json's links name local paths that must not reach a public page
        "status": {key: json.loads(status_path.read_text()).get(key) for key in ("kpi", "counter_kpi", "todo")}
        if status_path.exists() else None,
        "objectives_block": _objectives_block(),
        "robot_msgs": _robot_msgs_types(),
        "leaderboard": board,
        "best_solution": {"id": best, "path": f"solutions/{best}/solution.py", "code": source.read_text()}
        if source and source.exists() else None,
    }


def site_bytes() -> int:
    return sum(path.stat().st_size for path in SITE.rglob("*") if path.is_file())


def build() -> dict[str, Any]:
    before = site_bytes()
    # the live runtime this page used to load (Pyodide + MuJoCo WASM, its wheels and the repo mirror): git keeps it
    for retired in (SITE / "wheels", SITE / "runtime", DATA / "repo"):
        if retired.exists():
            shutil.rmtree(retired)
    index = export_playback()
    mirror_sources(index)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "page.json").write_text(json.dumps(page_data(), indent=1, allow_nan=False) + "\n")
    after = site_bytes()
    summary = {"pairs": index["rule"]["count"], "solutions": len(index["solutions"]), "tasks": len(index["tasks"]),
               "playback_bytes": index["bytes"], "site_bytes_before": before, "site_bytes_after": after,
               "check_worst_mm": index["check_worst_mm"], "best": index["rule"]["full"]}
    print(json.dumps(summary, indent=1))
    if after > SIZE_LIMIT_BYTES:
        raise SystemExit(f"site/ is {after / 1e6:.2f} MB, over the {SIZE_LIMIT_BYTES / 2**20:.0f} MiB limit: ship fewer tasks")
    return summary


# ── check: what ships equals the scorecards ─────────────────────────────────────────────────────────────────


def check() -> list[str]:
    """Problems with site/data (empty = pass): the shipped pairs are the rule's on the current ledger, every file listed
    exists and decodes, and every run file's metrics / gates / notes equal its scorecard's per-task row exactly."""
    problems: list[str] = []
    index_path = PLAYBACK / "index.json"
    if not index_path.exists():
        return ["site/data/playback/index.json is missing: run tools/build_site.py build"]
    index = json.loads(index_path.read_text())
    rule = selection()
    shipped = {row["id"]: sorted(row["tasks"]) for row in index["solutions"]}
    wanted = {sid: sorted(tasks) for sid, tasks in rule["pairs"].items()}
    if shipped != wanted:
        added = sorted(set(wanted) - set(shipped))
        removed = sorted(set(shipped) - set(wanted))
        problems.append(f"site/data/playback is stale for the current ledger (new: {added}, gone: {removed}, "
                        f"or a different best): run tools/build_site.py build")
    task_files = {row["id"]: row for row in index["tasks"]}
    bases = {}
    for task_id, row in task_files.items():
        path = PLAYBACK / row["file"]
        if not path.exists():
            problems.append(f"{row['file']} is listed but missing")
            continue
        header, _, ints = read_playback(path)
        if header.get("task") != task_id:
            problems.append(f"{row['file']} holds {header.get('task')}")
        bases[task_id] = (header, ints)
    for row in index["solutions"]:
        card = _scorecard(row["id"])
        if card is None:
            problems.append(f"{row['id']}: shipped but has no scorecard")
            continue
        if row["objective"] != card["objective"] or row["admissible"] != card["admissible"]:
            problems.append(f"{row['id']}: the index's objective / admissible differ from the scorecard")
        if row["scored"]["commit"] != card.get("code", {}).get("repo_commit"):
            problems.append(f"{row['id']}: the index's scored commit differs from the scorecard")
        by_task = {r["task"]: r for r in card["tasks"]}
        for task_id, entry in row["tasks"].items():
            path = PLAYBACK / entry["file"]
            if not path.exists() or task_id not in bases:
                problems.append(f"{entry['file']} is listed but missing (or its task file is)")
                continue
            task_header, task_ints = bases[task_id]
            header, values, _ = read_playback(path, base=task_ints)
            card_row = by_task.get(task_id)
            if card_row is None:
                problems.append(f"{row['id']} {task_id}: no scorecard row")
                continue
            want = {"tool_track_rms_mm": card_row["objective"], **card_row["kpis"], **card_row["diagnostics"]}
            if (header["solution"], header["task"]) != (row["id"], task_id):
                problems.append(f"{entry['file']} holds {header['solution']} {header['task']}")
            if header["metrics"] != want:
                problems.append(f"{entry['file']}: metrics differ from the scorecard's row")
            if header["gates"] != card_row["verdicts"] or header["notes"] != card_row["notes"]:
                problems.append(f"{entry['file']}: gates or notes differ from the scorecard's row")
            if entry["objective"] != card_row["objective"]:
                problems.append(f"{row['id']} {task_id}: the index's objective differs from the scorecard's row")
            rows_ = {spec["shape"][0] for spec in header["arrays"].values()}
            if rows_ != {task_header["samples"]} or header["samples"] != task_header["samples"]:
                problems.append(f"{entry['file']}: {rows_} rows, the task has {task_header['samples']}")
            for name, item in header["explain"]["checks"].items():
                if not item["ok"]:
                    problems.append(f"{entry['file']}: the drawing of {name} disagrees with the ruler")
            for name, item in header["explain"]["subset"].items():
                if item["consistent"] is False:
                    problems.append(f"{entry['file']}: the record's 100 Hz samples contradict the ruler's {name}")
        source = SOURCES / row["id"] / "solution.py"
        if not source.exists() or source.read_bytes() != (REPO / "solutions" / row["id"] / "solution.py").read_bytes():
            problems.append(f"site/data/solutions/{row['id']}/solution.py is not a byte copy of the solution")
    return problems


# ── serving and driving headless Chromium ──────────────────────────────────────────────────────────────────


class Server:
    """`python3 -m http.server` on a free 127.0.0.1 port over site/, stopped by PID on exit (never by port)."""

    def __enter__(self) -> Server:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.process = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(self.port), "--bind", "127.0.0.1", "--directory", str(SITE)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        self.url = f"http://127.0.0.1:{self.port}"
        return self

    def __exit__(self, *_: Any) -> None:
        self.process.send_signal(signal.SIGTERM)
        self.process.wait(timeout=10)


def _browser(playwright: Any) -> Any:
    # WHY swiftshader: headless Chromium has no GPU; WebGL (the 3D view) then renders in software
    return playwright.chromium.launch(headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                                           "--ignore-gpu-blocklist"])


CURSOR = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;left:-40px;top:0;width:18px;height:18px;z-index:2147483647;pointer-events:none';
  c.innerHTML = '<svg width="18" height="18" viewBox="0 0 18 18"><path d="M1 1 L1 15 L5 11 L8 17 L10.5 16 L7.5 10 L13 10 Z" fill="#111" stroke="#fff" stroke-width="1.3"/></svg>';
  document.body.appendChild(c);
  window.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
});
"""
CARD_IDS = ("tool_track_rms_mm", "completed", "stop_error_max_mm", "saturation_share_pct", "limit_violations",
            "floor_clearance")
RUNTIME_URL = re.compile(r"pyodide|@mujoco/mujoco|mujoco\.(js|wasm)|\.whl\b|/runtime/", re.I)


def _wait_run(page: Any, timeout_s: float = 60.0) -> dict[str, Any]:
    page.wait_for_function("window.__page && window.__page.run && !window.__page.busy", timeout=timeout_s * 1e3)
    return page.evaluate("({solution: window.__page.run.solution, task: window.__page.run.task, "
                         "metrics: window.__page.run.metrics, gates: window.__page.run.gates})")


def _pause_at(page: Any, t: float) -> None:
    page.evaluate("""(t) => { if (window.__page.playing) document.getElementById('play').click();
      const s = document.getElementById('scrub'); s.value = t; s.dispatchEvent(new Event('input')); }""", t)
    page.wait_for_timeout(300)


def _fingerprint(page: Any) -> dict[str, str]:
    # what a click changes: the 3D canvas pixels and the explanation plot's SVG, hashed in the page
    return page.evaluate("""async () => {
      const digest = async (text) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',
        new TextEncoder().encode(text)))).map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
      const canvas = document.querySelector('#viewer canvas');
      return {canvas: await digest(canvas.toDataURL()), plot: await digest(document.getElementById('explain-plot').innerHTML),
              title: document.getElementById('explain-title').textContent};
    }""")


def _cards_match(shown: dict[str, str], metrics_: dict[str, Any]) -> bool:
    """Each card's text is the record's own value, as the page formats it (3 significant digits, or an integer / yes-no)."""
    values = {**metrics_, "floor_clearance": metrics_.get("floor_clearance_violations")}
    for card, text in shown.items():
        value = values.get(card)
        number = text.split()[0] if text else ""
        if isinstance(value, bool):
            ok = number == ("yes" if value else "no")
        elif isinstance(value, int):
            ok = number == str(value)
        else:
            ok = value is not None and math.isclose(float(number), float(f"{value:.3g}"), rel_tol=1e-9)
        if not ok:
            print(f"card {card}: shows {text!r}, the record has {value!r}")
            return False
    return True


def _decoder_agrees(page: Any) -> dict[str, Any]:
    """The page's JavaScript decoder vs read_playback on the run it shows: every decoded array, max |difference|."""
    import numpy as np

    run = page.evaluate("""() => { const r = window.__page.run; return {solution: r.solution, task: r.task,
      q: r.q, qd: r.qd, tau: r.tau, tool: r.tool, error_mm: r.error_mm, lowest: r.lowest, t: r.t,
      measured_pos: r.frames.measured.pos, measured_quat: r.frames.measured.quat,
      target_pos: r.frames.target.pos, target_quat: r.frames.target.quat}; }""")
    index = json.loads((PLAYBACK / "index.json").read_text())
    entry = next(row for row in index["solutions"] if row["id"] == run["solution"])["tasks"][run["task"]]
    _, task_values, task_ints = read_playback(PLAYBACK / f"tasks/{run['task']}.bin.gz")
    _, values, _ = read_playback(PLAYBACK / entry["file"], base=task_ints)
    pairs = {"t": task_values["t"], "q": values["q"], "qd": values["qd"], "tau": values["tau"], "tool": values["tool"],
             "error_mm": values["error_mm"], "lowest": values["lowest"], "measured_pos": values["geom_pos"],
             "measured_quat": values["geom_quat"], "target_pos": task_values["geom_pos"], "target_quat": task_values["geom_quat"]}
    diffs = {name: float(np.max(np.abs(np.asarray(run[name], dtype=float) - array))) for name, array in pairs.items()}
    return {"pair": [run["solution"], run["task"]], "max_abs_diff": diffs, "agree": all(v <= 1e-12 for v in diffs.values())}


def shoot() -> dict[str, Any]:
    """Headless checks and media (outputs/site/): load time to the first playable frame, no runtime requests, the cards
    show the record's numbers and each click changes both views, every shipped picker option plays, the JS decoder equals
    the Python one; screenshots light / dark / 390 px phone; the hero video."""
    from playwright.sync_api import sync_playwright

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"cards": {}, "checks": {}}
    index = json.loads((PLAYBACK / "index.json").read_text())
    with Server() as server, sync_playwright() as playwright:
        browser = _browser(playwright)

        # 1. desktop, light: the default (the best solution on the cube), every card clicked
        page = browser.new_page(viewport={"width": 1280, "height": 860}, color_scheme="light")
        errors: list[str] = []
        requests: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        started = time.time()
        page.goto(f"{server.url}/index.html")
        page.wait_for_function("window.__page && window.__page.firstFrameMs", timeout=60e3)
        report["first_frame_s"] = round(time.time() - started, 2)
        report["first_frame_ms_in_page"] = round(page.evaluate("window.__page.firstFrameMs"))
        run = _wait_run(page)
        report["default"] = [run["solution"], run["task"]]
        _pause_at(page, 2.2)
        page.screenshot(path=str(OUTPUTS / "page-light.png"))
        shown = page.evaluate("[...document.querySelectorAll('.card')].map((c) => [c.dataset.id, c.querySelector('.value').textContent])")
        report["checks"]["cards_show_the_record"] = _cards_match(dict(shown), run["metrics"])
        decoder = _decoder_agrees(page)
        report["decoder"] = decoder
        report["checks"]["js_decoder_equals_python"] = decoder["agree"]
        previous = _fingerprint(page)
        for card in (*CARD_IDS[1:], CARD_IDS[0]):  # start away from the default, end back on it
            page.click(f".card[data-id='{card}']")
            page.wait_for_timeout(500)
            now = _fingerprint(page)
            report["cards"][card] = {"canvas_changed": now["canvas"] != previous["canvas"],
                                     "plot_changed": now["plot"] != previous["plot"], "title": now["title"]}
            previous = now
            # WHY scroll first: an element screenshot scrolls it just into view, under the sticky header
            page.evaluate("window.scrollTo(0, 0)")
            page.locator("#viewer").screenshot(path=str(OUTPUTS / f"card-{card}-3d.png"))
            page.evaluate("document.getElementById('explain').scrollIntoView({block: 'center'})")
            page.locator("#explain").screenshot(path=str(OUTPUTS / f"card-{card}-2d.png"))
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(OUTPUTS / "page-light-full.png"), full_page=True)

        # 2. every picker option: each shipped (solution, task) plays and shows its record's objective
        options = page.evaluate("[...document.getElementById('solution').options].map((o) => o.value)")
        report["checks"]["solution_picker_is_the_index"] = options == [row["id"] for row in index["solutions"]]
        played, failures = 0, []
        for row in index["solutions"]:
            page.select_option("#solution", row["id"])
            tasks = page.evaluate("[...document.getElementById('task').options].map((o) => o.value)")
            if sorted(tasks) != sorted(row["tasks"]):
                failures.append(f"{row['id']}: the task picker shows {len(tasks)} tasks, {len(row['tasks'])} ship")
            for task_id in tasks:
                page.select_option("#task", task_id)
                got = _wait_run(page)
                played += 1
                want = row["tasks"].get(task_id, {}).get("objective")
                if (got["solution"], got["task"]) != (row["id"], task_id) or got["metrics"]["tool_track_rms_mm"] != want:
                    failures.append(f"{row['id']} {task_id}: shows {got['solution']} {got['task']}")
                card = page.evaluate("document.querySelector('.card[data-id=tool_track_rms_mm] .value').textContent")
                if not _cards_match({"tool_track_rms_mm": card}, got["metrics"]):
                    failures.append(f"{row['id']} {task_id}: card {card!r}")
        report["options"] = {"played": played, "shipped": index["rule"]["count"], "failures": failures[:20]}
        report["checks"]["every_option_plays"] = not failures and played == index["rule"]["count"]
        report["page_errors"] = errors
        report["requests"] = {"count": len(requests), "hosts": sorted({u.split('/')[2] for u in requests}),
                              "runtime": [u for u in requests if RUNTIME_URL.search(u)]}
        report["checks"]["no_runtime_requests"] = not report["requests"]["runtime"]
        page.close()

        # 3. dark and phone width
        for name, viewport, scheme in (("page-dark", {"width": 1280, "height": 860}, "dark"),
                                       ("page-phone", {"width": 390, "height": 844}, "light")):
            page = browser.new_page(viewport=viewport, color_scheme=scheme)
            page.on("pageerror", lambda error: errors.append(str(error)))
            gen0 = index["rule"]["full"]["gen0_best"] or index["solutions"][0]["id"]
            page.goto(f"{server.url}/index.html?solution={gen0}&task=workspace-dev-001")
            _wait_run(page)
            _pause_at(page, 2.2)
            page.screenshot(path=str(OUTPUTS / f"{name}.png"))
            page.screenshot(path=str(OUTPUTS / f"{name}-full.png"), full_page=True)
            report["checks"][f"{name}_no_horizontal_scroll"] = page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth")
            page.close()

        # 4. the hero video: load -> it plays -> click three scores -> their 3D explanations
        video_dir = Path(tempfile.mkdtemp(dir=OUTPUTS))
        context = browser.new_context(viewport={"width": 1280, "height": 1000}, color_scheme="light",
                                      record_video_dir=str(video_dir), record_video_size={"width": 1280, "height": 1000})
        context.add_init_script(CURSOR)
        recording = time.monotonic()
        page = context.new_page()
        # WHY trim to the navigation: the recording starts with the context, a blank page until goto
        start_s = max(0.0, time.monotonic() - recording - 0.1)
        page.goto(f"{server.url}/index.html")
        page.mouse.move(1000, 480)
        _wait_run(page)
        report["hero_loaded_at_s"] = round(time.monotonic() - recording - start_s, 2)
        page.wait_for_timeout(2500)
        page.evaluate("window.scrollTo({top: 300, behavior: 'smooth'})")
        page.wait_for_timeout(900)
        for card in ("stop_error_max_mm", "saturation_share_pct", "floor_clearance"):
            box = page.locator(f".card[data-id='{card}']").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(2500)
        raw = Path(page.video.path())
        context.close()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start_s:.2f}", "-i", str(raw), "-vf", "scale=1280:-2", "-an",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(OUTPUTS / "hero.mp4")], check=True)
        shutil.rmtree(video_dir, ignore_errors=True)
        browser.close()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                            str(OUTPUTS / "hero.mp4")], capture_output=True, text=True)
    report["hero_mp4_s"] = float(probe.stdout.strip() or "nan")
    report["page_errors"] = errors
    report["pass"] = (all(report["checks"].values())
                      and all(card["canvas_changed"] and card["plot_changed"] for card in report["cards"].values())
                      and not errors)
    (OUTPUTS / "shoot.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("build", "check", "shoot"))
    args = parser.parse_args(argv)
    if args.command == "build":
        build()
        problems = check()
        print("\n".join(problems) or "check: PASS")
        return 1 if problems else 0
    if args.command == "check":
        problems = check()
        print("\n".join(problems) or "check: PASS")
        return 1 if problems else 0
    report = shoot()
    print(json.dumps({key: report[key] for key in ("checks", "cards", "pass", "hero_mp4_s", "first_frame_s", "options",
                                                   "requests")}, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
