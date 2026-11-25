"""The Trajectory Comparison and Model × Dataset pages: site/comparison/ and site/models-datasets/, made by calling stock
viewers (traj_compare and data-ui), never by copying their code.

    uv run --all-extras python tools/build_dropins.py build    # both pages, from committed files only
    uv run --all-extras python tools/build_dropins.py check    # the committed pages against their sources (no writing)

WHY (Zach, Daily Note 2026-11-24): "the trajectory comparison viewer is like what shows you exactly the performance that
is being used to calculate the objectives. So yes please add the Trajectory Coverage and Trajectory Comparison as top
tabs ... And also one for Model x Dataset."

What it writes, and from where (every input is committed; nothing is simulated or scored here):

- **site/comparison/**: traj_compare's dataset level (`traj_compare.dataset.write_dataset_report`: `index.html` and
  `targets/<task>.js`) over the 42 dev tasks of `workspace/v2`, and one run report per task
  (`traj_compare.report.write_comparison_report`: `runs/<task>/report.html`, the question tabs and the 3-D stage): the
  target (the frozen tape, `datasets/ur5e_alone/workspace/v2/tapes/<task>.npz`) and, as situations, every solution
  the landing page ships on all 42 tasks (`site/data/runs/index.json` `rule.full`: the best admissible solution and the
  best of generation 0), read from their saved bb-run/1 records (`site/data/runs/<solution>/<task>.json`).
  - The dataset level's league ranks on the ruler's own per-task numbers, passed as run tags from each solution's
    `scorecard.json`, so its median over the 42 tasks *is* the objective. The run report's statistics table is that
    task's scorecard row. traj_compare's plots are its own (robot_msgs.compare, every sample drawn, rests included); its
    error statistics are taken over the ruler's moving samples (`Comparison(stats_mask=)`: `ruler.metrics.moving_mask`),
    so its tool position RMS is the scorecard's `tool_track_rms_mm`; tests/test_dropins.py holds that equality.
  - traj_compare runs in its own venv (`TTA_TRAJ_COMPARE_PYTHON`, default `../traj_compare/.venv/bin/python`): this
    repo never depends on it. The kinematics (the deployment's MuJoCo model: the tool site's pose, the drawn arm's
    capsules) are computed here first, in this repo's env, into `outputs/dropins/inputs/` (gitignored).
  - What ships is only what a browser opens: the dataset's run folders (manifests, `.npz`), its references and caches
    stay in `outputs/dropins/comparison-build/`. The run reports' viewer files (uPlot, three.js r160, the viewer) are
    written once to `site/comparison/assets/` and each report loads them from there (traj_compare's own
    `write_comparison_report(assets=)`); the dataset page stays one self-contained file. The dataset page's commands name
    its folder `site/comparison` (`command_root=`), never the build machine's path, and its runs table offers no Rerun
    action (`rerun=False`): no .rrd ships, so a Rerun link would be a 404 (review 2026-11-25: `rerun_server=False` +
    `public_url=` drew 168 of them).
- **site/models-datasets/**: data-ui's leaderboard pivot (CONTRACT §57) in the shared kit (`site/vendor/data-ui/`,
  vendored by tools/build_coverage.py at its DATA_UI_REF; the pivot is in its table view): `models-datasets.base` over
  `models-datasets.csv` (+ its `.schema.json` sidecar), one row per solution × split × task from today's
  `scorecard.json` (dev) and `scorecard_holdout.json`, every number a scorecard's float, and `media/<task>.svg`, each
  task's target tool path from its tape. The rows, the sidecar's fields and the three views are data-ui's gallery case
  `gallery/examples/models-datasets-tta/` (views.base, tta.schema.json, source/build.py at 74be0c9a), ported here so
  the page is built from this repo's files: rows nest family › model › config (`FAMILY_RULE`), columns deployment ·
  split › dataset › task kind › task; **Leaderboard** (the default: ranked on the dev deployment, ablations left out),
  **Pivot** (everything open, ablations drawn, nothing ranked), **Rows**. A dataset cell is the median of its tasks
  (the objective), a folded row the median of its rows, a deployment the equal-weight mean of its datasets, dev and
  holdout never pooled. A cell over one task result opens its run: the Comparison report on that run
  (`#tab=track&run=<solution>`) when the run is there, else the landing page's saved-run player on it
  (`landing_run_url`: `../index.html?run=<record path from runs/index.json>#run`) when that run ships, else the task's
  Comparison report; a holdout task has no saved run (the row's `opens` says which). WHY (Zach's ruling, 2026-11-24
  ~21:30, data-ui CONTRACT §57; lane MXDLIVE 2026-11-25, after Zach found the public page unchanged): the page still ran
  the stock-pivot first version after §57 merged in data-ui.
- **The site bar**: every page gets the one include of the viewer's stock `<bb-site-nav>` reading site/nav.json
  (tools/site_bar.py; blackbox_agent viewer CONTRACT §18). nav.json is hand-written; the build only checks it. The
  traj_compare pages follow the reader's colour scheme (traj_compare 38b5967's dark mode), so their bar does too (no
  `theme=`); a run report's bar names the run (`here`).

The pages are built here and committed, like the playback runs; CI does not rebuild them.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_bar  # noqa: E402  (tools/site_bar.py: the site bar's one include)

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
RECORDS = SITE / "data" / "runs"
RUNS_INDEX = RECORDS / "index.json"
SOLUTIONS = REPO / "solutions"
DATASET_DIR = Path("datasets/ur5e_alone/workspace/v2")
TAPES = REPO / DATASET_DIR / "tapes"
DEPLOYMENT = "ur5e_alone"
DATASET = "workspace/v2"
SPLIT = "dev"
COMPARISON = SITE / "comparison"
MXD = SITE / "models-datasets"
NAV_JSON = SITE / "nav.json"
WORK = REPO / "outputs" / "dropins"
INPUTS = WORK / "inputs"
BUILD = WORK / "comparison-build"
TRAJ_COMPARE_PYTHON = Path(os.environ.get("TTA_TRAJ_COMPARE_PYTHON",
                                          REPO.parent / "traj_compare" / ".venv" / "bin" / "python"))
PUBLIC_DIR = "site/comparison"  # what the dataset page's commands call its folder (write_dataset_report command_root)
# The first traj_compare commit with the stock options this build uses (assets=, command_root=, rerun=False,
# stats_mask=, dark mode, #run= deep links); the build refuses an older checkout
TRAJ_COMPARE_MIN = "a4c3c79"
EXCLUDED_TAG = "ablation"
TOOL_FRAME = "tool point"  # the flange site `tool`, 0.1 m along wrist_3 (OBJECTIVES §2); said once in each report
# OBJECTIVES §3's words for the task kinds, in the order it lists them
KINDS = (
    ("a_to_b_joint", "joint A→B moves"),
    ("a_to_b_line", "straight tool lines"),
    ("via_points", "via-point paths"),
    ("iso9283_path", "ISO 9283 path"),
    ("iso9283_cube", "ISO 9283 cube"),
)
KIND_LABEL = dict(KINDS)
KIND_ORDER = {kind: index for index, (kind, _) in enumerate(KINDS)}
GATE_WORDS = {
    "completed": "completed",
    "stop_error_max_mm": "stop error ≤ 1 mm",
    "saturation_share_pct": "saturation ≤ 2 %",
    "limit_violations": "within limits",
    "floor_clearance": "above the floor",
}
# The question tab a cell's deep link opens (traj_compare.tabs: "Did it track the target?")
DEEP_TAB = "track"
PRIVATE = re.compile(r"/home/|bam_ws|zach_brain|\.claude|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
# WHY allowed: three.min.js and uPlot carry their own licence banners; none of these is a private path or a person
PRIVATE_ALLOWED = re.compile(r"three@|noreply@anthropic\.com")


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def _write_json(path: Path, data: Any, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=False, separators=None if indent else (",", ":")) + "\n")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _commit(repo: Path) -> dict[str, Any]:
    return {"commit": _git(repo, "rev-parse", "--short=7", "HEAD"),
            "dirty": bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))}


def fmt(value: Any, unit: str = "") -> str:
    """A scorecard number as the pages write it: 4 significant figures, its unit after a space; None is a dash."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = f"{value:.4g}" if isinstance(value, float) else str(value)
    return f"{text} {unit}".strip()


# ── what ships: the solutions on every task, the tasks, the scorecards ────────────────────────────────────────────


def runs_index() -> dict[str, Any]:
    return _json(RUNS_INDEX)


def full_solutions(index: dict[str, Any] | None = None) -> list[str]:
    """The solutions the landing page ships on every dev task (its rule's `full`: the best admissible, the best of
    generation 0), in that order, without repeats."""
    index = index or runs_index()
    full = index["rule"]["full"]
    return [sid for sid in dict.fromkeys([full.get("best"), full.get("gen0_best")]) if sid]


def roles(index: dict[str, Any] | None = None) -> dict[str, str]:
    index = index or runs_index()
    full = index["rule"]["full"]
    out: dict[str, str] = {}
    if full.get("gen0_best"):
        out[full["gen0_best"]] = "best of generation 0"
    if full.get("best"):
        out[full["best"]] = "best admissible"
    return out


def dev_tasks(index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The dev tasks in dataset order, with their kind's label and order."""
    index = index or runs_index()
    tasks = []
    for order, task in enumerate(index["tasks"]):
        kind = task["kind"]
        tasks.append({**task, "order": order, "kind_label": KIND_LABEL.get(kind, kind), "kind_order": KIND_ORDER.get(kind, 99)})
    return tasks


def scorecard(solution_id: str) -> dict[str, Any]:
    return _json(SOLUTIONS / solution_id / "scorecard.json")


def meta(solution_id: str) -> dict[str, Any]:
    path = SOLUTIONS / solution_id / "meta.json"
    return _json(path) if path.exists() else {}


def task_rows(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["task"]: row for row in card["tasks"]}


def record_path(solution_id: str, task_id: str) -> Path:
    return RECORDS / solution_id / f"{task_id}.json"


def failed_gates(row: dict[str, Any]) -> list[str]:
    """A task row's failed gates, in the ruler's gate order (fail closed: a missing verdict is a failure)."""
    verdicts = row.get("verdicts") or {}
    return [gate for gate in GATE_WORDS if verdicts.get(gate) is not True]


# ── stage 1 (this repo's env): kinematics into outputs/dropins/inputs/ ──────────────────────────────────────────


def _capsule(radius: float, half_length: float, segments: int = 8, rings: int = 2) -> Any:
    """A capsule along its local z (MuJoCo's capsule axis) as an (M, 3, 3) triangle soup, low-poly: the drawn arm is
    context for the tool paths, not a measurement."""
    import numpy as np

    latitudes = np.linspace(0.0, np.pi / 2, rings + 1)
    profile = [(radius * np.cos(a), -half_length - radius * np.sin(a)) for a in latitudes[::-1]]
    profile += [(radius * np.cos(a), half_length + radius * np.sin(a)) for a in latitudes]
    angles = np.linspace(0.0, 2 * np.pi, segments + 1)
    rings_xyz = [[(rho * np.cos(t), rho * np.sin(t), z) for t in angles] for rho, z in profile]
    tris = []
    for lower, upper in zip(rings_xyz, rings_xyz[1:]):
        for k in range(segments):
            a, b, c, d = lower[k], lower[k + 1], upper[k], upper[k + 1]
            for tri in ((a, b, d), (a, d, c)):
                if len({tuple(np.round(p, 12)) for p in tri}) == 3:  # drop the poles' zero-area triangles
                    tris.append(tri)
    return np.asarray(tris, dtype=np.float32)


class _Kinematics:
    """The deployment's own MuJoCo model (robot_controllers' UR5e, as tools/build_site.py's `_Poses` loads it):
    the tool site's pose and every geom's pose per row of joint angles. The tool site's position is checked against
    `deployment.tool_position`, the ruler's tool point."""

    def __init__(self) -> None:
        import mujoco
        import trajectory_tracking_agent as tta
        from robot_controllers.bench.ur5e import load_model

        self.mujoco = mujoco
        self.dep = tta.deployment(DEPLOYMENT)
        self.model = load_model(frictionloss=False)
        self.data = mujoco.MjData(self.model)
        self.site = self.model.site(self.dep.tool_site).id

    def link_names(self) -> list[str]:
        return [self.model.body(int(self.model.geom_bodyid[g])).name for g in range(self.model.ngeom)]

    def meshes(self) -> list[Any]:
        m = self.model
        out = []
        for g in range(m.ngeom):
            if int(m.geom_type[g]) != int(self.mujoco.mjtGeom.mjGEOM_CAPSULE):
                raise SystemExit(f"geom {g} is not a capsule; teach _capsule its shape")
            out.append(_capsule(float(m.geom_size[g][0]), float(m.geom_size[g][1])))
        return out

    def __call__(self, q: Any) -> tuple[Any, Any]:
        """(tool poses (N, 4, 4), geom poses (N, G, 4, 4)) for joint angles (N, 6)."""
        import numpy as np

        rows = np.atleast_2d(np.asarray(q, dtype=np.float64))
        tool = np.tile(np.eye(4), (len(rows), 1, 1))
        geoms = np.tile(np.eye(4), (len(rows), self.model.ngeom, 1, 1))
        for index, row in enumerate(rows):
            self.data.qpos[:] = row
            self.mujoco.mj_kinematics(self.model, self.data)
            tool[index, :3, :3] = self.data.site_xmat[self.site].reshape(3, 3)
            tool[index, :3, 3] = self.data.site_xpos[self.site]
            geoms[index, :, :3, :3] = self.data.geom_xmat.reshape(-1, 3, 3)
            geoms[index, :, :3, 3] = self.data.geom_xpos
        ruler = np.asarray(self.dep.tool_position(rows))
        if not np.allclose(tool[:, :3, 3], ruler, rtol=0.0, atol=1e-12):
            raise SystemExit("the tool site's pose is not deployment.tool_position's point")
        return tool, geoms


def _channels(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {channel["id"]: channel for channel in record["channels"]}


def prepare() -> dict[str, Any]:
    """outputs/dropins/inputs/: per task an .npz (the target's and each run's joints, tool poses, torques, the drawn
    arm's link poses) and manifest.json (tasks, solutions, their scorecard rows). Reads committed files only."""
    import numpy as np
    from robot_msgs import load_npz

    index = runs_index()
    solutions = full_solutions(index)
    if not solutions:
        raise SystemExit("site/data/runs/index.json names no solution on every task (rule.full)")
    role = roles(index)
    tasks = dev_tasks(index)
    cards = {sid: scorecard(sid) for sid in solutions}
    rows = {sid: task_rows(card) for sid, card in cards.items()}
    kin = _Kinematics()
    caps = np.asarray(kin.dep.torque_cap_nm, dtype=float)
    if INPUTS.exists():
        shutil.rmtree(INPUTS)
    INPUTS.mkdir(parents=True)
    meshes = kin.meshes()
    np.savez_compressed(INPUTS / "meshes.npz", **{f"m{i}": mesh for i, mesh in enumerate(meshes)})
    robot_situation = solutions[0]
    worst_tool_mm = 0.0
    task_entries = []
    for task in tasks:
        task_id = task["id"]
        tape = load_npz(TAPES / f"{task_id}.npz")
        if list(tape.joint_names) != list(kin.dep.joint_names):
            raise SystemExit(f"{task_id}: the tape's joints are not the deployment's")
        target_pose, _ = kin(tape.positions)
        arrays: dict[str, Any] = {"t": tape.t, "target_pose": target_pose}
        situations = []
        for sid in solutions:
            path = record_path(sid, task_id)
            if not path.exists():
                raise SystemExit(f"no saved run {path.relative_to(REPO)}: run tools/build_site.py build first")
            record = _json(path)
            if record["subject"]["solution"] != sid or record["subject"]["task"] != task_id:
                raise SystemExit(f"{path.relative_to(REPO)} is not {sid} on {task_id}")
            channel = _channels(record)
            t = np.asarray(record["time"]["t"], dtype=float)
            if t.shape != tape.t.shape or not np.allclose(t, tape.t, rtol=0.0, atol=1e-9):
                raise SystemExit(f"{path.relative_to(REPO)}: its samples are not the target's")
            q = np.radians(np.asarray(channel["q"]["values"], dtype=float))
            tool = np.asarray(channel["tool"]["values"], dtype=float)
            # WHY the record's own tool point, not FK of its rounded joints: it is the ruler's measured point at the
            # record's stored resolution (build_site check: within 1e-5 mm of the scorecard); the rotation comes from
            # the deployment's FK of the record's joints, which the ruler never scores
            pose, links = kin(q)
            worst_tool_mm = max(worst_tool_mm, float(np.max(np.linalg.norm(pose[:, :3, 3] - tool, axis=1))) * 1e3)
            pose[:, :3, 3] = tool
            tau = np.asarray(channel["tau_pct"]["values"], dtype=float) / 100.0 * caps
            arrays[f"{sid}__q"] = q
            arrays[f"{sid}__pose"] = pose
            arrays[f"{sid}__tau"] = tau
            if sid == robot_situation:
                arrays[f"{sid}__links"] = links
            row = rows[sid].get(task_id)
            if row is None:
                raise SystemExit(f"solutions/{sid}/scorecard.json has no row for {task_id}")
            situations.append({"id": sid, "record": path.relative_to(REPO).as_posix(), "row": row})
        target_tool = target_pose[:, :3, 3]
        from trajectory_tracking_agent.ruler.metrics import moving_mask

        moving = moving_mask(tape.t, target_tool, tape.velocities)
        np.savez_compressed(INPUTS / f"{task_id}.npz", **arrays, moving=moving)
        task_entries.append({**task, "tape": (DATASET_DIR / "tapes" / f"{task_id}.npz").as_posix(),
                             "title": f"{task_id} · {task['kind_label']}", "samples": int(len(tape.t)),
                             "moving_samples": int(np.sum(moving)), "situations": situations})
    manifest = {
        "schema": "tta.dropins_inputs/1",
        "made_by": "tools/build_dropins.py prepare",
        "repo": _commit(REPO),
        "deployment": DEPLOYMENT, "dataset": DATASET, "split": SPLIT,
        "joint_names": list(kin.dep.joint_names),
        "torque_cap_nm": caps.tolist(),
        "tcp_frame": TOOL_FRAME,
        "solutions": [{"id": sid, "role": role.get(sid, ""), "objective": cards[sid]["objective"],
                       "admissible": cards[sid]["admissible"], "diagnostics": cards[sid]["diagnostics"]}
                      for sid in solutions],
        "robot": {"situation": robot_situation, "links": kin.link_names(), "meshes": "meshes.npz"},
        "fk_check_worst_mm": worst_tool_mm,
        "tasks": task_entries,
    }
    _write_json(INPUTS / "manifest.json", manifest)
    return manifest


# ── stage 2 (traj_compare's venv): the dataset level and one run report per task ────────────────────────────


def _stats_table(task: dict[str, Any], titles: dict[str, str]) -> Any:
    from traj_compare import ReportTable, TableRow

    rows = []
    for situation in task["situations"]:
        row = situation["row"]
        kpis, diag = row["kpis"], row["diagnostics"]
        failed = failed_gates(row)
        rows.append(TableRow(cells=[
            titles[situation["id"]],
            fmt(row["objective"], "mm"),
            fmt(diag.get("tool_track_max_mm"), "mm"),
            fmt(kpis.get("stop_error_max_mm"), "mm"),
            fmt(kpis.get("saturation_share_pct"), "%"),
            fmt(diag.get("joint_track_rms_deg"), "°"),
            fmt(diag.get("tool_lag_ms"), "ms"),
            "passes all 5" if not failed else "fails: " + ", ".join(GATE_WORDS[g] for g in failed),
        ], tone="positive" if not failed else "danger"))
    return ReportTable(
        title="The ruler's numbers for this task",
        columns=["Run", "Tool tracking RMS (moving samples)", "Worst tool error", "Worst stop error", "Torque at cap",
                 "Worst-joint tracking RMS", "Tool lag", "Gates"],
        rows=rows,
        description=(f"This task's row of each solution's solutions/<id>/scorecard.json, as tta evaluate scored it. The "
                     f"first column is the objective's per-task number: the RMS of the tool error over the "
                     f"{task['moving_samples']} of {task['samples']} samples where the target moves; the objective is "
                     "the median of the 42. The plots below are traj_compare's own (robot_msgs.compare, error = target "
                     "− run) and draw every sample, rests included; its error statistics are taken over the same "
                     "moving samples (stats_mask), so its tool position RMS is this first column's number."),
    )


def comparison_stage() -> None:
    """Runs under traj_compare's venv: reads outputs/dropins/inputs/, writes outputs/dropins/comparison-build/."""
    import numpy as np
    from robot_msgs import load_npz
    from robot_msgs.trajectory import JointTrajectory
    from traj_compare import (Comparison, Metric, MetricCard, ReportPage, RobotDisplay, Run, Situation, Sweep,
                              write_comparison_report, write_dataset_report)

    import traj_compare

    here = Path(traj_compare.__file__).resolve().parents[2]
    if subprocess.run(["git", "-C", str(here), "merge-base", "--is-ancestor", TRAJ_COMPARE_MIN, "HEAD"]).returncode:
        raise SystemExit(f"traj_compare at {here} is older than {TRAJ_COMPARE_MIN} (the stock options this build uses)")
    manifest = _json(INPUTS / "manifest.json")
    joints = tuple(manifest["joint_names"])
    solutions = [s["id"] for s in manifest["solutions"]]
    titles = {s["id"]: f"{s['id']} ({s['role']})" if s["role"] else s["id"] for s in manifest["solutions"]}
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    # the dataset level: one Run per task, each solution a measured series, the ruler's numbers as tags
    runs = []
    for task in manifest["tasks"]:
        data = np.load(INPUTS / f"{task['id']}.npz")
        tags: dict[str, Any] = {"task": task["id"], "kind": task["kind_label"], "split": SPLIT, "speed_fraction": 1.0}
        measured = {}
        for situation in task["situations"]:
            sid, row = situation["id"], situation["row"]
            measured[sid] = JointTrajectory(t=data["t"], joint_names=joints, positions=data[f"{sid}__q"],
                                            effort=data[f"{sid}__tau"])
            tags[f"{sid}_tool_track_rms_mm"] = row["objective"]
            tags[f"{sid}_stop_error_mm"] = row["diagnostics"]["stop_error_mm"]
            tags[f"{sid}_joint_track_rms_deg"] = row["diagnostics"]["joint_track_rms_deg"]
            tags[f"{sid}_tool_lag_ms"] = row["diagnostics"]["tool_lag_ms"]
        runs.append(Run(name=task["id"], title=task["title"], reference=load_npz(REPO / task["tape"]),
                        measured=measured, tags=tags, pairs=[("reference", sid) for sid in measured]))
    sweep = Sweep(
        x="speed_fraction", y="{series}_tool_track_rms_mm", facet_by="kind",
        x_label="speed fraction",
        y_label="tool tracking RMS (the ruler's per-task number; the median is the objective)",
        unit="mm",
        metrics=(Metric("{series}_stop_error_mm", label="stop error", unit="mm"),
                 Metric("{series}_joint_track_rms_deg", label="worst-joint tracking RMS", unit="°"),
                 Metric("{series}_tool_lag_ms", label="tool lag", unit="ms")),
    )
    summary = ReportPage(
        title="The ruler's numbers",
        description=("Each solution's scorecard (solutions/<id>/scorecard.json). The league above ranks on the same "
                     "per-task numbers, passed to traj_compare as run tags, so its median over the 42 tasks is the "
                     "objective; traj_compare's own joint-error numbers (robot_msgs.compare, every sample) sit beside it."),
        metrics=[MetricCard(label=f"{titles[s['id']]}: objective", value=fmt(s["objective"], "mm"),
                            detail=("median of the 42 per-task tool tracking RMS values; "
                                    + ("admissible: every task passes every gate" if s["admissible"] else "not admissible")),
                            tone="positive" if s["admissible"] else "danger")
                 for s in manifest["solutions"]],
    )
    write_dataset_report(runs, BUILD, title=f"Trajectory Comparison: {DEPLOYMENT} · {DATASET} · {SPLIT}",
                         target_by="task", sweep=sweep, summary=summary, rows=(), drill_down="lazy",
                         command_root=PUBLIC_DIR, rerun=False)
    page = (BUILD / "index.html").read_text()
    payload = json.loads(re.search(r'id="traj-compare-dataset">(.*?)</script>', page, re.S).group(1).replace("<\\/", "</"))
    target_slug = {target["key"]: (target["slug"], target["title"]) for target in payload["levels"]["targets"]}
    run_slug = {run["name"]: run["slug"] for run in payload["runs"]}

    # the run level: one report per task, the target and every solution as situations
    with np.load(INPUTS / manifest["robot"]["meshes"]) as stored:
        meshes = [stored[f"m{i}"] for i in range(len(stored.files))]
    for task in manifest["tasks"]:
        data = np.load(INPUTS / f"{task['id']}.npz")
        tape = load_npz(REPO / task["tape"])
        target = Situation(name="target", title="Target (the frozen tape)", t=tape.t, q=tape.positions,
                           qd=tape.velocities, qdd=tape.accelerations, poses=data["target_pose"])
        situations = []
        for situation in task["situations"]:
            sid = situation["id"]
            robot = None
            if sid == manifest["robot"]["situation"]:
                q = data[f"{sid}__q"]
                links = data[f"{sid}__links"]
                by_row = {np.ascontiguousarray(row, dtype=np.float64).tobytes(): i for i, row in enumerate(q)}

                def link_fk(rows, links=links, by_row=by_row):  # the precomputed poses of the rows asked for
                    rows = np.ascontiguousarray(np.asarray(rows, dtype=np.float64))
                    return links[[by_row[row.tobytes()] for row in rows]]

                robot = RobotDisplay(link_names=list(manifest["robot"]["links"]), link_meshes=meshes,
                                     link_fk=link_fk, name="UR5e (the deployment's capsules)")
            situations.append(Situation(name=sid, title=titles[sid], t=data["t"], q=data[f"{sid}__q"],
                                        tau=data[f"{sid}__tau"], poses=data[f"{sid}__pose"], robot=robot,
                                        note=situation["record"]))
        slug, target_title = target_slug[task["id"]]
        comparison = Comparison(
            title=task["title"], name=task["id"], joint_names=list(joints), target=target, situations=situations,
            tcp_frame=manifest["tcp_frame"], vec_dirs=[],
            stats_mask=data["moving"], stats_mask_label="moving samples", statistics=_stats_table(task, titles),
            description=(f"Target: {task['tape']} (the frozen dataset). Runs: the saved records tta evaluate wrote "
                         "(site/data/runs/<solution>/<task>.json): joints, the tool point and the applied torque at the "
                         "target's 100 Hz samples. The tool point is the ruler's: the flange site `tool`, 0.1 m along "
                         "wrist_3, through the deployment's own FK (its orientation too). Applied torque is the record's percent of each joint's cap (0.1 % "
                         "steps). The joint speeds and accelerations of a run are traj_compare's gradient of its joints."),
        )
        write_comparison_report(
            [comparison], BUILD / "runs" / run_slug[task["id"]] / "report.html", title=task["title"],
            subtitle=(f"{DEPLOYMENT} · {DATASET} · {SPLIT} · {task['duration_s']} s · the target moves on "
                      f"{task['moving_samples']} of {task['samples']} samples"),
            provenance={"task": task["id"], "built by": "tools/build_dropins.py"},
            assets=BUILD / "assets",
            breadcrumb=[("Comparison: all 42 tasks", "../../index.html#/"),
                        (target_title, f"../../index.html#/target/{slug}"), (task["id"], "")],
        )
    import robot_msgs

    _write_json(BUILD / "build.json", {
        "traj_compare": {**_commit(Path(traj_compare.__file__).resolve().parents[2]), "version": traj_compare.__version__},
        "robot_msgs": _commit(Path(robot_msgs.__file__).resolve().parents[2]),
        "slugs": {"runs": run_slug, "targets": {key: value[0] for key, value in target_slug.items()}},
    })


# ── stage 3 (this repo's env): what a browser opens goes into site/comparison/ ──────────────────────────────


def _with_bar(page: str, path: Path, current: str, **kw: str) -> str:
    """The site bar's one include right after <body> (tools/site_bar.py: <bb-site-nav> reading site/nav.json)."""
    return site_bar.include(page, path, current, **kw)


# What a rebuild changes even when nothing it shows did: the time it ran and the dataset page's per-write id
_STAMPS = (re.compile(r"generated: [^·<]*"), re.compile(r'"generated":"[^"]*"'), re.compile(r'"write_id":"[^"]*"'))


def _unstamped(text: str) -> str:
    for stamp in _STAMPS:
        text = stamp.sub("", text)
    return text


def _keep_unchanged(old: dict[str, bytes]) -> int:
    """Put back each file whose new text differs from the committed one only in its stamps, so a rebuild that changes
    nothing a reader sees leaves git clean (WHY: otherwise every rebuild rewrites 42 reports for a timestamp)."""
    kept = 0
    for rel, before in old.items():
        path = COMPARISON / rel
        if path.exists() and path.read_bytes() != before:
            if _unstamped(path.read_text()) == _unstamped(before.decode()):
                path.write_bytes(before)
                kept += 1
    return kept


def publish() -> dict[str, Any]:
    build = _json(BUILD / "build.json")
    old = {p.relative_to(COMPARISON).as_posix(): p.read_bytes() for p in COMPARISON.rglob("*")
           if p.is_file() and p.suffix in (".html", ".js")} if COMPARISON.exists() else {}
    if COMPARISON.exists():
        shutil.rmtree(COMPARISON)
    (COMPARISON / "targets").mkdir(parents=True)
    (COMPARISON / "assets").mkdir()
    index = (BUILD / "index.html").read_text()
    (COMPARISON / "index.html").write_text(_with_bar(index, COMPARISON / "index.html", "comparison"))
    for slug in build["slugs"]["targets"].values():
        shutil.copy2(BUILD / "targets" / f"{slug}.js", COMPARISON / "targets" / f"{slug}.js")
    for asset in sorted((BUILD / "assets").iterdir()):
        shutil.copy2(asset, COMPARISON / "assets" / asset.name)
    for slug in build["slugs"]["runs"].values():
        page = (BUILD / "runs" / slug / "report.html").read_text()
        out = COMPARISON / "runs" / slug / "report.html"
        out.parent.mkdir(parents=True)
        out.write_text(_with_bar(page, out, "comparison", here=f"Run · {slug}"))
    _keep_unchanged(old)
    manifest = _json(INPUTS / "manifest.json")
    files = sorted(p for p in COMPARISON.rglob("*") if p.is_file())
    _write_json(COMPARISON / "build.json", {
        "schema": "tta.dropins_build/1",
        "what": ("Trajectory Comparison, written by tools/build_dropins.py build from committed files (the tapes, the "
                 "bb-run/1 records in site/data/runs/, the scorecards); never edit, rebuild."),
        "made_by": {"repo": manifest["repo"], "traj_compare": build["traj_compare"], "robot_msgs": build["robot_msgs"]},
        "solutions": [{"id": s["id"], "role": s["role"]} for s in manifest["solutions"]],
        "tasks": [task["id"] for task in manifest["tasks"]],
        "assets": {asset.name: hashlib.sha256(asset.read_bytes()).hexdigest()
                   for asset in sorted((COMPARISON / "assets").iterdir())},
        "fk_check_worst_mm": manifest["fk_check_worst_mm"],
        "bytes": sum(p.stat().st_size for p in files),
    })
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}


# ── Model × Dataset: data-ui's leaderboard pivot (CONTRACT §57) over the scorecards ───────────────────────────────


MXD_DATA = "models-datasets.csv"  # beside it: models-datasets.schema.json, which data-ui reads as the CSV's sidecar
MXD_MEDIA = MXD / "media"
# Both scorecards of a solution: dev (every solution) and holdout (scored only to report a finished one); never pooled
SPLITS = (("dev", "scorecard.json"), ("holdout", "scorecard_holdout.json"))
# The task kinds as the pivot's column names say them (data-ui's gallery case's words: short, for vertical headers)
MXD_KIND = {"a_to_b_joint": ("Joint A→B", 0), "a_to_b_line": ("Line A→B", 1), "via_points": ("Via points", 2),
            "iso9283_path": ("ISO 9283 path", 3), "iso9283_cube": ("ISO 9283 cube", 4)}
# The data-ui commit whose gallery case gallery/examples/models-datasets-tta/ the rows, the schema and the views port
MXD_CASE = "data-ui 74be0c9a gallery/examples/models-datasets-tta/"


def _scored_solutions() -> list[str]:
    return sorted(p.parent.name for p in SOLUTIONS.glob("*/scorecard.json"))


def landing_run_url(record: str) -> str:
    """The landing page's player opened on one saved run, href relative to site/models-datasets/. ``record`` is the run's
    path as site/data/runs/index.json lists it (``runs/<solution>/<task>.json``, relative to site/data/). WHY ?run=
    (lane DROP2, 2026-11-25): blackbox_agent 0.1.5's landing reads ``index.html?run=<record path>#run`` into its replay
    and says so when the run is not one it ships, never swapping in another run silently."""
    return f"../index.html?{urllib.parse.urlencode({'run': record}, safe='/')}#run"


def landing_run_record(url: str) -> str | None:
    """The record a landing_run_url names (None for any other link)."""
    if not url.startswith("../index.html?"):
        return None
    query = url.split("?", 1)[1].split("#", 1)[0]
    return (urllib.parse.parse_qs(query).get("run") or [None])[0]


def shipped_records(index: dict[str, Any] | None = None) -> dict[tuple[str, str], str]:
    """{(solution, task): its record path} for every run site/data/runs/index.json ships."""
    index = index or runs_index()
    return {(s["id"], task_id): entry["record"] for s in index["solutions"] for task_id, entry in s["tasks"].items()}


def _deep_link(solution_id: str, task_id: str, in_comparison: set[str], records: dict[tuple[str, str], str],
               reported: set[str]) -> tuple[str | None, str]:
    """(href relative to site/models-datasets/ or None, what it opens, in a few words) for one task result. ``reported``:
    the tasks the Comparison has a run report for (the dev tasks)."""
    report = f"../comparison/runs/{task_id}/report.html#tab={DEEP_TAB}"
    if task_id in reported and solution_id in in_comparison:
        # traj_compare's #run=<name> opens that run beside the target (38b5967)
        return f"{report}&run={urllib.parse.quote(solution_id)}", "its run in the Comparison"
    if (solution_id, task_id) in records:
        # the Comparison holds the solutions shipped on every task; this one ships on one task per kind
        return landing_run_url(records[(solution_id, task_id)]), "its run in the landing page's player"
    if task_id in reported:
        return report, "the task's Comparison (this run is not saved, only its score)"
    return None, "nothing: only its score is saved (the saved runs and the Comparison are dev tasks)"


FAMILY_RULE = ("Rows nest family › model › config, read from the solution's id and meta.json: the family is the id's "
               "<code>pN</code> root, named with the first two phrases of that root's own change (\"P5 · model + "
               "Coulomb at plan time, board PD\"); the model is the id's first segment (<code>p5s</code>), the config the "
               "rest (<code>pass3</code>; \"as built\" when there is none). A solution tagged <code>ablation</code> is in "
               "the family Ablations, its model its ablation kind; ablations are never ranked: the Leaderboard leaves "
               "them out, and the Pivot, which ranks nothing, draws them.")


def mxd_family(solution_id: str, info: dict[str, Any], base_change: dict[str, str]) -> tuple[str, int, str, str]:
    """FAMILY_RULE: (family, its order, model, config). Ported from the gallery case's source/build.py (family_of)."""
    tags = info.get("tags") or []
    if EXCLUDED_TAG in tags:
        kind = next((t.split(":", 1)[1] for t in tags if t.startswith(f"{EXCLUDED_TAG}:")), EXCLUDED_TAG)
        return "Ablations", 99, kind, solution_id[4:] if solution_id.startswith("abl-") else solution_id
    model = solution_id.split("-")[0]
    config = solution_id.split("-", 1)[1] if "-" in solution_id else "as built"
    root = re.match(r"p(\d+)", solution_id)
    if not root:  # WHY: an id outside the pN scheme still gets a row (the case's port assumed every id had a root)
        return "Other", 98, model, config
    n = int(root.group(1))
    words = ", ".join((base_change.get(f"p{n}") or "").split(", ")[:2])
    return (f"P{n} · {words}" if words else f"P{n}"), n, model, config


def task_previews(tasks: list[str]) -> dict[str, str]:
    """A small SVG of each task's target tool path, from the top (x-y) and the side (x-z), each scaled to its own box,
    written to site/models-datasets/media/<task>.svg: the Leaderboard's column pictures (`media: {image: preview}`).
    Read from the frozen tapes (`tcp_pos`); ported from the gallery case's source/build.py (previews)."""
    import numpy as np  # noqa: PLC0415

    MXD_MEDIA.mkdir(parents=True, exist_ok=True)
    out = {}
    for task in tasks:
        tape = TAPES / f"{task}.npz"
        if not tape.exists():
            continue
        path = np.load(tape, allow_pickle=False)["tcp_pos"]
        pts = path[:: max(1, len(path) // 110)]

        def poly(a: int, b: int, x0: float, w: float, h: float, pad: float = 4):
            u, v = pts[:, a], pts[:, b]
            span = max(u.max() - u.min(), v.max() - v.min(), 1e-3)
            cu, cv = (u.max() + u.min()) / 2, (v.max() + v.min()) / 2
            s = (min(w, h) - 2 * pad) / span
            xs, ys = x0 + w / 2 + (u - cu) * s, h / 2 - (v - cv) * s
            return " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys)), (xs[0], ys[0]), (xs[-1], ys[-1])

        top, s0, e0 = poly(0, 1, 0, 60, 60)
        side, s1, e1 = poly(0, 2, 64, 60, 60)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 124 60" width="124" height="60">'
               '<rect x="0.5" y="0.5" width="59" height="59" rx="4" fill="none" stroke="#9aa0a6" stroke-opacity=".35"/>'
               '<rect x="64.5" y="0.5" width="59" height="59" rx="4" fill="none" stroke="#9aa0a6" stroke-opacity=".35"/>'
               f'<polyline points="{top}" fill="none" stroke="#3987e5" stroke-width="1.6" stroke-linejoin="round"/>'
               f'<polyline points="{side}" fill="none" stroke="#3987e5" stroke-width="1.6" stroke-linejoin="round"/>'
               f'<circle cx="{s0[0]:.1f}" cy="{s0[1]:.1f}" r="2.2" fill="#1a7f37"/><circle cx="{e0[0]:.1f}" cy="{e0[1]:.1f}" r="2.2" fill="#c63f33"/>'
               f'<circle cx="{s1[0]:.1f}" cy="{s1[1]:.1f}" r="2.2" fill="#1a7f37"/><circle cx="{e1[0]:.1f}" cy="{e1[1]:.1f}" r="2.2" fill="#c63f33"/>'
               '<text x="3" y="57" font-size="7" fill="#8a8f98" font-family="sans-serif">top</text>'
               '<text x="67" y="57" font-size="7" fill="#8a8f98" font-family="sans-serif">side</text></svg>')
        (MXD_MEDIA / f"{task}.svg").write_text(svg, encoding="utf-8")
        out[task] = f"media/{task}.svg"
    return out


# The CSV's columns and their sidecar fields (Frictionless + data-ui's unit / decimals / better / media / hidden): the
# gallery case's FIELDS, plus where a task result's link goes (`url`, `opens`)
MXD_FIELDS = [
    ("id", "string", {"description": "solution / task id"}),
    ("family", "string", {"description": "the solution's pN root (its change's first words); 'Ablations' for an ablation"}),
    ("family_order", "integer", {"hidden": True}),
    ("model", "string", {"description": "the solution id's first segment (an ablation: its kind)"}),
    ("config", "string", {"description": "the rest of the solution id ('as built' when there is none)"}),
    ("solution", "string", {}),
    ("parent", "string", {}),
    ("change", "string", {}),
    ("ablation", "boolean", {"description": "tagged 'ablation' in meta.json: never ranked, never in the default view"}),
    ("admissible", "boolean", {"description": "the scorecard's verdict: every gate on every task"}),
    ("deployment", "string", {"description": "the scorecard's deployment and split: dev and holdout are never pooled"}),
    ("deployment_order", "integer", {"hidden": True}),
    ("dataset", "string", {"description": "the dataset (its cell is the median of its tasks: the ruler's objective)"}),
    ("split", "string", {}),
    ("kind", "string", {}),
    ("kind_order", "integer", {"hidden": True}),
    ("task", "string", {}),
    ("rms_mm", "number", {"unit": "mm", "decimals": 4, "better": "lower",
                          "description": "RMS tool-point error over the task's moving samples (the task's objective)"}),
    ("max_mm", "number", {"unit": "mm", "decimals": 3, "better": "lower"}),
    ("stop_mm", "number", {"unit": "mm", "decimals": 3, "better": "lower",
                           "description": "the largest error at a stop (gate: at most 1 mm)"}),
    ("sat_pct", "number", {"unit": "%", "decimals": 2, "better": "lower"}),
    ("gates", "integer", {"decimals": 0, "better": "higher", "description": "of the 5 ruler gates on the task"}),
    ("gates_failed", "string", {}),
    ("preview", "string", {"media": "image", "hidden": True, "description": "the task's target tool path, top and side"}),
    ("opens", "string", {"description": "what a click on this task result's cell opens"}),
    ("url", "string", {"hidden": True, "description": "the cell's link, relative to this file"}),
]
MXD_TITLES = {"family": "Family", "model": "Model", "config": "Config", "solution": "Solution", "parent": "Parent",
              "change": "Change", "ablation": "Ablation", "admissible": "Admissible (every gate, every task)",
              "deployment": "Deployment · split", "dataset": "Dataset", "split": "Split", "kind": "Task kind",
              "task": "Task", "rms_mm": "Tool tracking RMS", "max_mm": "Tool tracking max", "stop_mm": "Stop error",
              "sat_pct": "Saturation share", "gates": "Gates passed (of 5)", "gates_failed": "Gates failed",
              "opens": "Opens", "url": "Link"}


def mxd_rows(pictures: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """One row per (scored solution, split, task), every number a scorecard's, unrounded (so a leaf cell IS the task's
    tool_track_rms_mm and a dataset cell's median IS the objective). The gallery case's source/build.py (main), read from
    today's solutions/*/scorecard.json, scorecard_holdout.json and meta.json, plus each row's link."""
    index = runs_index()
    in_comparison = set(full_solutions(index))
    records = shipped_records(index)
    reported = {task["id"] for task in dev_tasks(index)}
    solutions = sorted(p for p in SOLUTIONS.iterdir() if p.is_dir())
    metas = {p.name: _json(p / "meta.json") for p in solutions if (p / "meta.json").exists()}
    base_change = {sid: m.get("change", "") for sid, m in metas.items() if re.fullmatch(r"p\d+", sid)}
    rows = []
    for folder in solutions:
        sid, info = folder.name, metas.get(folder.name, {})
        family, family_order, model, config = mxd_family(sid, info, base_change)
        for split, name in SPLITS:
            path = folder / name
            if not path.exists():
                continue
            card = _json(path)
            if card.get("split") != split:
                raise SystemExit(f"{path.relative_to(REPO)}: split {card.get('split')!r}, expected {split!r}")
            deployment = f"{card['deployment']['name']} · {split}"
            dataset = card["dataset"]["name"].split("/", 1)[-1]
            for task in card["tasks"]:
                kind, kind_order = MXD_KIND.get(task["kind"], (task["kind"], 9))
                verdicts = task.get("verdicts") or {}
                url, opens = _deep_link(sid, task["task"], in_comparison, records, reported)
                rows.append({
                    "id": f"{sid}/{task['task']}", "family": family, "family_order": family_order, "model": model,
                    "config": config, "solution": sid, "parent": info.get("parent"),
                    # WHY the whole change (the case cut it at 90 characters): a stored property is shown as written
                    "change": info.get("change") or None,
                    "ablation": EXCLUDED_TAG in (info.get("tags") or []), "admissible": bool(card.get("admissible")),
                    "deployment": deployment, "deployment_order": 0 if split == "dev" else 1, "dataset": dataset,
                    "split": split, "kind": kind, "kind_order": kind_order,
                    "task": task["task"].replace("workspace-", "", 1),
                    "rms_mm": task.get("objective"),
                    "max_mm": _field(task, ("diagnostics", "tool_track_max_mm")),
                    "stop_mm": _field(task, ("kpis", "stop_error_max_mm")),
                    "sat_pct": _field(task, ("kpis", "saturation_share_pct")),
                    "gates": sum(1 for ok in verdicts.values() if ok is True),
                    "gates_failed": ", ".join(g for g, ok in verdicts.items() if ok is not True) or None,
                    "preview": (pictures or {}).get(task["task"]),
                    "opens": opens, "url": url,
                })
    rows.sort(key=lambda r: (r["family_order"], r["model"], r["config"], r["deployment_order"], r["kind_order"], r["task"]))
    if len({r["id"] for r in rows}) != len(rows):
        raise SystemExit("models-datasets: two rows share an id")
    leaf: dict[tuple[str, str, str], str] = {}
    for r in rows:
        if leaf.setdefault((r["family"], r["model"], r["config"]), r["solution"]) != r["solution"]:
            raise SystemExit(f"models-datasets: two solutions share the row {r['family']} › {r['model']} › {r['config']}")
    return rows


def _field(row: dict[str, Any] | None, path: tuple[str, ...]) -> Any:
    value: Any = row
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _csv_cell(value: Any) -> Any:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value  # a float writes as its shortest round-trip repr: the scorecard's float, read back bit for bit


def _mxd_csv(rows: list[dict[str, Any]]) -> str:
    import csv
    import io

    names = [name for name, _, _ in MXD_FIELDS]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(names)
    for row in rows:
        writer.writerow([_csv_cell(row[name]) for name in names])
    return buffer.getvalue()


def _mxd_schema() -> dict[str, Any]:
    fields = []
    for name, kind, extra in MXD_FIELDS:
        field = {"name": name, "type": kind}
        if name in MXD_TITLES:
            field["title"] = MXD_TITLES[name]
        field.update(extra)
        fields.append(field)
    return {"name": "models-datasets", "title": "Trajectory Tracking Agent: task results (solution × split × task)",
            "titleProperty": "solution", "linkProperty": "url",
            "source": ("tools/build_dropins.py from solutions/<id>/scorecard.json and scorecard_holdout.json (each task "
                       "row's objective, kpis, diagnostics, verdicts) and meta.json (tags, parent, change); links from "
                       f"site/data/runs/index.json; the shape is {MXD_CASE}"),
            "schema": {"fields": fields}}


# The views are the gallery case's views.base at MXD_CASE (CONTRACT §57; Zach's ruling of 2026-11-24 ~21:30), key for
# key: Leaderboard (the default), Pivot, Rows. tests/test_dropins.py holds the names and the order; data-ui's checker
# (`node <data-ui>/bin/data-ui.mjs check models-datasets.base`) holds the keys.
MXD_BASE = """# Model × Dataset · the solution leaderboard as ONE pivot over every task result (solution × split × task). CONTRACT
# §57's `pivot:` keys; the views are __CASE__views.base, Zach's ruling of 2026-11-24
# ~21:30: Leaderboard (the DEFAULT), Pivot (the bare stock pivot, nested rows, with the column roll-up) and the
# plain Rows. A dataset cell is the median of its tasks (the ruler's objective), a folded row the median of the rows under
# it, a deployment the equal-weight mean of its datasets; dev and holdout are never pooled. Ablation-tagged solutions are
# never ranked: the Leaderboard leaves them out; the Pivot, which ranks nothing (`color: none`, no sort), draws them.
# GENERATED by tools/build_dropins.py from the scorecards and meta.json: change the build, never this file.
# Check it: node <data-ui>/bin/data-ui.mjs check models-datasets.base
data: __DATA__
noun: [task result, task results]
facets:
  - family
  - { property: model, parent: family, searchable: true, limit: 8 }
  - kind
  - { property: admissible, as: toggle, value: true, text: "Admissible solutions only" }
properties:
  family: { displayName: Family }
  model: { displayName: Model }
  config: { displayName: Config }
  solution: { displayName: Solution }
  parent: { displayName: Parent }
  change: { displayName: Change }
  ablation: { displayName: Ablation }
  admissible: { displayName: "Admissible (every gate, every task)" }
  deployment: { displayName: "Deployment · split" }
  dataset: { displayName: Dataset }
  split: { displayName: Split }
  kind: { displayName: Task kind }
  task: { displayName: Task }
  rms_mm: { displayName: Tool tracking RMS }
  max_mm: { displayName: Tool tracking max }
  stop_mm: { displayName: Stop error }
  sat_pct: { displayName: Saturation share }
  gates: { displayName: "Gates passed (of 5)" }
  gates_failed: { displayName: Gates failed }
  opens: { displayName: Opens }
views:
  - type: pivot
    name: Leaderboard
    filters: "ablation == false"
    splitBy: [deployment, dataset, kind, task]
    value: { property: rms_mm, summary: Median }
    pivot:
      rows: [family, model, config]
      roles: { deployment: deployment, dataset: dataset }
      rollup: median
      metrics: [rms_mm, max_mm, stop_mm, gates]
      color: rank
      interval: median
      reference: ablation
      layout: compact
      fold: { rows: closed, columns: closed }
      sort: { column: "@__SORT__" }
      media: { image: preview }
      headers: vertical
  - type: pivot
    name: Pivot
    splitBy: [deployment, dataset, kind, task]
    value: { property: rms_mm, summary: Median }
    pivot:
      rows: [family, model, config]
      roles: { deployment: deployment, dataset: dataset }
      rollup: median
      metrics: [rms_mm, max_mm, stop_mm, gates]
      color: none
      reference: ablation
      layout: compact
      fold: { rows: open, columns: open }
      headers: horizontal
  - type: table
    name: Rows
    order: [model, config, solution, deployment, kind, task, rms_mm, max_mm, stop_mm, gates, gates_failed, admissible, ablation, change]
    groupBy: { property: family }
    fold: open
"""


MXD_PAGE = """<!doctype html>
<!-- GENERATED by tools/build_dropins.py (never edit; rebuild): Model × Dataset, data-ui's leaderboard pivot (CONTRACT §57)
     over models-datasets.csv (one row per solution × split × task, every number a scorecard's), the site bar on top. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model × Dataset · Trajectory Tracking Agent</title>
<meta name="description" content="The solution leaderboard: every solution on every task, dev and holdout, nested family › model › config and rolled up the way the ruler rolls it up. Unfold a column to its tasks; click a task's cell for its run.">
<link rel="stylesheet" href="../vendor/data-ui/data-ui.css">
<style>
  /* WHY --page-*: data-ui reads shadcn's token names from its host (--muted = a soft background, --accent = a hover
     fill; site/vendor/data-ui/data-ui.css), so a host --muted text grey painted the "Showing" pills, the count, the
     picked view tab and the group bands grey on grey (lane COV2, 2026-11-25). The page's own colours never use those names. */
  :root { --bg: #f7f7f5; --surface: #ffffff; --ink: #1b1e23; --page-muted: #5e6570; --line: #e1e3e1; --page-accent: #2c64d1;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; color-scheme: light dark; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #111317; --surface: #181b20; --ink: #e6e8eb; --page-muted: #a0a7b1; --line: #2a2f36; --page-accent: #6c9cf0; }
  }
  html, body { margin: 0; }
  body { background: var(--bg); color: var(--ink); font: 14px/1.45 var(--sans); }
  .page-head { padding: 14px 16px 10px; max-width: 1100px; }
  .page-head h1 { margin: 0 0 4px; font-size: 20px; }
  .page-head p { margin: 0; color: var(--page-muted); }
  .page-head p + p { margin-top: 4px; }
  .page-head a { color: var(--page-accent); }
  .page-head code { font: 12.5px var(--mono); }
  .page-head .small { font-size: 12.5px; }
  .page-head details { margin-top: 4px; font-size: 12.5px; color: var(--page-muted); }
  .page-head summary { cursor: pointer; width: max-content; max-width: 100%; }
  .frame { display: grid; grid-template-columns: 15rem minmax(0, 1fr); gap: 0 16px; padding: 0 16px 16px; }
  .frame aside { min-width: 0; border-right: 1px solid var(--line); padding-right: 12px; }
  main { min-width: 0; }
  data-views { display: block; }
  /* the filter panel stacks above the grid on a phone (data-facets is then its own closed disclosure) */
  @media (max-width: 767px) { .frame { display: block; } .frame aside { border: 0; padding: 0 0 8px; } }
</style>
</head>
<body>
__BAR__
<header class="page-head">
  <h1>Model × Dataset</h1>
  <p>__LEDE__</p>
  <p class="small" data-rollup-rule>__ROLLUP__</p>
  <details>
    <summary>How the rows, the views and the links are made</summary>
    <p>__FAMILIES__</p>
    <p>__VIEWS__</p>
    <p>__LINKS__</p>
  </details>
</header>
<div class="frame">
<aside aria-label="Filters"><data-facets for="models-datasets"></data-facets></aside>
<main>
<data-views id="models-datasets" src="models-datasets.base" view="Leaderboard" frame="page" views="tabs" filters="pills rail" aria-label="The solution leaderboard: every solution on every task"></data-views>
</main>
</div>
<script type="module" src="../vendor/data-ui/data-ui.js"></script>
<script>
  // WHY (a data-ui gap, asked in the handoff): a pivot cell opens "the records behind it" in the peek, with no link to
  // the record's page. Here a cell over ONE task result is one run, so a click on it goes to that run (the record's
  // url), read from data-ui's own data-views-open event; a cell over many records keeps the stock peek. CONTRACT §57's
  // cells raise the same event as the stock pivot's did ({row, column: '@…', records}), so this script is unchanged but
  // for the data file's name.
  document.getElementById('models-datasets').addEventListener('data-views-open', (event) => {
    const { column, records } = event.detail || {};
    if (!column || !String(column).startsWith('@') || !records || records.length !== 1 || !records[0].url) return;
    location.assign(new URL(records[0].url, new URL('__DATA__', location.href)).href);
  });
</script>
</body>
</html>
"""


def models_datasets() -> dict[str, Any]:
    if MXD.exists():
        shutil.rmtree(MXD)
    MXD.mkdir(parents=True)
    tasks = sorted({row["task"] for split, name in SPLITS for card in SOLUTIONS.glob(f"*/{name}")
                    for row in _json(card)["tasks"]})
    pictures = task_previews(tasks)
    rows = mxd_rows(pictures)
    (MXD / MXD_DATA).write_text(_mxd_csv(rows), encoding="utf-8")
    _write_json(MXD / MXD_DATA.replace(".csv", ".schema.json"), _mxd_schema())
    sort = next(r["deployment"] for r in rows if r["split"] == SPLIT)
    (MXD / "models-datasets.base").write_text(MXD_BASE.replace("__CASE__", MXD_CASE).replace("__DATA__", MXD_DATA)
                                              .replace("__SORT__", sort))
    ranked = sorted({r["solution"] for r in rows if not r["ablation"]})
    ablations = sorted({r["solution"] for r in rows if r["ablation"]})
    families = sorted({(r["family_order"], r["family"]) for r in rows if not r["ablation"]})
    per_split = {split: sorted({r["task"] for r in rows if r["split"] == split}) for split, _ in SPLITS}
    holdout = sorted({r["solution"] for r in rows if r["split"] == "holdout"})
    deployment = next(r["deployment"] for r in rows).split(" · ")[0]
    dataset = next(r["dataset"] for r in rows)
    lede = (f"The solution leaderboard: {len(ranked)} solutions in {len(families)} families, nested family › model › "
            f"config, on every task of <code>{deployment}</code> › <code>{dataset}</code>: the "
            f"{len(per_split['dev'])} dev tasks, and the {len(per_split['holdout'])} holdout tasks for the "
            f"{len(holdout)} solutions scored there (holdout is scored only to report a finished solution, never to "
            f"pick one). A task's cell is its <code>tool_track_rms_mm</code> from the solution's scorecard: the RMS "
            f"tool error over the samples where the target moves. Unfold a column to its task kinds and tasks; click a "
            f"task's cell to open its run.")
    rollup = ("<b>Roll-up, in plain words:</b> a solution's score on a dataset is the <b>median</b> of its per-task "
              "numbers (that median is the objective); a folded row (a model, a family) is the median of the rows "
              "under it, one vote per row; a deployment is the plain average of its datasets' scores, every dataset "
              "counted once, and dev and holdout are never pooled; a deployment ranks only the rows scored on every one "
              f"of its datasets. Ruler v1 has one dataset, so the <b>{html.escape(sort)}</b> column is each "
              "solution's objective, and the Leaderboard ranks on it. The Roll up buttons over the grid switch the "
              "method (Median, Mean, Best, Rank, Count) and the grid says the rule it is using in words.")
    views = (f"Three views of the same rows (data-ui's leaderboard pivot, CONTRACT §57): <b>Leaderboard</b> (the "
             f"default) ranks the solutions on the dev deployment, tints each cell by its rank in its column, and puts a "
             f"picture of each task's target tool path over its column; the {len(ablations)} ablations are left out. "
             "<b>Pivot</b> is the bare pivot with every row and column open, the ablations drawn but never ranked. "
             "<b>Rows</b> is every task result. In both pivots a column group folds into one roll-up column that says "
             "its method and count; the Metric control switches the number (tool tracking RMS or max, stop error, "
             "gates passed), and the left panel filters by family, model, task kind and admissible.")
    links = ("A cell over one task result opens its run: in the Trajectory Comparison for the solutions saved on every "
             "dev task, in the landing page's player for those saved on one task per kind, else the task's Comparison "
             "(this run is not saved, only its score); a holdout task has no saved run, so its cell opens the records "
             "behind it, as every cell over several does. Each task result's <b>Opens</b> says which.")
    page = (MXD_PAGE.replace("__LEDE__", lede).replace("__ROLLUP__", rollup).replace("__FAMILIES__", FAMILY_RULE)
            .replace("__VIEWS__", views).replace("__LINKS__", links).replace("__DATA__", MXD_DATA)
            .replace("__BAR__", site_bar.tag(MXD / "index.html", "models-datasets")))
    (MXD / "index.html").write_text(page)
    return {"rows": len(rows), "solutions": len(ranked), "ablations": len(ablations),
            "families": [name for _, name in families], "tasks": {s: len(t) for s, t in per_split.items()},
            "holdout_solutions": len(holdout), "pictures": len(pictures)}


def mxd_table() -> list[dict[str, Any]]:
    """The committed models-datasets.csv, typed by its own sidecar (what data-ui reads)."""
    import csv

    schema = _json(MXD / MXD_DATA.replace(".csv", ".schema.json"))
    kinds = {field["name"]: field["type"] for field in schema["schema"]["fields"]}

    def typed(name: str, text: str) -> Any:
        if text == "":
            return None
        if kinds.get(name) == "number":
            return float(text)
        if kinds.get(name) == "integer":
            return int(text)
        if kinds.get(name) == "boolean":
            return text == "true"
        return text

    with (MXD / MXD_DATA).open(newline="", encoding="utf-8") as handle:
        return [{name: typed(name, text) for name, text in row.items()} for row in csv.DictReader(handle)]


# ── check: the committed pages against their sources ─────────────────────────────────────────────────────────


def report_payload(task_id: str) -> dict[str, Any]:
    page = (COMPARISON / "runs" / task_id / "report.html").read_text()
    match = re.search(r'id="traj-compare-data">(.*?)</script>', page, re.S)
    return json.loads(match.group(1).replace("<\\/", "</"))


def dataset_payload() -> dict[str, Any]:
    page = (COMPARISON / "index.html").read_text()
    match = re.search(r'id="traj-compare-dataset">(.*?)</script>', page, re.S)
    return json.loads(match.group(1).replace("<\\/", "</"))


def page_links(path: Path) -> list[str]:
    """Every static href / src in a page (not data:, not absolute URLs, not in-page anchors)."""
    # WHY scripts emptied first: a page's own code builds links in strings ('href="runs/' + slug ...); those are
    # checked from the payload (link_problems), a <script src> stays
    text = re.sub(r"(<script[^>]*>).*?(</script>)", r"\1\2", path.read_text(), flags=re.S)
    links = re.findall(r"""(?:href|src)=["']([^"']+)["']""", text)
    return [link for link in links if not re.match(r"^(?:[a-z]+:|#|//)", link)]


def resolves(base: Path, link: str) -> bool:
    target = link.split("#", 1)[0].split("?", 1)[0]
    if not target:
        return True
    # WHY site_bar.built (2026-11-25, lane PKG): the landing (index.html) and the bar's module (dashboard/...) are written
    # by blackbox_agent's `blackbox build`, not kept in site/
    return site_bar.built((base.parent / target).resolve())


def our_files() -> list[Path]:
    files = [NAV_JSON]
    for folder in (COMPARISON, MXD):
        files += [p for p in folder.rglob("*") if p.is_file()]
    return files


def private_hits(files: list[Path] | None = None) -> list[str]:
    hits = []
    for path in files or our_files():
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            for match in PRIVATE.finditer(line):
                if not PRIVATE_ALLOWED.search(line[max(0, match.start() - 20): match.end() + 20]):
                    hits.append(f"{path.relative_to(REPO)}:{number}: {match.group(0)}")
    return hits


def link_problems() -> list[str]:
    problems = []
    pages = [COMPARISON / "index.html", MXD / "index.html", *sorted(COMPARISON.glob("runs/*/report.html"))]
    for page in pages:
        for link in page_links(page):
            if not resolves(page, link):
                problems.append(f"{page.relative_to(REPO)}: {link}")
    payload = dataset_payload()
    index = COMPARISON / "index.html"
    for line in payload["levels"]["lines"]:  # the line's ↗ (dataset.js builds it from `report`)
        if not resolves(index, line["report"]):
            problems.append(f"comparison line {line['id']}: {line['report']}")
    for run in payload["runs"]:  # the runs table's Open run, and the sweep's worst targets
        if not resolves(index, f"runs/{run['slug']}/report.html"):
            problems.append(f"comparison run {run['name']}")
    for target in payload["levels"]["targets"]:
        if not resolves(index, f"targets/{target['slug']}.js"):
            problems.append(f"comparison target {target['slug']}: targets/{target['slug']}.js")
    shipped = set(shipped_records().values())
    data = MXD / MXD_DATA
    for row in mxd_table():
        if row["url"] is None:
            continue
        if not resolves(data, row["url"]):
            problems.append(f"models-datasets {row['id']}: {row['url']}")
        record = landing_run_record(row["url"])
        if row["url"].startswith("../index.html") and (record not in shipped or not (SITE / "data" / record).is_file()):
            problems.append(f"models-datasets {row['id']}: {row['url']} names no record in runs/index.json")
        if row["preview"] and not (MXD / row["preview"]).is_file():
            problems.append(f"models-datasets {row['id']}: no picture {row['preview']}")
    problems += site_bar.nav_problems()
    problems += site_bar.page_problems(pages)
    return problems


def number_problems() -> list[str]:
    """Every scorecard number the pages show equals the scorecard's float."""
    problems = []
    index = runs_index()
    solutions = full_solutions(index)
    cards = {sid: scorecard(sid) for sid in solutions}
    payload = dataset_payload()
    facet = next(f for f in payload["sweep"]["facets"] if f["value"] == "all")
    league = {c["name"]: c["points"][0] for c in facet["configs"]}
    for sid in solutions:
        if league[sid]["median"] != cards[sid]["objective"]:
            problems.append(f"league median {sid}: {league[sid]['median']} != scorecard {cards[sid]['objective']}")
        if league[sid]["n"] != len(cards[sid]["tasks"]):
            problems.append(f"league n {sid}")
    for task in dev_tasks(index):
        payload = report_payload(task["id"])
        table = payload["comparisons"][0]["statistics"]
        shown = {row["cells"][0].split(" ")[0]: row["cells"] for row in table["rows"]}
        for sid in solutions:
            row = task_rows(cards[sid])[task["id"]]
            if shown.get(sid, [None, None])[1] != fmt(row["objective"], "mm"):
                problems.append(f"{task['id']} {sid}: table {shown.get(sid)} != {fmt(row['objective'], 'mm')}")
    # Model × Dataset: every task result is its scorecard row's float; a dataset cell (data-ui's median of a leaf row's
    # tasks: the mean of the middle two of an even count) is the scorecard's objective
    by_card: dict[tuple[str, str], list[float]] = {}
    for row in mxd_table():
        solution, task_id = row["id"].split("/", 1)
        card = _json(SOLUTIONS / solution / dict(SPLITS)[row["split"]])
        task_row = task_rows(card).get(task_id)
        if task_row is None or row["rms_mm"] != task_row["objective"]:
            problems.append(f"models-datasets {row['id']}: {row['rms_mm']}")
        by_card.setdefault((solution, row["split"]), []).append(row["rms_mm"])
    for (solution, split), values in by_card.items():
        card = _json(SOLUTIONS / solution / dict(SPLITS)[split])
        values = sorted(values)
        mid = len(values) // 2
        median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
        if len(values) != len(card["tasks"]) or median != card["objective"]:
            problems.append(f"models-datasets {solution} {split}: median {median} != objective {card['objective']}")
    return problems


def check() -> list[str]:
    problems = []
    for path in (COMPARISON / "index.html", MXD / "index.html", MXD / MXD_DATA, MXD / "models-datasets.base", NAV_JSON,
                 site_bar.BAR_JS):
        if not path.exists():
            problems.append(f"missing {path.relative_to(REPO)}")
    if problems:
        return problems
    problems += number_problems()
    problems += link_problems()
    problems += private_hits()
    return problems


# ── build ─────────────────────────────────────────────────────────────────────────────────────────────────


def _served_bytes(paths: list[Path]) -> tuple[int, int]:
    import gzip

    disk = sum(p.stat().st_size for p in paths)
    served = sum(len(gzip.compress(p.read_bytes(), compresslevel=4, mtime=0)) for p in paths)
    return disk, served


DATA_UI = Path(os.environ.get("TTA_DATA_UI", REPO.parent / "data-ui"))


def base_problems() -> list[str]:
    """data-ui's own checker on models-datasets.base against its data (every key of CONTRACT §57, every property it
    names); [] with a note when node or the data-ui checkout is not here (CI never builds these pages)."""
    cli = DATA_UI / "bin" / "data-ui.mjs"
    if not cli.exists() or not shutil.which("node"):
        print(f"note: data-ui's checker not run (no node or no {cli.name} under TTA_DATA_UI)")
        return []
    result = subprocess.run(["node", str(cli), "check", str(MXD / "models-datasets.base"), "--json"],
                            capture_output=True, text=True, timeout=120)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [f"data-ui check failed: {(result.stderr or result.stdout)[-1000:]}"]
    return [f"data-ui check: {p}" for p in report.get("problems", [])] if report.get("errors") or report.get("warnings") else []


def build() -> None:
    manifest = prepare()
    print(f"inputs: {len(manifest['tasks'])} tasks x {len(manifest['solutions'])} solutions "
          f"(FK vs the records' tool points: worst {manifest['fk_check_worst_mm']:.4f} mm)")
    if not TRAJ_COMPARE_PYTHON.exists():
        raise SystemExit(f"no traj_compare venv python at {TRAJ_COMPARE_PYTHON} (set TTA_TRAJ_COMPARE_PYTHON)")
    env = {**os.environ, "PYTHONPATH": ""}
    env.pop("VIRTUAL_ENV", None)
    result = subprocess.run([str(TRAJ_COMPARE_PYTHON), str(Path(__file__).resolve()), "comparison"], cwd=REPO, env=env,
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-4000:] + result.stderr[-8000:])
        raise SystemExit("the traj_compare stage failed")
    published = publish()
    print(f"site/comparison: {published['files']} files, {published['bytes'] / 1e6:.2f} MB")
    print(f"site/models-datasets: {models_datasets()}")
    for name, folder in (("comparison", COMPARISON), ("models-datasets", MXD)):
        disk, served = _served_bytes([p for p in folder.rglob("*") if p.is_file()])
        print(f"  {name}: {disk / 1e6:.2f} MB on disk, {served / 1e6:.2f} MB served (gzip)")
    problems = check() + base_problems()
    if problems:
        print("\n".join(problems[:40]))
        raise SystemExit(f"{len(problems)} problems")
    print("check: every number is its scorecard's, every link resolves, no private path, data-ui's checker clean")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build", "check", "prepare", "comparison", "publish", "mxd"))
    args = parser.parse_args(argv)
    if args.command == "build":
        build()
    elif args.command == "check":
        problems = check()
        print("\n".join(problems) if problems else "ok")
        return 1 if problems else 0
    elif args.command == "prepare":
        prepare()
    elif args.command == "comparison":
        comparison_stage()
    elif args.command == "publish":
        print(publish())
    elif args.command == "mxd":
        print(models_datasets())
        problems = base_problems()
        print("\n".join(problems) if problems else "data-ui check: clean")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
