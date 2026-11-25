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
    task's scorecard row. traj_compare's own plots and its joint-error numbers are its own (robot_msgs.compare at every
    sample, rests included); tests/test_dropins.py holds the relation between the two.
  - traj_compare runs in its own venv (`TTA_TRAJ_COMPARE_PYTHON`, default `../traj_compare/.venv/bin/python`): this
    repo never depends on it. The kinematics (the deployment's MuJoCo model: the tool site's pose, the drawn arm's
    capsules) are computed here first, in this repo's env, into `outputs/dropins/inputs/` (gitignored).
  - What ships is only what a browser opens: the dataset's run folders (manifests, `.npz`), its references and caches
    stay in `outputs/dropins/comparison-build/`. The run reports' inlined viewer files (uPlot, three.js r160, the
    viewer) are written once to `site/comparison/assets/` and each report loads them from there (`_share_assets`: an
    exact, checked substitution of traj_compare's own inline copies); the dataset page stays one self-contained file.
- **site/models-datasets/**: data-ui's stock `pivot` (`models-datasets.base` over `cells.json`, one row per solution ×
  dev task, every value a scorecard's) in the data-ui kit lane CV vendored (`site/vendor/data-ui/`; the pivot is in
  its table view). Rows = iterations nested under their family (`FAMILY_RULE`: by lineage), ablations in their own
  view; columns = dataset › task kind › task; cell = that task's `tool_track_rms_mm`. Margins: the per-dataset median
  (the objective; PICKS' roll-up, with one dataset just the median) and the worst task; a family's row and the footer
  are data-ui's own summaries (median). Presets roll a level up (per task kind, per dataset by median, mean or mean
  rank: `RANK_RULE`) or switch the metric; in any of them data-ui's view settings switch Cell value and Summary in
  place. The left panel is data-ui's `<data-facets>`; "Rows" is the plain list. A cell opens its run: the Comparison
  report when the run is there, else the landing page's saved-run player when that run ships, else the task's
  Comparison report (the record says which). WHY (dispatcher, relaying Zach's feedback, 2026-11-24): the stock first
  version; lanes PV and VZ design the full pivot, and what data-ui cannot do is listed, not hand-rolled.
- **The site bar**: every page gets the one include of the viewer's stock `<bb-site-nav>` reading site/nav.json
  (tools/site_bar.py; blackbox_agent viewer CONTRACT §18). nav.json is hand-written; the build only checks it. The
  traj_compare pages have no dark mode, so their bar says `theme="light"`; a run report's bar names the run (`here`).

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
PUBLIC_DIR = "site/comparison"  # what the dataset page's commands name instead of the build's absolute folder
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
# The traj_compare report's inlined files, as report.py writes them: (tag, asset file name)
REPORT_ASSETS = (
    ("style", "uplot.min.css"),
    ("style", "style.css"),
    ("script", "uplot.iife.min.js"),
    ("script", "three.min.js"),
    ("script", "viewhelper.js"),
    ("script", "viewer3d.js"),
    ("script", "plots.js"),
)
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
        np.savez_compressed(INPUTS / f"{task_id}.npz", **arrays)
        target_tool = target_pose[:, :3, 3]
        from trajectory_tracking_agent.ruler.metrics import moving_mask

        moving = moving_mask(tape.t, target_tool, tape.velocities)
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
                     "− run, at every sample, rests included), so the RMS its hovers show is not the ruler's."),
    )


def comparison_stage() -> None:
    """Runs under traj_compare's venv: reads outputs/dropins/inputs/, writes outputs/dropins/comparison-build/."""
    import importlib.resources

    import numpy as np
    from robot_msgs import load_npz
    from robot_msgs.trajectory import JointTrajectory
    from traj_compare import (Comparison, Metric, MetricCard, ReportPage, RobotDisplay, Run, Situation, Sweep,
                              write_comparison_report, write_dataset_report)

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
                         target_by="task", sweep=sweep, summary=summary, rows=(), drill_down="lazy")
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
            tcp_frame=manifest["tcp_frame"], vec_dirs=[], statistics=_stats_table(task, titles),
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
            breadcrumb=[("Comparison: all 42 tasks", "../../index.html#/"),
                        (target_title, f"../../index.html#/target/{slug}"), (task["id"], "")],
        )
    assets = BUILD / "assets"
    assets.mkdir()
    for _, name in REPORT_ASSETS:
        (assets / name).write_text(importlib.resources.files("traj_compare").joinpath("assets", name).read_text("utf-8"))
    import robot_msgs
    import traj_compare

    _write_json(BUILD / "build.json", {
        "traj_compare": {**_commit(Path(traj_compare.__file__).resolve().parents[2]), "version": traj_compare.__version__},
        "robot_msgs": _commit(Path(robot_msgs.__file__).resolve().parents[2]),
        "slugs": {"runs": run_slug, "targets": {key: value[0] for key, value in target_slug.items()}},
    })


# ── stage 3 (this repo's env): what a browser opens goes into site/comparison/ ──────────────────────────────


def _with_bar(page: str, path: Path, current: str, **kw: str) -> str:
    """The site bar's one include right after <body> (tools/site_bar.py: <bb-site-nav> reading site/nav.json)."""
    return site_bar.include(page, path, current, **kw)


def _share_assets(page: str, assets: Path, rel: str) -> str:
    """Each of traj_compare's inlined viewer files, exactly as the report inlines it, becomes a reference to its one
    copy in site/comparison/assets/. WHY: 42 reports each inlining the same 0.92 MB (three.js r160 is 0.67 MB of it)
    would ship 39 MB of copies; a missing or changed inline copy stops the build (traj_compare ask: an `assets=` option)."""
    for tag, name in REPORT_ASSETS:
        content = (assets / name).read_text()
        inline = f"<{tag}>{content}</{tag}>"
        if page.count(inline) != 1:
            raise SystemExit(f"the report does not inline {name} exactly once as report.py writes it")
        reference = (f'<link rel="stylesheet" href="{rel}{name}">' if tag == "style"
                     else f'<script src="{rel}{name}"></script>')
        page = page.replace(inline, reference, 1)
    return page


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
    absolute = str(BUILD.resolve())
    index = (BUILD / "index.html").read_text()
    # WHY: the dataset page names its own folder in the commands it offers (serve, drill, Rerun); the public copy names
    # it as this repo does, from the repo root (traj_compare ask: a public_url / relative-commands option)
    index = index.replace(absolute, PUBLIC_DIR)
    (COMPARISON / "index.html").write_text(_with_bar(index, COMPARISON / "index.html", "comparison", theme="light"))
    for slug in build["slugs"]["targets"].values():
        shutil.copy2(BUILD / "targets" / f"{slug}.js", COMPARISON / "targets" / f"{slug}.js")
    for _, name in REPORT_ASSETS:
        shutil.copy2(BUILD / "assets" / name, COMPARISON / "assets" / name)
    for slug in build["slugs"]["runs"].values():
        page = (BUILD / "runs" / slug / "report.html").read_text()
        page = _share_assets(page, BUILD / "assets", "../../assets/")
        out = COMPARISON / "runs" / slug / "report.html"
        out.parent.mkdir(parents=True)
        out.write_text(_with_bar(page, out, "comparison", here=f"Run · {slug}", theme="light"))
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
        "assets": {name: hashlib.sha256((COMPARISON / "assets" / name).read_bytes()).hexdigest() for _, name in REPORT_ASSETS},
        "fk_check_worst_mm": manifest["fk_check_worst_mm"],
        "bytes": sum(p.stat().st_size for p in files),
    })
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}


# ── Model × Dataset: data-ui's pivot over the scorecards ─────────────────────────────────────────────────────


def _scored_solutions() -> list[str]:
    return sorted(p.parent.name for p in SOLUTIONS.glob("*/scorecard.json"))


def _deep_link(solution_id: str, task_id: str, in_comparison: set[str]) -> tuple[str, str]:
    """(href relative to site/models-datasets/, what it opens, in a few words) for one cell."""
    report = f"../comparison/runs/{task_id}/report.html#tab={DEEP_TAB}"
    if solution_id in in_comparison:
        return report, "its run in the Comparison"
    if record_path(solution_id, task_id).exists():
        # the Comparison holds the solutions shipped on every task; this one ships on one task per kind
        return f"../index.html?solution={solution_id}&task={task_id}#run", "its run in the landing page's player"
    return report, "the task's Comparison (this run is not saved, only its score)"


FAMILY_RULE = ("Family, by lineage: a generation-0 solution (tag gen-0: robot_controllers' P1–P10 configs) is in "
               "\"generation 0\"; an ablation (tag ablation) is in \"ablations\"; every other solution is in its "
               "lineage, named by the generation-0 solution reached by following its parents (\"p5s lineage\").")


def family_of(solution_id: str, metas: dict[str, dict[str, Any]]) -> str:
    """FAMILY_RULE, read from meta.json's tags and parents."""
    info = metas.get(solution_id, {})
    tags = info.get("tags", [])
    if EXCLUDED_TAG in tags:
        return "ablations"
    if "gen-0" in tags:
        return "generation 0"
    seen, node = set(), solution_id
    while metas.get(node, {}).get("parent") and node not in seen:
        seen.add(node)
        node = metas[node]["parent"]
    return f"{node} lineage"


# The metrics a cell can show (the pivot's stock "Cell value" switch and one preset view each): (property, label, unit,
# the scorecard task row's field, digits)
METRICS = (
    ("tool_track_rms_mm", "Tool tracking RMS", "mm", ("objective",), 3),
    ("rank_on_task", "Rank on the task", "", None, 0),
    ("stop_error_max_mm", "Worst stop error", "mm", ("kpis", "stop_error_max_mm"), 3),
    ("tool_track_max_mm", "Worst tool error", "mm", ("diagnostics", "tool_track_max_mm"), 3),
    ("saturation_share_pct", "Torque at cap", "%", ("kpis", "saturation_share_pct"), 3),
    ("joint_track_rms_deg", "Worst-joint tracking RMS", "°", ("diagnostics", "joint_track_rms_deg"), 3),
    ("failed_gate_count", "Gates failed", "", None, 0),
)
RANK_RULE = ("Rank on the task: 1 + how many of the solutions (ablations left out) have a lower tool tracking RMS on "
             "that task; ties share a rank, an ablation is placed among the solutions, and a failed gate does not "
             "change it (the Gates failed view shows those).")


def _field(row: dict[str, Any] | None, path: tuple[str, ...] | None) -> Any:
    value: Any = row
    for key in path or ():
        value = value.get(key) if isinstance(value, dict) else None
    return value


def mxd_rows() -> list[dict[str, Any]]:
    """One row per (scored solution, dev task), every number a scorecard's (the rank is counted from them)."""
    index = runs_index()
    in_comparison = set(full_solutions(index))
    tasks = {task["id"]: task for task in dev_tasks(index)}
    solutions = [sid for sid in _scored_solutions() if scorecard(sid).get("split") == SPLIT]
    metas = {sid: meta(sid) for sid in (p.parent.name for p in SOLUTIONS.glob("*/meta.json"))}
    cards = {sid: scorecard(sid) for sid in solutions}
    per_task = {sid: task_rows(card) for sid, card in cards.items()}
    ranked = {task_id: sorted(per_task[sid][task_id]["objective"] for sid in solutions
                              if EXCLUDED_TAG not in metas[sid].get("tags", []) and task_id in per_task[sid]
                              and per_task[sid][task_id]["objective"] is not None)
              for task_id in tasks}
    rows = []
    for sid in solutions:
        card, info = cards[sid], metas[sid]
        values = [per_task[sid][t]["objective"] for t in tasks if t in per_task[sid]]
        finite = [v for v in values if v is not None and math.isfinite(v)]
        failing = [t for t in tasks if t in per_task[sid] and failed_gates(per_task[sid][t])]
        gates = "passes every gate" if card["admissible"] else f"fails a gate on {len(failing)} of {len(per_task[sid])} tasks"
        for task_id, task in tasks.items():
            row = per_task[sid].get(task_id)
            failed = failed_gates(row) if row else list(GATE_WORDS)
            url, opens = _deep_link(sid, task_id, in_comparison)
            value = row["objective"] if row else None
            out = {
                "id": f"{sid}/{task_id}",
                "family": family_of(sid, metas),
                "solution": sid,
                "iteration": "ablation" if EXCLUDED_TAG in info.get("tags", []) else "solution",
                "gates": gates,
                "objective_mm": card["objective"],
                "worst_task_mm": max(finite) if finite else None,
                "deployment": DEPLOYMENT,
                "dataset": DATASET,
                "kind": task["kind_label"],
                "task": task_id,
                "verdict": "not run" if row is None else ("pass" if not failed else "fail"),
                "failed_gates": [GATE_WORDS[g] for g in failed] if row else [],
                "rank_on_task": None if value is None else 1 + sum(1 for v in ranked[task_id] if v < value),
                "failed_gate_count": len(failed) if row else None,
                "opens": opens,
                "url": url,
                "parent": info.get("parent") or "",
                "kind_order": task["kind_order"],
                "task_order": task["order"],
            }
            for prop, _, _, path, _ in METRICS:
                if path is not None:
                    out[prop] = _field(row, path)
            rows.append(out)
    return rows


def _mxd_properties() -> dict[str, Any]:
    props: dict[str, Any] = {
        "family": {"type": "text", "width": 150},
        "solution": {"type": "text", "width": 170},
        "iteration": {"type": "text", "width": 90},
        "gates": {"type": "text", "width": 150},
        "objective_mm": {"type": "number", "unitText": "mm", "digits": 3, "width": 120, "better": "lower"},
        "worst_task_mm": {"type": "number", "unitText": "mm", "digits": 3, "width": 100, "better": "lower"},
        "deployment": {"type": "text"},
        "dataset": {"type": "text"},
        "kind": {"type": "text"},
        "task": {"type": "text"},
        "verdict": {"type": "text", "width": 80},
        "failed_gates": {"type": "list", "width": 200},
        "opens": {"type": "text", "width": 300},
        "url": {"type": "text", "width": 120},
        "parent": {"type": "text"},
        "kind_order": {"type": "number", "hidden": True},
        "task_order": {"type": "number", "hidden": True},
    }
    for prop, _, unit, _, digits in METRICS:
        spec: dict[str, Any] = {"type": "number", "width": 80, "better": "lower"}
        if unit:
            spec["unitText"] = unit
        spec.update({"digits": digits} if digits else {"decimals": 0})
        props[prop] = spec
    return props


def _mxd_base(rows: list[dict[str, Any]]) -> str:
    """The .base: one pivot preset per roll-up level and per metric, a plain row view, the rail's facets."""
    columns = sorted({(r["kind_order"], r["task_order"], r["kind"], r["task"]) for r in rows})
    kinds = sorted({(r["kind_order"], r["kind"]) for r in rows})
    per_task = [f"@{DATASET} / {kind} / {task}" for _, _, kind, task in columns]
    per_kind = [f"@{DATASET} / {kind}" for _, kind in kinds]
    per_dataset = [f"@{DEPLOYMENT} / {DATASET}"]

    def calc(ids: list[str], summary: str = "Median") -> str:
        return "\n".join(f"      '{cid}': {summary}" for cid in ids)

    names = "\n".join(f"  {prop}: {{ displayName: '{label}' }}" for prop, label, _, _, _ in METRICS)
    def rows_spec(by: str = "objective_mm") -> str:
        # WHY by the cell's own column in a per-dataset view: a pivot sorts its rows by what each row keeps, and those
        # views keep no objective column (their one cell is the roll-up itself)
        return f"""    groupBy: {{ property: family }}
    groupOrder: [p5s lineage, generation 0, ablations]
    sort:
      - {{ property: '{by}', direction: ASC }}
    fold: open"""
    # WHY presets and the stock switches (dispatcher, relaying Zach 2026-11-24: "a metric switcher", the roll-up
    # "switchable between median, mean and rank", default PICKS' per-dataset median): each view below is a preset; in any
    # pivot the toolbar's view settings switch "Cell value" (the metric) and "Summary" (Median, Average, ...) in place, and
    # a column's menu switches the family rows' and the footer's calculation
    return f"""# Model × Dataset: one row per iteration (solution) nested under its family, one column per dev task grouped
# deployment › dataset › task kind › task; a cell is that task's number from solutions/<id>/scorecard.json.
# GENERATED by tools/build_dropins.py from the scorecards and meta.json: change the build, never this file.
# {FAMILY_RULE}
# {RANK_RULE}
# Check it: node <data-ui>/bin/data-ui.mjs check models-datasets.base
data: cells.json
facets:
  - family
  - gates
  - kind
  - iteration
properties:
  family: {{ displayName: Family }}
  solution: {{ displayName: Iteration }}
  iteration: {{ displayName: Kind of iteration }}
  gates: {{ displayName: Gates }}
  objective_mm: {{ displayName: 'Median of the dataset' }}
  worst_task_mm: {{ displayName: Worst task }}
  deployment: {{ displayName: Deployment }}
  dataset: {{ displayName: Dataset }}
  kind: {{ displayName: Task kind }}
  task: {{ displayName: Task }}
  verdict: {{ displayName: Gates on this task }}
  failed_gates: {{ displayName: Failed gates }}
  opens: {{ displayName: Opens }}
  url: {{ displayName: Link }}
  parent: {{ displayName: Parent }}
{names}
open: side
views:
  - type: pivot
    name: Per task
    filters: 'iteration == "solution"'
    order: [solution, gates, objective_mm, worst_task_mm]
{rows_spec()}
    splitBy: [dataset, kind, task]
    value: {{ property: tool_track_rms_mm, summary: Median }}
    summaries:
{calc(per_task)}
  - type: pivot
    name: Per task kind
    filters: 'iteration == "solution"'
    order: [solution, gates, objective_mm]
{rows_spec()}
    splitBy: [dataset, kind]
    value: {{ property: tool_track_rms_mm, summary: Median }}
    summaries:
{calc(per_kind)}
  - type: pivot
    name: Per dataset (median)
    filters: 'iteration == "solution"'
    order: [solution, gates]
{rows_spec(per_dataset[0])}
    splitBy: [deployment, dataset]
    value: {{ property: tool_track_rms_mm, summary: Median }}
    summaries:
{calc(per_dataset)}
  - type: pivot
    name: Per dataset (mean)
    filters: 'iteration == "solution"'
    order: [solution, gates]
{rows_spec(per_dataset[0])}
    splitBy: [deployment, dataset]
    value: {{ property: tool_track_rms_mm, summary: Average }}
    summaries:
{calc(per_dataset, "Average")}
  - type: pivot
    name: Per dataset (mean rank)
    filters: 'iteration == "solution"'
    order: [solution, gates]
{rows_spec(per_dataset[0])}
    splitBy: [deployment, dataset]
    value: {{ property: rank_on_task, summary: Average }}
    summaries:
{calc(per_dataset, "Average")}
  - type: pivot
    name: Gates failed
    filters: 'iteration == "solution"'
    order: [solution, gates]
{rows_spec()}
    splitBy: [dataset, kind, task]
    value: {{ property: failed_gate_count, summary: Max }}
    summaries:
{calc(per_task, "Sum")}
  - type: pivot
    name: With ablations
    order: [solution, iteration, gates, objective_mm, worst_task_mm]
{rows_spec()}
    splitBy: [dataset, kind, task]
    value: {{ property: tool_track_rms_mm, summary: Median }}
    summaries:
{calc(per_task)}
  - type: table
    name: Rows
    open: {{ mode: link, url: url }}
    order: [solution, family, task, kind, tool_track_rms_mm, rank_on_task, verdict, failed_gates, stop_error_max_mm, objective_mm, opens]
    groupBy: {{ property: family }}
    groupOrder: [p5s lineage, generation 0, ablations]
    sort:
      - {{ property: objective_mm, direction: ASC }}
      - {{ property: task_order, direction: ASC }}
    display: {{ verdict: status }}
    fold: open
"""


MXD_PAGE = """<!doctype html>
<!-- GENERATED by tools/build_dropins.py (never edit; rebuild): Model × Dataset, data-ui's stock pivot over cells.json
     (one row per solution × dev task, every number a scorecard's), the site bar on top. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model × Dataset · Trajectory Tracking Agent</title>
<meta name="description" content="Every solution on every dev task: the ruler's per-task tool tracking error, nested by family, rolled up per task kind and per dataset (median, mean or mean rank). Click a cell for its run.">
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
    <summary>How the rows, the rank and the links are made</summary>
    <p>__FAMILIES__</p>
    <p>__RANK__</p>
    <p>__CONTROLS__</p>
  </details>
</header>
<div class="frame">
<aside aria-label="Filters"><data-facets for="models-datasets"></data-facets></aside>
<main>
<data-views id="models-datasets" src="models-datasets.base" view="Per task" frame="page" views="tabs" filters="pills rail" aria-label="Every solution on every dev task"></data-views>
</main>
</div>
<script type="module" src="../vendor/data-ui/data-ui.js"></script>
<script>
  // WHY (a data-ui gap, asked in the handoff): a pivot cell opens "the records behind it" as plain text, with no link to
  // the record's page. Here a per-task cell is one run, so a plain click on it goes to that run (the record's url),
  // read from data-ui's own data-views-open event; a cell over many records keeps the stock peek.
  document.getElementById('models-datasets').addEventListener('data-views-open', (event) => {
    const { column, records } = event.detail || {};
    if (!column || !String(column).startsWith('@') || !records || records.length !== 1 || !records[0].url) return;
    location.assign(new URL(records[0].url, new URL('cells.json', location.href)).href);
  });
</script>
</body>
</html>
"""


def models_datasets() -> dict[str, Any]:
    rows = mxd_rows()
    solutions = sorted({r["solution"] for r in rows if r["iteration"] == "solution"})
    ablations = sorted({r["solution"] for r in rows if r["iteration"] == "ablation"})
    families = sorted({r["family"] for r in rows})
    tasks = sorted({r["task"] for r in rows})
    if MXD.exists():
        shutil.rmtree(MXD)
    MXD.mkdir(parents=True)
    data = {
        "id": "models-datasets",
        "title": "Model × Dataset",
        "titleProperty": "id",
        "linkProperty": "url",
        "source": ("tools/build_dropins.py from solutions/<id>/scorecard.json (each task row's objective, kpis, "
                   "diagnostics, verdicts) and meta.json (tags, parent); links from site/data/runs/index.json"),
        "properties": _mxd_properties(),
        "rows": rows,
    }
    _write_json(MXD / "cells.json", data, indent=None)
    (MXD / "models-datasets.base").write_text(_mxd_base(rows))
    lede = (f"One row per iteration ({len(solutions)} solutions in {len(families) - (1 if ablations else 0)} families; "
            f"the {len(ablations)} ablations are in the <b>With ablations</b> view), one column per dev task of "
            f"<code>{DEPLOYMENT}</code> › <code>{DATASET}</code>, grouped by task kind ({len(tasks)} tasks). A cell is "
            "that task's <code>tool_track_rms_mm</code> from the solution's <code>scorecard.json</code>: the RMS tool "
            "error over the samples where the target moves. Click a cell to open its run.")
    rollup = ("<b>Roll-up, in plain words:</b> a solution's score on a dataset is the <b>median</b> of its per-task "
              "numbers (that median is the objective); across datasets of one deployment the score is the plain "
              "average of those medians, with every dataset counted once; deployments are never pooled. Ruler v1 has "
              "one dataset, so the score is the median of the 42 tasks: the <b>Median of the dataset</b> column, and "
              "the <b>Per dataset (median)</b> view. <b>Per dataset (mean)</b> and <b>(mean rank)</b> roll up the "
              "same numbers by their mean and by the solution's average rank across the tasks. A family's row and the "
              "footer show the median of the rows under them (a column's menu, Calculate, switches it).")
    controls = ("Switches: the views are presets of one roll-up level or one metric; in any of them the toolbar's view "
                "settings switch the metric (Cell value), the roll-up (Summary: Median, Average, …) and the column "
                "levels in place. The left panel filters by family, gates, task kind and kind of iteration. "
                "<b>Rows</b> is the plain list behind the grid. A cell opens its run: in the Trajectory Comparison for "
                "the solutions saved on every task, in the landing page's player for those saved on one task per kind, "
                "else the task's Comparison (its record says which).")
    page = (MXD_PAGE.replace("__LEDE__", lede).replace("__ROLLUP__", rollup).replace("__FAMILIES__", FAMILY_RULE)
            .replace("__RANK__", RANK_RULE).replace("__CONTROLS__", controls)
            .replace("__BAR__", site_bar.tag(MXD / "index.html", "models-datasets")))
    (MXD / "index.html").write_text(page)
    return {"rows": len(rows), "solutions": len(solutions), "ablations": len(ablations), "families": families,
            "tasks": len(tasks)}


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
    cells = _json(MXD / "cells.json")
    for row in cells["rows"]:
        if not resolves(MXD / "cells.json", row["url"]):
            problems.append(f"models-datasets {row['id']}: {row['url']}")
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
    cells = _json(MXD / "cells.json")["rows"]
    for row in cells:
        card = scorecard(row["solution"])
        task_row = task_rows(card).get(row["task"])
        if row["tool_track_rms_mm"] != (task_row["objective"] if task_row else None):
            problems.append(f"models-datasets {row['id']}: {row['tool_track_rms_mm']}")
        if row["objective_mm"] != card["objective"]:
            problems.append(f"models-datasets objective {row['solution']}")
    return problems


def check() -> list[str]:
    problems = []
    for path in (COMPARISON / "index.html", MXD / "index.html", MXD / "cells.json", NAV_JSON, site_bar.BAR_JS):
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
    problems = check()
    if problems:
        print("\n".join(problems[:40]))
        raise SystemExit(f"{len(problems)} problems")
    print("check: every number is its scorecard's, every link resolves, no private path")


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
