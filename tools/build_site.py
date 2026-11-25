"""Build the landing page's data (site/data/) from saved run records, check it, and shoot its media.

    uv run --all-extras python tools/build_site.py build     # site/data/runs/ (bb-run/1 records) + state.json + page.json
    uv run --all-extras python tools/build_site.py check     # every shipped number equals its scorecard row
    uv run --all-extras --with playwright==1.64.1 python tools/build_site.py parity  # headless: every saved run, on the built page
    uv run --all-extras --with playwright==1.64.1 python tools/build_site.py shoot   # headless screenshots + hero video

The page plays back saved runs; nothing is simulated or scored in the browser (Zach, 2026-11-24: "You can just
playback saved runs"). `tta evaluate <id>` already writes one run record per task (`outputs/runs/<id>/dev/<task>.json`,
gitignored: the target, the measured joints and torques, the tool points, and the ruler's own `metrics` / `gates`).
`build` turns the shipped ones into what the page's `<bb-evidence>` plays (the blackbox_agent viewer's metric explainer,
its CONTRACT §4 and §14):

- **Which runs ship** (`selection()`, the rule in site/README.md): from `ledger.jsonl`, every scored solution not tagged
  `ablation` on one representative dev task per task kind (the first of each kind in dataset order), plus the best
  admissible solution and the best generation-0 one on all 42 dev tasks. A missing or stale record (its numbers differ
  from the scorecard's) stops the build with the `tta evaluate` command that rewrites it; records are never edited.
- **What the page draws is computed here, natively**: the arm's geom poses per frame from the deployment's own model
  and `mj_kinematics` (checked against `deployment.link_points`), the tool error from `metrics.tool_errors_m`, the stops
  from `metrics.stop_errors_mm`, the lowest moving point from `deployment.link_points`. The browser does no kinematics.
- **The box's export** (CONTRACT §14: "a box's export writes" bb-run/1 records and lists them in `state.playback.runs`):
  those arrays go into a compact binary export (`outputs/site/playback/`, an intermediate), which the viewer's own
  `tools/fold_runs.py` (`tta_record`, called where it lives, like the state fold) turns into one bb-run/1 record per run
  (`site/data/runs/<solution>/<task>.json`); `state.json` lists them in its `playback` slice.
- **The numbers on the cards are the record's own** `metrics` / `gates` (computed by the ruler when the run was
  scored), at the fold's stated rounding; `check` proves each equals its scorecard's per-task row.

The page itself is blackbox_agent's stock landing (its hero plays `state.playback.runs` with `<bb-evidence>`) and
dashboard, written with this repo's site/ by `blackbox build` (CI: .github/workflows/pages.yml). `parity` and `shoot`
build HEAD that way (outputs/site/built/) and drive headless Chromium through Playwright (its cached browser; never a
visible window) over a server on 127.0.0.1 they start and stop themselves.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
DATA = SITE / "data"
SOURCES = DATA / "solutions"
RUNS = REPO / "outputs" / "runs"
LEDGER = REPO / "ledger.jsonl"
OUTPUTS = REPO / "outputs" / "site"
# WHY an intermediate (2026-11-24, lane EV): the page plays bb-run/1 records now (site/data/runs/); the compact binary
# export is what the viewer's fold reads to write them, so it stays out of site/ (it shipped as site/data/playback/
# until then; git history keeps it, and the viewer's own scenario pins a commit that has it)
PLAYBACK = OUTPUTS / "playback"
RECORDS = DATA / "runs"
DATASET_REL = Path("datasets/ur5e_alone/workspace/v2")
GITHUB = "https://github.com/zacharyyamaoka"
REPO_URL = f"{GITHUB}/trajectory_tracking_agent"
ROBOT_MSGS_REPO = REPO / ".." / "robot_msgs"

EXCLUDED_TAG = "ablation"  # ablation solutions test which parts matter; they are not search progress (coordinator, 11-24)
GEN0_TAG = "gen-0"
MAGIC = b"TTAPLAY1"
PLAYBACK_SCHEMA = "tta.playback/1"
INDEX_SCHEMA = "tta.playback_index/1"
# WHY GitHub's own limits, not a picked budget (Zach 2026-11-24: a cap is his ask or a cited limit): a visitor loads one
# page and the run it picks, never the whole site, so the only hard ceilings are GitHub's. "Published GitHub Pages
# sites may be no larger than 1 GB" (docs.github.com/en/pages/getting-started-with-github-pages/about-github-pages
# #usage-limits); "GitHub blocks files larger than 100 MiB" (docs.github.com/en/repositories/working-with-files/
# managing-large-files/about-large-files-on-github). The 15 MiB budget it replaces dated from the Pyodide page, which
# downloaded the whole runtime on load.
SIZE_LIMIT_BYTES = 1_000_000_000  # all of site/, on disk (Pages counts the published files)
FILE_LIMIT_BYTES = 100 * 1024 * 1024  # any one file
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
    """The binary export (PLAYBACK, an intermediate): one file per shipped task (the target) and per shipped
    (solution, task) (the run), and its index. Refuses on a missing or stale record."""
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
                                "pass": all(record["gates"].get(gate) is True for gate in gates.GATES),
                                "checks": explain["checks"], "subset": explain["subset"]}
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


# ── the box's export: bb-run/1 records (the blackbox_agent viewer's CONTRACT §4, §14) ─────────────────────────

# WHY the viewer's fold, called where it lives (like fold_state.py below): `tta_record` is the one place that turns this
# box's saved runs into bb-run/1 (viewer/tools/fold_runs.py, stdlib only); a second copy here would drift from it.
# BB_FOLD_RUNS overrides the path; the tests validate the records against the schema beside it.
FOLD_RUNS = Path(os.environ.get("BB_FOLD_RUNS", Path.home() / "blackbox_agent" / "viewer" / "tools" / "fold_runs.py"))
RUN_RECORD_SCHEMA = FOLD_RUNS.parent.parent / "schemas" / "run-record.schema.json"
RUNS_INDEX_SCHEMA = "tta.runs/1"

# Display resolution, never a score: every number on a card is the record's metric. WHY (2026-11-24, lane EV): the fold
# writes the arm's poses at all 100 Hz samples to 10 um, 76 MB of JSON for the 244 shipped runs. Drawing the arm at
# 25 Hz (bb-run/1's own `layer.t`) to 1 mm keeps every evidence channel at the record's 100 Hz, so "which samples
# count" stays the ruler's own count; the frame at each metric's peak is kept too, so a paused peak shows the arm there.
GEOMETRY_STRIDE = 4  # 100 Hz / 4: the drawn arm at 25 Hz
POSE_DIGITS = 3  # 1 mm (under a pixel on the drawn arm), and 1e-3 of a quaternion component (~0.1 deg)
# a channel the fold writes -> its decimals here; absent = the fold's own rounding
CHANNEL_DIGITS = {
    "q": 4, "q_target": 4,  # deg: 1e-4 deg, so the page's measured - target per joint resolves the best's 0.01 deg errors
    "tool_error": 4,  # mm: 0.1 um
    "tool_target": 6, "tool": 6,  # m: 1 um (the whiskers draw errors of tens of um and up, magnified and labelled)
    "tau_pct": 1, "qd_pct": 1,  # % of a cap or limit
    "torque_peak": 2, "speed_peak": 2,  # % (the gates' lines sit at 98 % and 105 %)
    "clearance": 1,  # mm
    "joint_error": 4,  # deg
    "power": 2,  # W
}
# the fold's rounding of a metric's value (fold_runs.tta_record): `check` holds the record to the scorecard at it
METRIC_DIGITS = {"tool_track_rms_mm": 6, "stop_error_max_mm": 6, "saturation_share_pct": 5, "joint_track_rms_deg": 5,
                 "tool_lag_ms": 4, "energy_j": 4}
METRIC_KEY = {"floor_clearance": "floor_clearance_violations"}  # a record's metric id -> the scorecard row's key


def fold_runs() -> Any:
    """The viewer's run-record fold, imported from where it lives."""
    if not FOLD_RUNS.exists():
        raise SystemExit(f"{FOLD_RUNS} not found: the bb-run/1 fold lives in the blackbox_agent viewer (set BB_FOLD_RUNS)")
    spec = importlib.util.spec_from_file_location("bb_fold_runs", FOLD_RUNS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Export:
    """What `tta_record` reads through (it takes a repo at a git ref, fold_runs.Repo): this build's binary export, by the
    path the box published it under until 2026-11-24 (site/data/playback/). `where` names the true source, the run
    record `tta evaluate` saved, at the commit that scored it."""

    name = "trajectory_tracking_agent"
    ref = "build"

    def __init__(self, scored: dict[str, str | None]) -> None:
        self.scored = scored  # solution id -> the commit its scorecard names
        self.read: list[str] = []

    def bytes(self, path: str) -> bytes:
        rel = path.removeprefix("site/data/playback/")
        self.read.append(rel)
        return (PLAYBACK / rel).read_bytes()

    def json(self, path: str) -> Any:
        return json.loads(self.bytes(path))

    def where(self, path: str) -> str:
        parts = path.removeprefix("site/data/playback/").removesuffix(".bin.gz").split("/")
        if parts[0] == "tasks":
            return f"{self.name}:{DATASET_REL.as_posix()}/tapes/{parts[1]}.npz (the target)"
        commit = (self.scored.get(parts[1]) or "?")[:7]
        return f"{self.name}@{commit}:outputs/runs/{parts[1]}/dev/{parts[2]}.json (tta evaluate's run record)"


def _compact(record: dict[str, Any], fold: Any) -> dict[str, Any]:
    """The fold's record at display resolution (GEOMETRY_STRIDE, POSE_DIGITS, CHANNEL_DIGITS); nothing else changes."""
    import bisect

    t = record["time"]["t"]
    keep = set(range(0, len(t), GEOMETRY_STRIDE)) | {len(t) - 1}
    for metric in record["metrics"]:
        peak = (metric.get("evidence") or {}).get("peak")
        if peak:  # the frame a paused peak shows: the last sample at or before it (the scene's frameIndex)
            keep.add(peak["i"] if "i" in peak else max(0, bisect.bisect_right(t, peak["t"] + 1e-9) - 1))
    frames = sorted(keep)
    for layer in record["scene"]["geometry"]["layers"]:
        layer["t"] = [t[i] for i in frames]
        layer["poses"] = [fold.rnd(layer["poses"][i], POSE_DIGITS) for i in frames]
    for channel in record["channels"]:
        if channel["id"] in CHANNEL_DIGITS:
            channel["values"] = fold.rnd(channel["values"], CHANNEL_DIGITS[channel["id"]])
    return record


def _label(row: dict[str, Any], best: str | None, gen0: str | None) -> str:
    """The run's subject.label: what its solution is in the population (the header line under the verdict)."""
    objective = row.get("objective")
    score = f"{objective:.3g} mm median on dev" if isinstance(objective, (int, float)) and math.isfinite(objective) else "no score"
    role = ("best admissible" if row["id"] == best else "best of generation 0" if row["id"] == gen0
            else "admissible" if row["admissible"] else "not admissible on dev")
    return f"{role}, {score}"


def export_records(index: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """site/data/runs/: one bb-run/1 record per shipped run (the viewer's `tta_record` over the binary export) and the
    pickers' index; returns (that index, state.json's `playback` slice listing every record)."""
    fold = fold_runs()
    rule = index["rule"]
    best, gen0 = rule["full"]["best"], rule["full"]["gen0_best"]
    export = _Export({row["id"]: row["scored"]["commit"] for row in index["solutions"]})
    if RECORDS.exists():
        shutil.rmtree(RECORDS)
    solutions, listed, left_out = [], [], []
    for row in index["solutions"]:
        label = _label(row, best, gen0)
        shipped = {}
        for task_id, entry in row["tasks"].items():
            try:
                record = fold.tta_record(export, index, row["id"], task_id, label)
            except ValueError as error:  # the fold refuses a run with unmeasured rows (a crash): named, never hidden
                left_out.append({"solution": row["id"], "task": task_id, "why": str(error)})
                continue
            rel = f"runs/{row['id']}/{task_id}.json"
            text = fold.dump(_compact(record, fold))
            (DATA / rel).parent.mkdir(parents=True, exist_ok=True)
            (DATA / rel).write_text(text)
            shipped[task_id] = {"record": rel, "bytes": len(text.encode()), "objective": entry["objective"],
                                "pass": entry["pass"], "checks": entry["checks"], "subset": entry["subset"]}
            listed.append({"solution": row["id"], "task": task_id, "split": "dev", "path": rel, "schema": "bb-run/1",
                           "label": label})
        if shipped:
            solutions.append({**{key: row[key] for key in ("id", "parent", "change", "tags", "objective", "admissible",
                                                           "gate_pass_rate", "scored")}, "tasks": shipped})
    runs_index = {
        "schema": RUNS_INDEX_SCHEMA,
        "what": "The page's pickers: every shipped run's bb-run/1 record (relative to site/data/, listed in "
                "state.json's playback slice), its objective, whether it passed every gate, and the build's honesty "
                "checks on its saved samples. tools/build_site.py writes it; site/README.md states the rule.",
        "rule": {**rule, "count": sum(len(row["tasks"]) for row in solutions)},
        "made_by": {"export": "tools/build_site.py", "fold": "blackbox_agent viewer/tools/fold_runs.py tta_record",
                    "display": {"geometry_hz": 100.0 / GEOMETRY_STRIDE, "pose_digits": POSE_DIGITS,
                                "channel_digits": CHANNEL_DIGITS}},
        "tasks": [{key: row[key] for key in ("id", "kind", "duration_s", "samples")} for row in index["tasks"]],
        "solutions": solutions,
        "left_out": left_out,
        "bytes": sum(task["bytes"] for row in solutions for task in row["tasks"].values()),
        "check_worst_mm": index["check_worst_mm"],
    }
    (RECORDS / "index.json").write_text(json.dumps(runs_index, indent=1, allow_nan=False) + "\n")
    playback = {"runs": listed, "scene": None, "index": "runs/index.json",
                "rule": rule["text"] + (f" Left out: {len(left_out)} runs the fold refused (runs/index.json)." if left_out else "")}
    return runs_index, playback


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


# WHY served bytes (2026-11-24, lane EV): GitHub Pages gzips text on the wire (measured that day: data/state.json,
# 678,500 B on disk, arrived as 87,077 B with content-encoding: gzip) and git stores blobs compressed, so what a page
# weighs to a visitor and to the repo is its compressed size. gzip level 4 overstates that measurement by 4 %, so the
# budget errs on the heavy side. Files already compressed (images, video, .gz) count as they are.
COMPRESSED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".gz", ".woff", ".woff2"}


def served_bytes(path: Path) -> int:
    data = path.read_bytes()
    return len(data) if path.suffix.lower() in COMPRESSED_SUFFIXES else len(gzip.compress(data, compresslevel=4, mtime=0))


def site_bytes(served: bool = True) -> int:
    """All of site/: as served (the budget) or as stored on disk."""
    files = [path for path in SITE.rglob("*") if path.is_file()]
    return sum(served_bytes(path) if served else path.stat().st_size for path in files)


# WHY the package's fold (2026-11-25, lane PKG): the headliner and every tab read a bb-state/1 state.json, blackbox_agent's
# fold of this repo. CI folds every pushed commit with the same package (.github/workflows/pages.yml calls its
# site.yml@v0: `blackbox build`), so the local build runs that package's fold too (the `site` extra installs it at the
# commit uv.lock pins): one fold, the same bytes for the same commit. BB_FOLD overrides the path. Without a fold the
# committed state.json stays and tests/test_site_headliner.py catches it going stale.


def _package_fold() -> Path:
    try:
        from blackbox_agent.site import FOLD as package_fold
    except ImportError:
        return Path("blackbox_agent/fold/fold_state.py")  # not installed: write_state warns and keeps the committed state
    return Path(package_fold)


FOLD = Path(os.environ["BB_FOLD"]) if os.environ.get("BB_FOLD") else _package_fold()
# The test run the Spec page reads, committed with site/data: CI cannot run the tests (the deps are local path deps),
# so it folds this file. It is public (site/), so it is written by public_junit().
JUNIT = DATA / "junit.xml"
# One test run per commit (<sha7>.xml.gz), for the Spec page's History (the viewer's spec_history slice, its CONTRACT
# §16.8): the fold never runs a test, so the history is the runs committed with each commit. Seeded 2026-11-24 (lane SHIP)
# from blackbox_agent's viewer/scenarios/junit/tta/ (the suite on a git archive of each commit, lane G), made public by
# public_junit(); kept current by archive_junit() (each build archives the run committed with HEAD) and by CI
# (`blackbox build` adds the pushed commit's own run to the built site). ~7 kB a commit, gzipped.
JUNIT_DIR = DATA / "junit"


def write_state(playback: dict[str, Any]) -> None:
    """site/data/state.json: the viewer's fold of this repo at HEAD, plus the `playback` slice this build's export
    writes (CONTRACT §4: the export lists its bb-run/1 records there)."""
    path = DATA / "state.json"
    if FOLD.exists():
        cmd = [sys.executable, str(FOLD), "--repo", str(REPO), "--ref", "HEAD", "--out", str(path)]
        archive_junit()
        if JUNIT_DIR.is_dir():
            cmd += ["--junit-dir", JUNIT_DIR.relative_to(REPO).as_posix()]
        if test_run(JUNIT):
            # relative to the repo, run from it, as `blackbox build` hands them (site/data/junit.xml): the string lands in
            # state.json, so an absolute path would put a local directory on the public page
            cmd += ["--junit", JUNIT.relative_to(REPO).as_posix()]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, cwd=REPO)
    else:
        print(f"warning: {FOLD} not found: site/data/state.json not re-folded (its playback slice is)", file=sys.stderr)
    state = json.loads(path.read_text())
    out: dict[str, Any] = {}
    for key, value in state.items():  # the slice goes before `source` (provenance last, as the fold orders them)
        if key == "playback":
            continue
        if key == "source":
            out["playback"] = playback
        out[key] = value
    out.setdefault("playback", playback)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


def archive_junit() -> str | None:
    """HEAD's own run into site/data/junit/<sha7>.xml.gz: the junit.xml committed with HEAD (the run committed with a
    commit is that commit's run), public as committed. None when HEAD has no committed run or it is already there."""
    if not JUNIT_DIR.is_dir():
        return None
    head = _git(REPO, "rev-parse", "HEAD").strip()[:7]
    out = JUNIT_DIR / f"{head}.xml.gz"
    if out.exists() or (JUNIT_DIR / f"{head}.xml").exists():
        return None
    shown = subprocess.run(["git", "-C", str(REPO), "show", "HEAD:site/data/junit.xml"], capture_output=True, text=True)
    if shown.returncode != 0:
        return None
    out.write_bytes(gzip.compress(public_junit(shown.stdout).encode(), mtime=0))
    return out.name


def test_run(out: Path) -> bool:
    """site/data/junit.xml: a junit XML of this tree's test run, for the Spec page's pass/fail per requirement (the fold
    never runs a test), written by public_junit(). No run: the file is removed, so a stale run never reads as this
    tree's (the Spec page then shows 'not run', locally and in CI alike).
    WHY: tests/test_site_* are left out: they check the very site/data this build is writing, so they are red mid-build
    by construction; no spec cites them."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "junit.xml"
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={raw}",
                              "--ignore-glob=tests/test_site_*"], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not raw.exists():
            out.unlink(missing_ok=True)
            print(f"warning: no test run (pytest exit {run.returncode}): the Spec page shows 'not run'", file=sys.stderr)
            return False
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(public_junit(raw.read_text()))
    return True


def _relative(text: str) -> str:
    # WHY the temp dir too: a failing test's message can name its tmp_path (/tmp/pytest-of-<user>/...)
    return (text.replace(f"{REPO}/", "").replace(str(REPO), ".").replace(str(Path.home()), "~")
            .replace(tempfile.gettempdir(), "<tmp>"))


def public_junit(text: str) -> str:
    """A junit XML as it is published (site/ is public): pytest's `hostname` dropped and every path relative (this
    repo's root removed, the home directory written ~, the temp dir <tmp>), in attributes and text alike. Nothing the
    fold reads changes: each testcase's classname and name, its failure / error / skipped tags, and the suite's counts
    and timestamp."""
    root = ET.fromstring(text)
    for element in root.iter():
        element.attrib.pop("hostname", None)
        for key, value in list(element.attrib.items()):
            element.set(key, _relative(value))
        if element.text:
            element.text = _relative(element.text)
        if element.tail:
            element.tail = _relative(element.tail)
    return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(root, encoding="unicode") + "\n"


def build() -> dict[str, Any]:
    before = {"served": site_bytes(), "on_disk": site_bytes(served=False)}
    # retired: the live runtime this page used to load (Pyodide + MuJoCo WASM, its wheels and the repo mirror) and the
    # binary playback it decoded before bb-evidence (now an intermediate in outputs/); git keeps them
    for retired in (SITE / "wheels", SITE / "runtime", DATA / "repo", DATA / "playback"):
        if retired.exists():
            shutil.rmtree(retired)
    exported = export_playback()
    index, playback = export_records(exported)
    mirror_sources(index)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "page.json").write_text(json.dumps(page_data(), indent=1, allow_nan=False) + "\n")
    write_state(playback)
    after = {"served": site_bytes(), "on_disk": site_bytes(served=False)}
    records = sorted(RECORDS.rglob("*.json"))
    summary = {"runs": index["rule"]["count"], "left_out": index["left_out"], "solutions": len(index["solutions"]),
               "tasks": len(index["tasks"]), "records_on_disk": sum(path.stat().st_size for path in records),
               "records_served": sum(served_bytes(path) for path in records), "site_before": before, "site_after": after,
               "check_worst_mm": index["check_worst_mm"], "best": index["rule"]["full"]}
    print(json.dumps(summary, indent=1))
    on_disk = site_bytes(served=False)
    if on_disk > SIZE_LIMIT_BYTES:
        raise SystemExit(f"site/ is {on_disk / 1e6:.0f} MB, over GitHub Pages' 1 GB limit: ship fewer runs")
    big = [p for p in SITE.rglob("*") if p.is_file() and p.stat().st_size > FILE_LIMIT_BYTES]
    if big:
        raise SystemExit(f"over GitHub's 100 MiB per-file limit: {[str(p.relative_to(SITE)) for p in big]}")
    return summary


# ── check: what ships equals the scorecards ─────────────────────────────────────────────────────────────────


def _rounded(value: Any, digits: int) -> Any:
    """fold_runs.rnd for one number: Python's round, -0 as 0, non-finite as None."""
    if value is None or isinstance(value, bool):
        return value
    value = float(value)
    if not math.isfinite(value):
        return None
    out = round(value, digits)
    return 0.0 if out == 0 else out


def check() -> list[str]:
    """Problems with site/data (empty = pass): the shipped runs are the rule's on the current ledger, state.json's
    playback slice lists exactly their records, every record is this run's, and its metrics and gate verdicts equal its
    scorecard's per-task row (at the fold's stated rounding); the build's honesty checks passed."""
    problems: list[str] = []
    index_path = RECORDS / "index.json"
    if not index_path.exists():
        return ["site/data/runs/index.json is missing: run tools/build_site.py build"]
    if (DATA / "playback").exists():
        problems.append("site/data/playback/ is the retired binary playback: run tools/build_site.py build")
    index = json.loads(index_path.read_text())
    if index.get("schema") != RUNS_INDEX_SCHEMA:
        problems.append(f"site/data/runs/index.json is {index.get('schema')}, not {RUNS_INDEX_SCHEMA}")
    rule = selection()
    left = {(row["solution"], row["task"]) for row in index.get("left_out", [])}
    shipped = {(row["id"], task) for row in index["solutions"] for task in row["tasks"]}
    wanted = {(sid, task) for sid, tasks in rule["pairs"].items() for task in tasks}
    if shipped | left != wanted or shipped & left:
        problems.append(f"site/data/runs is stale for the current ledger ({len(wanted - shipped - left)} runs to add, "
                        f"{len(shipped - wanted)} gone, or a different best): run tools/build_site.py build")
    if index["rule"]["full"] != rule["full"]:
        problems.append(f"the index's best {index['rule']['full']} is not the ledger's {rule['full']}")
    state = json.loads((DATA / "state.json").read_text())
    listed = {row["path"]: row for row in (state.get("playback") or {}).get("runs", [])}
    records = {task["record"]: (row["id"], task_id) for row in index["solutions"] for task_id, task in row["tasks"].items()}
    if set(listed) != set(records):
        problems.append(f"state.json's playback lists {len(listed)} records, the index {len(records)}: "
                        f"{sorted(set(listed) ^ set(records))[:5]}")
    for path, (sid, task_id) in records.items():
        row = listed.get(path)
        if row and (row.get("solution"), row.get("task"), row.get("schema")) != (sid, task_id, "bb-run/1"):
            problems.append(f"state.json lists {path} as {row.get('solution')} {row.get('task')} {row.get('schema')}")
    on_disk = {path.relative_to(DATA).as_posix() for path in RECORDS.rglob("*.json") if path != RECORDS / "index.json"}
    if on_disk != set(records):
        problems.append(f"site/data/runs holds files the index does not list (or misses some): {sorted(on_disk ^ set(records))[:5]}")
    for solution in index["solutions"]:
        card = _scorecard(solution["id"])
        if card is None:
            problems.append(f"{solution['id']}: shipped but has no scorecard")
            continue
        if solution["objective"] != card["objective"] or solution["admissible"] != card["admissible"]:
            problems.append(f"{solution['id']}: the index's objective / admissible differ from the scorecard")
        if solution["scored"]["commit"] != card.get("code", {}).get("repo_commit"):
            problems.append(f"{solution['id']}: the index's scored commit differs from the scorecard")
        by_task = {r["task"]: r for r in card["tasks"]}
        for task_id, entry in solution["tasks"].items():
            where = f"{solution['id']} {task_id}"
            card_row = by_task.get(task_id)
            path = DATA / entry["record"]
            if card_row is None or not path.exists():
                problems.append(f"{where}: no scorecard row, or {entry['record']} is missing")
                continue
            record = json.loads(path.read_text())
            subject = record.get("subject", {})
            if (record.get("schema"), record.get("id"), subject.get("solution"), subject.get("task")) != (
                    "bb-run/1", f"{solution['id']}/{task_id}", solution["id"], task_id):
                problems.append(f"{entry['record']}: holds {record.get('schema')} {record.get('id')}")
                continue
            want = {"tool_track_rms_mm": card_row["objective"], **card_row["kpis"], **card_row["diagnostics"]}
            metrics_ = {m["id"]: m for m in record["metrics"]}
            for gate, verdict in card_row["verdicts"].items():
                if gate not in metrics_ or metrics_[gate]["passed"] is not bool(verdict):
                    problems.append(f"{where}: gate {gate} shows {metrics_.get(gate, {}).get('passed')}, the scorecard {verdict}")
            for metric in record["metrics"]:
                key = METRIC_KEY.get(metric["id"], metric["id"])
                if key not in want:
                    problems.append(f"{where}: metric {metric['id']} is not in the scorecard row")
                    continue
                value = want[key]
                expected = (bool(value) if isinstance(value, bool) else _rounded(value, METRIC_DIGITS[metric["id"]])
                            if metric["id"] in METRIC_DIGITS else value)
                if metric["value"] != expected or type(metric["value"]) is not type(expected):
                    problems.append(f"{where}: {metric['id']} = {metric['value']!r}, the scorecard {value!r}")
            if "tool_track_rms_mm" not in metrics_:
                problems.append(f"{where}: the record has no objective")
            if record.get("notes") != card_row["notes"]:
                problems.append(f"{where}: notes differ from the scorecard's row")
            if entry["objective"] != card_row["objective"] or entry["pass"] != all(card_row["verdicts"].values()):
                problems.append(f"{where}: the index's objective or pass differs from the scorecard's row")
            n = len(record["time"]["t"])
            if any(len(channel["values"]) != n for channel in record["channels"]):
                problems.append(f"{where}: a channel is not on the record's {n} samples")
            for layer in record["scene"]["geometry"]["layers"]:
                frames = layer.get("t", record["time"]["t"])
                if len(frames) != len(layer["poses"]) or frames != sorted(frames):
                    problems.append(f"{where}: layer {layer['id']} has {len(layer['poses'])} poses for {len(frames)} times")
            for name, item in entry["checks"].items():
                if not item["ok"]:
                    problems.append(f"{where}: the record's samples give {name} = {item['record']}, the ruler {item['ruler']}")
            for name, item in entry["subset"].items():
                if item["consistent"] is False:
                    problems.append(f"{where}: the record's 100 Hz samples contradict the ruler's {name}")
        source = SOURCES / solution["id"] / "solution.py"
        if not source.exists() or source.read_bytes() != (REPO / "solutions" / solution["id"] / "solution.py").read_bytes():
            problems.append(f"site/data/solutions/{solution['id']}/solution.py is not a byte copy of the solution")
    return problems


# ── serving and driving headless Chromium ──────────────────────────────────────────────────────────────────


# WHY a build of HEAD (2026-11-25, lane PKG): the page is blackbox_agent's stock landing over this repo's site/, written
# by `blackbox build` (CI runs the same on every push); there is no landing in site/ to serve. The build reads git at the
# ref, never the working tree, so commit before `parity` / `shoot` (they say which commit they drove).
BUILT = OUTPUTS / "built"


def built_site(out: Path = BUILT, ref: str = "HEAD") -> dict[str, Any]:
    """The live page as CI builds it, from `ref`: blackbox_agent's `build` (its record, blackbox-build.json, returned)."""
    from blackbox_agent.site import build as blackbox_build

    return blackbox_build(REPO, out, ref)


class Server:
    """`python3 -m http.server` on a free 127.0.0.1 port over a built site, stopped by PID on exit (never by port)."""

    def __init__(self, root: Path = BUILT) -> None:
        self.root = root

    def __enter__(self) -> Server:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.process = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(self.port), "--bind", "127.0.0.1", "--directory", str(self.root)],
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
RUNTIME_URL = re.compile(r"pyodide|@mujoco/mujoco|mujoco\.(js|wasm)|\.whl\b|/runtime/", re.I)


def _watch(page: Any, errors: list[str], requests: list[str] | None = None) -> None:
    """Page errors and console errors (both must stay empty), and every request URL."""
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on("console", lambda message: errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error" else None)
    if requests is not None:
        page.on("request", lambda request: requests.append(request.url))


def _wait_run(page: Any, path: str | None = None, timeout_s: float = 60.0) -> dict[str, Any]:
    """Wait until the landing's <bb-evidence> shows a run (this record, when named) with its cards or lanes drawn; returns
    the run's entry in state.json's playback slice."""
    page.wait_for_function("""(path) => { const e = document.querySelector('bb-evidence');
        if (!e || !e.rec || !e.path || (path && e.path !== path)) return false;
        const run = (e.runs || []).find((r) => r.path === e.path), s = e.rec.subject || {};
        return !!run && s.solution === run.solution && s.task === run.task
          && !!e.querySelector('.bbe-card, .bbe-lh[data-metric]'); }""", arg=path, timeout=timeout_s * 1e3)
    return page.evaluate("(() => { const e = document.querySelector('bb-evidence'); "
                         "return {...e.runs.find((r) => r.path === e.path)}; })()")


def _open_run(page: Any, path: str) -> dict[str, Any]:
    """Pick a run the way a visitor does: its chip in the explainer's run row (scrolled into view by the click)."""
    if page.evaluate("document.querySelector('bb-evidence').path") != path:
        page.locator(f"bb-evidence .bbe-runs button[data-run='{path}']").click()
    return _wait_run(page, path)


def _js_fmt(value: Any, digits: int = 3) -> str:
    """bb-evidence's fmt (bb-evidence.model.js), in Python: what a card shows for a number."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return f"{int(value):,}"
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value:,.0f}"
    decimals = max(0, digits - 1 - math.floor(math.log10(magnitude)))
    return f"{value:.{min(decimals, 6)}f}"


def _value_text(metric: dict[str, Any]) -> str:
    """bb-evidence's valueText: what a card's value reads."""
    if metric.get("display"):
        return metric["display"]
    value = metric["value"]
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "—"
    unit = metric.get("unit")
    return f"{_js_fmt(value)}{('' if unit in ('%', '°') else ' ') + unit if unit else ''}"


def _cards(page: Any) -> dict[str, str]:
    return dict(page.evaluate("[...document.querySelectorAll('bb-evidence .bbe-card')].map((c) => [c.dataset.metric, "
                              "c.querySelector('.val').textContent])"))


def _shows_its_record(page: Any, run: dict[str, Any]) -> list[str]:
    """The explainer on screen shows this run's record: its header names the run and every card reads the record's
    metric (which `check` proved equals the scorecard)."""
    record = json.loads((DATA / run["path"]).read_text())
    problems = []
    title = page.evaluate("document.querySelector('bb-evidence .bbe-title')?.textContent || ''")
    if run["solution"] not in title or run["task"] not in title:
        problems.append(f"{run['solution']} {run['task']}: the header reads {title!r}")
    shown = _cards(page)
    for metric in record["metrics"]:
        want = _value_text(metric)
        if shown.get(metric["id"]) != want:
            problems.append(f"{run['solution']} {run['task']}: card {metric['id']} shows {shown.get(metric['id'])!r}, "
                            f"the record {want!r}")
    return problems


def parity() -> dict[str, Any]:
    """Every saved run, in headless Chromium on the page CI builds (blackbox_agent's stock landing, built from HEAD): the
    explainer's run row lists exactly the runs state.json's playback slice lists, in the index's order, and each one,
    picked by its chip, plays its own bb-run/1 record with every card reading the record's number. Also: no page or
    console error, no request to a Python or MuJoCo runtime."""
    from playwright.sync_api import sync_playwright

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    record = built_site()
    index = json.loads((RECORDS / "index.json").read_text())
    want = [(row["id"], task, entry["record"]) for row in index["solutions"] for task, entry in row["tasks"].items()]
    report: dict[str, Any] = {"ref": record["ref"][:7], "package": record["package"], "checks": {}, "failures": []}
    errors: list[str] = []
    requests: list[str] = []
    played = 0
    with Server() as server, sync_playwright() as playwright:
        browser = _browser(playwright)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _watch(page, errors, requests)
        page.goto(f"{server.url}/index.html")
        _wait_run(page)
        listed = page.evaluate("document.querySelector('bb-evidence').runs.map((r) => [r.solution, r.task, r.path])")
        chips = page.evaluate("[...document.querySelectorAll('bb-evidence .bbe-runs button')].map((b) => b.dataset.run)")
        if sorted(map(tuple, listed)) != sorted(want):
            report["failures"].append(f"the page lists {len(listed)} runs, the index {len(want)}")
        if chips != [path for _, _, path in listed]:
            report["failures"].append(f"the run row has {len(chips)} chips for {len(listed)} listed runs")
        for solution, task, path in listed:
            run = _open_run(page, path)
            played += 1
            if (run["solution"], run["task"]) != (solution, task):
                report["failures"].append(f"{path}: plays {run['solution']} {run['task']}")
            report["failures"] += _shows_its_record(page, run)
        page.close()
        browser.close()
    report["played"] = played
    report["shipped"] = index["rule"]["count"]
    report["errors"] = errors[:20]
    report["requests"] = {"count": len(requests), "hosts": sorted({u.split('/')[2] for u in requests}),
                          "runtime": [u for u in requests if RUNTIME_URL.search(u)]}
    report["checks"] = {"every_run_plays_its_record": not report["failures"] and played == index["rule"]["count"],
                        "no_page_or_console_errors": not errors, "no_runtime_requests": not report["requests"]["runtime"]}
    report["pass"] = all(report["checks"].values())
    (OUTPUTS / "parity.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def _element_png(page: Any, selector: str, path: Path) -> None:
    """A screenshot of one element, with the page's sticky header hidden (it would sit over the element's top)."""
    page.evaluate("document.querySelector('header.top').style.visibility = 'hidden'")
    page.locator(selector).first.screenshot(path=str(path))
    page.evaluate("document.querySelector('header.top').style.visibility = ''")


def _scene_png(page: Any) -> bytes:
    page.wait_for_timeout(250)  # the scene draws on the next animation frame
    return page.locator("bb-evidence .bbe-scene").first.screenshot()


def shoot(media: Path | None = None) -> dict[str, Any]:
    """Headless checks and media (outputs/site/, or `media`) on the page CI builds (blackbox_agent's stock landing, built
    from HEAD; commit first): the default run loads, each metric card changes the scene
    and the readout, Lens <-> Recorder keeps the chosen metric, a lane opens its joints; screenshots of the first screen
    and the full page in light and dark and at 390 px (no sideways scroll, measured); a failing run in Recorder; zero
    page or console errors; the hero video."""
    from playwright.sync_api import sync_playwright

    out = media or OUTPUTS
    out.mkdir(parents=True, exist_ok=True)
    record = built_site()
    index = json.loads((RECORDS / "index.json").read_text())
    best = index["rule"]["full"]["best"]
    report: dict[str, Any] = {"ref": record["ref"][:7], "package": record["package"], "checks": {}, "cards": {}}
    errors: list[str] = []
    with Server() as server, sync_playwright() as playwright:
        browser = _browser(playwright)

        # 1. desktop, light: the default (the first run the playback slice lists: the best admissible); every card clicked
        page = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme="light")
        _watch(page, errors)
        started = time.time()
        page.goto(f"{server.url}/index.html")
        run = _wait_run(page)
        report["first_run_s"] = round(time.time() - started, 2)
        report["default"] = [run["solution"], run["task"]]
        report["checks"]["default_is_the_best_admissible"] = run["solution"] == best
        report["checks"]["cards_show_the_record"] = not _shows_its_record(page, run)
        page.evaluate("document.querySelector('bb-evidence').stop()")
        page.screenshot(path=str(out / "light-first-screen.png"))
        page.screenshot(path=str(out / "light-full.png"), full_page=True)
        before = _scene_png(page)
        record = json.loads((DATA / run["path"]).read_text())
        for metric in [m["id"] for m in record["metrics"] if m["id"] != "tool_track_rms_mm"] + ["tool_track_rms_mm"]:
            page.click(f"bb-evidence .bbe-card[data-metric='{metric}']")
            now = _scene_png(page)
            explain = page.evaluate("document.querySelector('bb-evidence .bbe-explain h3')?.textContent || ''")
            report["cards"][metric] = {"scene_changed": now != before, "explains": explain[:60]}
            before = now
        # Lens -> Recorder keeps the chosen metric; a lane opens its joints
        page.click("bb-evidence .bbe-card[data-metric='saturation_share_pct']")
        _element_png(page, "bb-evidence", out / "lens-torque.png")
        page.click("bb-evidence [data-layout='recorder']")
        page.wait_for_timeout(300)
        report["checks"]["recorder_keeps_the_metric"] = page.evaluate(
            "document.querySelector(\"bb-evidence .bbe-lane[data-metric='saturation_share_pct']\")?.getAttribute('aria-selected') === 'true'")
        page.click("bb-evidence .bbe-lh[data-metric='tool_track_rms_mm']")
        page.wait_for_timeout(300)
        report["checks"]["a_lane_opens_its_joints"] = page.evaluate(
            "!!document.querySelector(\"bb-evidence .bbe-lane.open[data-metric='tool_track_rms_mm']\")")
        _element_png(page, "bb-evidence", out / "recorder-best.png")
        page.close()

        # 2. a failing run in Recorder: where each number failed, red on the timeline
        failing = next(((row["id"], task) for row in index["solutions"] for task, entry in row["tasks"].items()
                        if not entry["pass"] and row["id"] == "p10"), None) or next(
            ((row["id"], task) for row in index["solutions"] for task, entry in row["tasks"].items() if not entry["pass"]), None)
        if failing:
            page = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme="light")
            _watch(page, errors)
            page.goto(f"{server.url}/index.html")
            _wait_run(page)
            run = _open_run(page, next(row for row in index["solutions"] if row["id"] == failing[0])["tasks"][failing[1]]["record"])
            report["failing"] = list(failing)
            report["checks"]["failing_cards_show_the_record"] = not _shows_its_record(page, run)
            page.evaluate("document.querySelector('bb-evidence').stop()")
            _element_png(page, "bb-evidence", out / "lens-failing.png")
            page.click("bb-evidence [data-layout='recorder']")
            page.wait_for_timeout(300)
            _element_png(page, "bb-evidence", out / "recorder-failing.png")
            report["checks"]["failing_run_flags_red"] = page.evaluate(
                "document.querySelectorAll('bb-evidence .bbe-sc .pf.bad').length") > 0
            page.close()

        # 3. dark, and the phone (390 px: nothing may scroll sideways)
        for name, viewport, scheme in (("dark", {"width": 1280, "height": 900}, "dark"),
                                       ("phone", {"width": 390, "height": 844}, "light"),
                                       ("phone-dark", {"width": 390, "height": 844}, "dark")):
            page = browser.new_page(viewport=viewport, color_scheme=scheme)
            _watch(page, errors)
            page.goto(f"{server.url}/index.html")
            _wait_run(page)
            page.evaluate("document.querySelector('bb-evidence').stop()")
            page.screenshot(path=str(out / f"{name}-first-screen.png"))
            page.screenshot(path=str(out / f"{name}-full.png"), full_page=True)
            width = page.evaluate("""() => ({scroll: document.documentElement.scrollWidth, inner: window.innerWidth,
              wider: [...document.querySelectorAll('body *')].filter((e) => { const r = e.getBoundingClientRect();
                return r.width && r.right > window.innerWidth + 0.5 && getComputedStyle(e).position !== 'fixed'
                  && !e.closest('.table-wrap, pre, .bbe-runs, .top nav'); }).slice(0, 5)
                .map((e) => `${e.tagName.toLowerCase()}.${[...e.classList].join('.')}`)})""")
            report[f"{name}_width"] = width
            report["checks"][f"{name}_no_sideways_scroll"] = width["scroll"] <= width["inner"] and not width["wider"]
            if name.startswith("phone"):
                page.click("bb-evidence [data-layout='recorder']")
                page.wait_for_timeout(300)
                _element_png(page, "bb-evidence", out / f"{name}-recorder.png")
                width = page.evaluate("({scroll: document.documentElement.scrollWidth, inner: window.innerWidth})")
                report["checks"][f"{name}_recorder_no_sideways_scroll"] = width["scroll"] <= width["inner"]
            page.close()

        # 4. the hero video: land -> Lens -> click a metric -> Recorder -> Lens -> change task
        video_dir = Path(tempfile.mkdtemp(dir=out))
        context = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light",
                                      record_video_dir=str(video_dir), record_video_size={"width": 1280, "height": 900})
        context.add_init_script(CURSOR)
        recording = time.monotonic()
        page = context.new_page()
        _watch(page, errors)
        start_s = max(0.0, time.monotonic() - recording - 0.1)  # WHY: the recording starts blank, before the goto
        page.goto(f"{server.url}/index.html")
        page.mouse.move(900, 700)
        _wait_run(page)
        page.wait_for_timeout(700)
        page.evaluate("window.scrollTo({top: document.querySelector('bb-evidence').getBoundingClientRect().top + scrollY - 64, "
                      "behavior: 'smooth'})")
        page.wait_for_timeout(900)

        def glide(selector: str, pause_ms: int) -> None:
            box = page.locator(selector).first.bounding_box()
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            page.mouse.move(x, y, steps=14)
            page.mouse.click(x, y)
            page.wait_for_timeout(pause_ms)

        glide("bb-evidence .bbe-strip .bbe-play", 1800)  # the saved run plays: the arm, its error whiskers, the cursor
        glide("bb-evidence .bbe-card[data-metric='stop_error_max_mm']", 1500)
        glide("bb-evidence [data-layout='recorder']", 1500)
        glide("bb-evidence .bbe-lh[data-metric='saturation_share_pct']", 1400)
        glide("bb-evidence [data-layout='lens']", 900)
        # another task of the best solution: its chip in the run row
        chip = page.locator(f"bb-evidence .bbe-runs button[data-run='runs/{best}/workspace-dev-002.json']")
        chip.scroll_into_view_if_needed()
        box = chip.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=14)
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        _wait_run(page, f"runs/{best}/workspace-dev-002.json")
        page.wait_for_timeout(1600)
        raw = Path(page.video.path())
        context.close()
        hero = out / "hero.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start_s:.2f}", "-i", str(raw), "-an",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        str(hero)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(hero), "-vf",
                        "fps=10,scale=720:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer",
                        str(out / "hero.gif")], check=True)
        shutil.rmtree(video_dir, ignore_errors=True)
        browser.close()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(hero)],
                           capture_output=True, text=True)
    report["hero_mp4_s"] = float(probe.stdout.strip() or "nan")
    report["errors"] = errors
    report["checks"]["every_card_changes_the_scene"] = all(card["scene_changed"] for card in report["cards"].values())
    report["checks"]["no_page_or_console_errors"] = not errors
    report["pass"] = all(report["checks"].values())
    (out / "shoot.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("build", "check", "parity", "shoot"))
    parser.add_argument("--media", type=Path, help="shoot: where the screenshots and the hero video go (default outputs/site/)")
    args = parser.parse_args(argv)
    if args.command in ("build", "check"):
        if args.command == "build":
            build()
        problems = check()
        print("\n".join(problems) or "check: PASS")
        return 1 if problems else 0
    if args.command == "parity":
        report = parity()
        print(json.dumps({key: report[key] for key in ("checks", "played", "shipped", "failures", "errors", "requests", "pass")},
                         indent=1))
        return 0 if report["pass"] else 1
    report = shoot(args.media)
    print(json.dumps({key: report.get(key) for key in ("checks", "cards", "pass", "hero_mp4_s", "first_run_s", "default",
                                                       "failing", "errors")}, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
