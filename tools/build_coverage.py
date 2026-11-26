"""The Deployments and Datasets pages: site/deployments/, site/datasets/<robot>/ (the Trajectory coverage dashboard).

    uv run --all-extras python tools/build_coverage.py build     # facts -> Deployments; traj_compare's workbench -> Datasets
    uv run --all-extras python tools/build_coverage.py check     # the committed pages against their sources (no writing)
    uv run --all-extras python tools/build_coverage.py pages     # only the host pages (index.html), from the committed rows
    uv run --all-extras python tools/build_coverage.py local     # outputs/coverage-site/: the site plus a .rrd per
                                                                 # trajectory and Open in Rerun, for traj_compare.serve

WHY (Zach, 2026-11-24, feedback/2026-11-24-deployments-then-datasets.md): datasets compare only within one kind of
deployment, so a page to pick a deployment (a stock data-ui table, and a gallery grouped by deployment type) comes before
the datasets' coverage, which opens filtered to what was picked; the coverage viewer is a stable part dropped in, never
copied. His ruling the same evening: the datasets go with the agent, since they are how the objective is computed.

What it writes, and from where (nothing is typed by hand; every number is read from the file named in its row's source):

- **site/deployments/** `deployments.json` (one row per robot, deployment and dataset, nested by `parent`),
  `deployments.base` (data-ui: a table, nested, and a gallery grouped by robot), `index.html`, `thumbs/`. The rows come
  from robot_controllers' arm registry (the robots: `bench.arms.ARM_MODULES`, each `ArmSpec.title`), the datasets in this
  repo (`datasets/<deployment>/<dataset>/<version>/`: in ruler v1 when OBJECTIVES.md §2 and §3 name them) and
  arm_motion_bench's frozen datasets (`datasets/*/*/v*/manifest.json` + `station.json`, its title table
  `playback.DEPLOYMENT_TITLES` / `DATASET_TITLES`), marked deferred (OBJECTIVES §5, specs/O5.2, O5.4) or not in the ruler.
- **site/datasets/<robot>/**: traj_compare's coverage workbench (`traj_compare.coverage.workbench.write_workbench`, its
  `coverage.base`, `trajectories.json` and `parts.json` as it writes them) over the ruler's datasets of that robot, run in
  traj_compare's own venv (this repo does not depend on traj_compare). `index.html` is this site's host page around the
  writer's one `<data-workbench src="coverage.base">` element: the site bar on top, the same element under it.
  Every trajectory's recording ships beside it (`rrd-<deployment>-<task>.rrd`, traj_compare's `write_trajectory_rrd`
  with `robot=`: robot_msgs' stock JointTrajectory viewer, the arm on the left, tabs of q / qd / qdd / qddd / % of limit /
  TCP on the right, no start / end ghosts), its record offering "Open in the Rerun web viewer" (app.rerun.io at the SDK
  version that wrote it, `?url=` the file on GitHub Pages) and the download. The arm is `robot/<deployment>.urdf`
  (tools/ruler_urdf.py: the ruler's own kinematics dressed in ur_description's meshes, BSD licence beside them); its tool
  is the ruler's tool point (OBJECTIVES §2). `rrd_inputs.json` digests what each file was written from, so a rebuild
  rewrites only the recordings whose inputs changed (tests/test_coverage_robot.py).
- **site/vendor/data-ui/**: data-ui at a pinned commit, vendored by data-ui's own `vendor` command with only the views
  these pages draw (table, cards, chart, coverage), shared by both pages (the writer's `kit=`).
- **The site bar** on both pages is the one include of the viewer's stock `<bb-site-nav>` reading site/nav.json
  (tools/site_bar.py; blackbox_agent viewer CONTRACT §18), which replaced lane CV's stage bar (site/stages/) on
  2026-11-24 (lane SHIP: Zach's pick, lane NAV's 01 Two rows). nav.json is hand-written; the build only checks it.

The pages are built here and committed, like the playback runs; CI does not rebuild them.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_bar  # noqa: E402  (tools/site_bar.py: the site bar's one include)

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
RULER_DATASETS = REPO / "datasets"
SIBLINGS = REPO.parent
ARM_MOTION_BENCH = Path(os.environ.get("TTA_ARM_MOTION_BENCH", SIBLINGS / "arm_motion_bench"))
TRAJ_COMPARE_PYTHON = Path(os.environ.get("TTA_TRAJ_COMPARE_PYTHON", SIBLINGS / "traj_compare" / ".venv" / "bin" / "python"))
DATA_UI = Path(os.environ.get("TTA_DATA_UI", SIBLINGS / "data-ui"))
LOCAL_OUT = REPO / "outputs" / "coverage-site"
PUBLIC_URL = "https://zacharyyamaoka.github.io/trajectory_tracking_agent/"

# data-ui at a pinned commit (main on 2026-11-25: the coverage views §52, the workbench §53, drill links keeping a
# relative path's '/', the rail's URL encoding a value once and the pills' labels at 4.5:1, lane COV2; then the
# leaderboard pivot §57 and its coverage amendment, 74be0c9a, lane MXDLIVE; then the charts §58, Ranks and the
# configurable Bars, merged as 8b9d364b, vendored at dbc89e48 (main), which the Model × Dataset page draws with, lane
# CHARTSLIVE).
# WHY pinned, not "main": a rebuild must not change the kit underneath the committed pages; bump it here on purpose.
DATA_UI_REF = "dbc89e48aa246e9f6998d248c85b2695feaeb854"
KIT = SITE / "vendor" / "data-ui"
KIT_VIEWS = ("table", "cards", "chart", "coverage")
# WHY these left out: like-obsidian/ (3.8 MB) opens a notes folder's record and python/ is the checker, neither used
# here; views/mesh.js (0.7 MB) draws 3-D model thumbnails, which no row has. The browser check counts 0 failed requests.
KIT_WITHOUT = ("like-obsidian/", "python/", "views/mesh.js")

STATUS_LABELS = {"ruler-v1": "In ruler v1", "deferred": "Deferred to ruler v2", "not-in-ruler": "Not in the ruler"}
SPLITS = ("dev", "holdout")
# What OBJECTIVES §5 defers. Each entry is checked: the spec exists with kind: deferred, its quoted requirement is in
# OBJECTIVES.md and names the word given here. A deferred deployment's datasets are deferred with it (O5.4 names the
# deployments); O5.2 names two datasets, so the deployment they live on is deferred with them, and its third dataset
# (the cell's Entire Workspace), which §5 does not name, is "not in the ruler".
DEFERRED_DEPLOYMENTS = {"bam_fb": ("O5.4", "BAM FB"), "pendulum": ("O5.4", "pendulum")}
DEFERRED_DATASETS = {("ur5e", "conveyor"): ("O5.2", "conveyor"), ("ur5e", "impact"): ("O5.2", "impact")}
# Dataset kinds as words for a page (the dataset's own keys stay in the rows)
WORKBENCH_TITLE = "{robot}: trajectory coverage"
THUMB_ASPECT = 0.62  # the gallery's picture well, height / width (the cards view's imageAspectRatio)


# ── small helpers ───────────────────────────────────────────────────────────────────────────────────────────────────


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_commit(directory: Path) -> str:
    result = subprocess.run(["git", "-C", str(directory), "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def write_json(path: Path, document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False, allow_nan=False) + "\n")


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


# ── the facts: robots, deployments, datasets, each read from its source ─────────────────────────────────────────────


def ruler_scope() -> dict:
    """The deployment and dataset ruler v1 names (OBJECTIVES §2, §3), and §5's text."""
    text = (REPO / "OBJECTIVES.md").read_text()
    deployment = re.search(r"^## 2\. Deployment v1: `([^`]+)`", text, re.M)
    dataset = re.search(r"^## 3\. The dataset v1: `([^`]+)`", text, re.M)
    deferred = re.search(r"^## 5\. .*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not (deployment and dataset and deferred):
        raise ValueError("OBJECTIVES.md no longer has §2 'Deployment v1', §3 'The dataset v1' and §5 as this build reads them")
    return {"deployment": deployment.group(1), "dataset": dataset.group(1), "section5": " ".join(deferred.group(1).split())}


def deferred_specs() -> dict[str, dict]:
    """specs/O5.*.md: id -> {kind, quote (the requirement's last quoted line), path}."""
    out = {}
    for path in sorted((REPO / "specs").glob("O5.*.md")):
        text = path.read_text()
        front = dict(re.findall(r"^(\w+): (.*)$", text.split("---")[1], re.M))
        quotes = [line[1:].strip() for line in text.split("## Requirement", 1)[-1].split("##", 1)[0].splitlines()
                  if line.startswith(">") and line[1:].strip()]
        out[front["id"]] = {"kind": front.get("kind"), "quote": quotes[-1] if quotes else "", "path": f"specs/{path.name}"}
    return out


def robot_registry() -> tuple[dict, str]:
    """robot_controllers' arms in ARM_MODULES order: name -> {title, joints, real_station, order}; and the source line."""
    import robot_controllers
    from robot_controllers.bench import arms as registry

    robots = {}
    for order, (name, _module) in enumerate(registry.ARM_MODULES):
        spec = registry.arm(name)
        robots[name] = {"title": spec.title, "joints": list(spec.joint_names), "real_station": spec.real_station,
                        "order": order}
    root = Path(robot_controllers.__file__).resolve().parents[2]
    return robots, "robot_controllers src/robot_controllers/bench/arms.py (ARM_MODULES, ArmSpec.title)"


def bench_titles() -> dict[str, dict[str, str]]:
    """arm_motion_bench's one title table (playback.py DEPLOYMENT_TITLES / DATASET_TITLES), read without importing it."""
    tree = ast.parse((ARM_MOTION_BENCH / "src" / "arm_motion_bench" / "playback.py").read_text())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("DEPLOYMENT_TITLES", "DATASET_TITLES"):
                found[node.targets[0].id] = ast.literal_eval(node.value)
    if set(found) != {"DEPLOYMENT_TITLES", "DATASET_TITLES"}:
        raise ValueError("arm_motion_bench playback.py no longer defines DEPLOYMENT_TITLES and DATASET_TITLES")
    return {"deployment": found["DEPLOYMENT_TITLES"], "dataset": found["DATASET_TITLES"]}


def _version(folder: Path) -> int:
    match = re.fullmatch(r"v(\d+)", folder.name)
    return int(match.group(1)) if match else -1


def dataset_records() -> list[dict]:
    """Every dataset's newest version: this repo's (the ruler's copies) first, then arm_motion_bench's that this repo
    does not hold. Each: deployment, dataset, version, key, manifest facts, station title and module, source, origin."""
    records: dict[tuple[str, str], dict] = {}

    def read(manifest_path: Path, root: Path, origin: str) -> dict:
        manifest = json.loads(manifest_path.read_text())
        folder = manifest_path.parent
        station = json.loads((folder / "station.json").read_text())
        relative = folder.relative_to(root).as_posix()
        return {
            "deployment": manifest["robot"], "dataset": manifest["dataset"], "version": manifest["version"],
            "key": f"{manifest['robot']}/{manifest['dataset']}/{manifest['version']}",
            "dev": int(manifest["counts"]["dev"]["total"]), "holdout": int(manifest["counts"]["holdout"]["total"]),
            "duration_s": round(float(manifest["duration_rung_1_s"]["dev"]) + float(manifest["duration_rung_1_s"]["holdout"]), 2),
            "kinds": sorted(set(manifest["counts"]["dev"]["by_kind"]) | set(manifest["counts"]["holdout"]["by_kind"])),
            "scene": station["title"], "station_module": manifest["station"]["module"],
            "tasks_sha256": manifest["tasks_sha256"], "origin": origin,
            "source": f"{relative}/manifest.json" if origin == "tta" else f"arm_motion_bench {relative}/manifest.json",
        }

    for manifest_path in sorted(RULER_DATASETS.glob("*/*/v*/manifest.json")):
        record = read(manifest_path, REPO, "tta")
        records[(record["deployment"], record["dataset"])] = record
    if not (ARM_MOTION_BENCH / "datasets").is_dir():
        raise FileNotFoundError(f"no arm_motion_bench checkout at {ARM_MOTION_BENCH} (set TTA_ARM_MOTION_BENCH)")
    newest: dict[tuple[str, str], Path] = {}
    for manifest_path in ARM_MOTION_BENCH.glob("datasets/*/*/v*/manifest.json"):
        pair = (manifest_path.parents[2].name, manifest_path.parents[1].name)
        if pair not in newest or _version(manifest_path.parent) > _version(newest[pair].parent):
            newest[pair] = manifest_path
    for pair, manifest_path in sorted(newest.items()):
        if pair in records:
            # the ruler's copy is the bench's dataset (its manifest has private paths redacted, so compare the tasks)
            bench = json.loads(manifest_path.read_text())
            if records[pair]["version"] == bench["version"] and records[pair]["tasks_sha256"] != bench["tasks_sha256"]:
                raise ValueError(f"datasets/{records[pair]['key']}: its tasks differ from arm_motion_bench's")
            continue
        records[pair] = read(manifest_path, ARM_MOTION_BENCH, "arm_motion_bench")
    return list(records.values())


def robot_of(deployment: str, station_module: str, robots: dict) -> str:
    """A deployment's robot: the arm whose real_station it is, else the arm named by its station module (robots.ur5e)."""
    for name, robot in robots.items():
        if robot["real_station"] == deployment:
            return name
    name = station_module.rsplit(".", 1)[-1]
    if name in robots:
        return name
    raise ValueError(f"deployment {deployment!r}: no robot_controllers arm has it as real_station or is named {name!r}")


def _quote(spec_id: str, word: str, specs: dict, scope: dict) -> str:
    spec = specs.get(spec_id)
    if not spec or spec["kind"] != "deferred":
        raise ValueError(f"{spec_id}: no specs/{spec_id}-*.md with kind: deferred")
    if word.lower() not in spec["quote"].lower() or spec["quote"] not in scope["section5"]:
        raise ValueError(f"{spec_id}: its quote {spec['quote']!r} is not OBJECTIVES §5's or does not name {word!r}")
    return spec["quote"]


def facts(workbench: dict[str, list[dict]] | None = None) -> list[dict]:
    """The rows of site/deployments/deployments.json. `workbench`: robot -> the rows of its trajectories.json (what the
    Datasets page holds), for the in-workbench counts and links; None reads them from site/datasets/."""
    scope = ruler_scope()
    specs = deferred_specs()
    robots, robots_source = robot_registry()
    titles = bench_titles()
    records = dataset_records()
    if workbench is None:
        workbench = {path.parent.name: json.loads(path.read_text())["rows"]
                     for path in sorted((SITE / "datasets").glob("*/trajectories.json"))}

    def in_ruler(record: dict) -> bool:
        return record["origin"] == "tta" and record["key"] == scope["dataset"] and record["deployment"] == scope["deployment"]

    deployments: dict[str, dict] = {}
    for record in records:
        record["robot"] = robot_of(record["deployment"], record["station_module"], robots)
        entry = deployments.setdefault(record["deployment"], {"robot": record["robot"], "datasets": [], "scene": record["scene"]})
        if entry["scene"] != record["scene"]:
            raise ValueError(f"deployment {record['deployment']!r}: two scenes ({entry['scene']!r}, {record['scene']!r})")
        entry["datasets"].append(record)
    for name, robot in robots.items():  # a robot robot_controllers defines with no station anywhere: its base scenario
        if not any(entry["robot"] == name for entry in deployments.values()):
            deployments[name] = {"robot": name, "datasets": [], "scene": None, "scenario_only": True}

    def coverage_href(robot: str, deployment: str | None = None, dataset: str | None = None) -> str | None:
        rows = workbench.get(robot)
        if not rows:
            return None
        query = {}
        if deployment:
            if not any(row.get("deployment") == deployment for row in rows):
                return None
            query["deployment"] = deployment
        if dataset:
            if not any(row.get("dataset") == dataset for row in rows):
                return None
            query["dataset"] = dataset
        # WHY safe="/": the dataset id reads as itself in the address bar (data-ui reads ?dataset= back either way)
        return f"../datasets/{robot}/" + (f"?{urlencode(query, safe='/')}" if query else "")

    def held(robot: str, **match) -> int:
        return sum(all(row.get(k) == v for k, v in match.items()) for row in workbench.get(robot, []))

    rows: list[dict] = []
    robot_order = sorted(robots, key=lambda name: (
        0 if any(in_ruler(r) for d in deployments.values() if d["robot"] == name for r in d["datasets"]) else
        1 if any(d_name in DEFERRED_DEPLOYMENTS or any((d_name, r["dataset"]) in DEFERRED_DATASETS for r in d["datasets"])
                 for d_name, d in deployments.items() if d["robot"] == name) else 2,
        robots[name]["order"]))
    order = 0
    for robot_name in robot_order:
        robot = robots[robot_name]
        mine = {name: entry for name, entry in deployments.items() if entry["robot"] == robot_name}
        robot_row = {"id": f"robot:{robot_name}", "name": robot["title"], "level": "Robot", "key": robot_name,
                     "parent": None, "robot": robot_name, "order": order, "source": robots_source}
        rows.append(robot_row)
        order += 1
        robot_children = []
        live_datasets = 0
        for deployment_name, entry in sorted(mine.items(), key=lambda item: (
                not any(in_ruler(r) for r in item[1]["datasets"]), item[0])):
            datasets = sorted(entry["datasets"], key=lambda r: (not in_ruler(r), r["dataset"] != "workspace", r["dataset"]))
            if entry.get("scenario_only"):
                status, spec, why = ("not-in-ruler", None,
                                     "Not named in OBJECTIVES: robot_controllers defines this robot and its base scenario "
                                     "(rate, bus, boards); no frozen dataset of it exists")
                name = f"{robot['title'].split(' (')[0]}, robot_controllers' base scenario"
                source = robots_source
                scene = None
            else:
                name = titles["deployment"].get(deployment_name, deployment_name)
                scene = entry["scene"]
                deferred_here = [DEFERRED_DATASETS[(deployment_name, r["dataset"])] for r in datasets
                                 if (deployment_name, r["dataset"]) in DEFERRED_DATASETS]
                if deployment_name == scope["deployment"]:
                    status, spec, why = "ruler-v1", None, "OBJECTIVES §2: ruler v1's one deployment"
                elif deployment_name in DEFERRED_DEPLOYMENTS:
                    spec, word = DEFERRED_DEPLOYMENTS[deployment_name]
                    status, why = "deferred", f"OBJECTIVES §5 ({spec}): “{_quote(spec, word, specs, scope)}”"
                elif deferred_here:
                    spec, word = deferred_here[0]
                    status, why = "deferred", (f"OBJECTIVES §5 ({spec}): “{_quote(spec, word, specs, scope)}”, which "
                                               "live on this deployment")
                else:
                    status, spec, why = "not-in-ruler", None, f"Not named in OBJECTIVES; ruler v1's one deployment is {scope['deployment']}"
                source = "; ".join(dict.fromkeys(r["source"].rsplit("/", 1)[0] + "/station.json" if r["origin"] == "tta"
                                                 else r["source"].replace("manifest.json", "station.json") for r in datasets))
            deployment_row = {"id": f"deployment:{deployment_name}", "name": name, "level": "Deployment",
                              "key": deployment_name, "parent": robot_row["id"], "robot": robot_name, "scene": scene,
                              "status": status, "spec": spec, "why": why, "order": order, "source": source}
            rows.append(deployment_row)
            order += 1
            children = []
            for record in datasets:
                if in_ruler(record):
                    d_status, d_spec, d_why = "ruler-v1", None, "OBJECTIVES §3: ruler v1's one dataset"
                elif (record["deployment"], record["dataset"]) in DEFERRED_DATASETS or record["deployment"] in DEFERRED_DEPLOYMENTS:
                    d_spec, word = (DEFERRED_DATASETS.get((record["deployment"], record["dataset"]))
                                    or DEFERRED_DEPLOYMENTS[record["deployment"]])
                    d_status, d_why = "deferred", f"OBJECTIVES §5 ({d_spec}): “{_quote(d_spec, word, specs, scope)}”"
                else:
                    d_status, d_spec = "not-in-ruler", None
                    d_why = f"Ruler v1 has one dataset, {scope['dataset']} (OBJECTIVES §3); §5 does not name this one"
                count = held(robot_name, deployment=record["deployment"], dataset=record["key"])
                dataset_row = {
                    "id": f"dataset:{record['key']}", "name": titles["dataset"].get(record["dataset"], record["dataset"]),
                    "level": "Dataset", "key": record["key"], "parent": deployment_row["id"], "robot": robot_name,
                    "status": d_status, "spec": d_spec, "why": d_why, "datasets": 1, "dev": record["dev"],
                    "holdout": record["holdout"], "trajectories": record["dev"] + record["holdout"],
                    "duration_s": record["duration_s"], "kinds": ", ".join(record["kinds"]), "in_workbench": count,
                    "coverage": coverage_href(robot_name, record["deployment"], record["key"]) if count else None,
                    "order": order, "source": record["source"],
                }
                rows.append(dataset_row)
                children.append(dataset_row)
                order += 1
            live = sum(row["in_workbench"] for row in children)
            live_datasets += sum(1 for row in children if row["status"] == "ruler-v1")
            deployment_row.update(_totals(children), in_workbench=live,
                                  coverage=coverage_href(robot_name, deployment_name) if live else None)
            robot_children.append(deployment_row)
        live = sum(row["in_workbench"] for row in robot_children)
        statuses = {row["status"] for row in robot_children}
        status = next(s for s in ("ruler-v1", "deferred", "not-in-ruler") if s in statuses)
        spec_ids = sorted({row["spec"] for row in robot_children if row["spec"]}) if status == "deferred" else []
        if status == "ruler-v1":
            why = (f"Ruler v1 scores {live_datasets} of its {sum(r['datasets'] for r in robot_children)} datasets "
                   f"(OBJECTIVES §2–§3); the rest are not in the ruler yet")
        elif status == "deferred":
            why = next(row["why"] for row in robot_children if row["status"] == "deferred")
        else:
            why = robot_children[0]["why"]
        robot_row.update(_totals(robot_children), deployments=len(robot_children), status=status,
                         spec=", ".join(spec_ids) or None, why=why, in_workbench=live,
                         coverage=coverage_href(robot_name) if live else None)
    for row in rows:
        row["status_label"] = STATUS_LABELS[row["status"]]
        # the gallery: every deployment, and a robot whose datasets page exists ("All <robot>")
        row["card"] = "yes" if row["level"] == "Deployment" or (row["level"] == "Robot" and row["coverage"]) else None
        row["thumb"] = thumb_name(row)
    return rows


def provenance() -> dict:
    """The commits the rows were read at (kept beside the rows, so a later commit there does not change a row)."""
    import robot_controllers

    return {"robot_controllers": git_commit(Path(robot_controllers.__file__).resolve().parents[2]),
            "arm_motion_bench": git_commit(ARM_MOTION_BENCH), "data_ui": DATA_UI_REF[:7]}


def _totals(children: list[dict]) -> dict:
    total = lambda key: sum(row.get(key) or 0 for row in children)  # noqa: E731
    return {"datasets": total("datasets"), "dev": total("dev"), "holdout": total("holdout"),
            "trajectories": total("trajectories"), "duration_s": round(total("duration_s"), 2)}


def thumb_name(row: dict) -> str | None:
    """A gallery card's picture: the tool from above (from the workbench) when the row is on the Datasets page, else a
    placeholder that says why it is not."""
    if row["card"] != "yes":
        return None
    key = row["key"].replace("/", "-")
    return f"thumbs/{row['level'].lower()}-{key}.png" if row["coverage"] else f"thumbs/{row['level'].lower()}-{key}.svg"


# ── the Deployments page ────────────────────────────────────────────────────────────────────────────────────────────

PAGE_CSS = """
  /* WHY --page-*: data-ui reads shadcn's token names from its host (--muted = a soft background, --accent = a hover
     fill; site/vendor/data-ui/data-ui.css), so a host --muted text grey painted the "Showing" pills, the count, the
     picked view tab and the group bands grey on grey (lane COV2, 2026-11-25). The page's own colours never use those names. */
  :root { --bg: #f7f7f5; --surface: #ffffff; --surface-2: #f0f1ef; --ink: #1b1e23; --page-muted: #5e6570; --line: #e1e3e1;
    --page-accent: #2c64d1; --page-accent-soft: #2c64d11f; --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; color-scheme: light dark; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #111317; --surface: #181b20; --surface-2: #1f2329; --ink: #e6e8eb; --page-muted: #a0a7b1; --line: #2a2f36;
      --page-accent: #6c9cf0; --page-accent-soft: #6c9cf026; }
  }
  html, body { margin: 0; }
  body { background: var(--bg); color: var(--ink); font: 14px/1.45 var(--sans); }
  .page-head { padding: 14px 16px 10px; max-width: 1400px; }
  .page-head h1 { margin: 0 0 4px; font-size: 20px; }
  .page-head p { margin: 0; color: var(--page-muted); max-width: 980px; }
  .page-head p + p { margin-top: 4px; }
  .page-head p.small, .page-head details.small { font-size: 12.5px; color: var(--page-muted); }
  .page-head details.small { margin-top: 4px; max-width: 980px; }
  .page-head details.small summary { cursor: pointer; width: max-content; }
  .page-head a { color: var(--page-accent); }
  .page-head code { font: 12.5px var(--mono); }
  .notice { margin: 8px 0 0; padding: 8px 12px; border: 1px solid var(--line); border-left: 3px solid var(--page-muted);
    border-radius: 6px; background: var(--surface); color: var(--ink); max-width: 980px; }
  .notice[hidden] { display: none; }
  main { padding: 0 16px 16px; min-width: 0; }
"""

DEPLOYMENTS_HTML = """<!doctype html>
<!-- GENERATED by tools/build_coverage.py (never edit; rebuild): the Deployments page, data-ui's stock <data-views> over
     deployments.base, the site bar on top. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deployments · Trajectory Tracking Agent</title>
<meta name="description" content="Every deployment (a robot and its scene) and its datasets: what ruler v1 scores, what is deferred and why. Pick one to open its datasets' trajectory coverage.">
<link rel="stylesheet" href="../vendor/data-ui/data-ui.css">
<style>{css}
  data-views {{ display: block; }}
</style>
</head>
<body>
<div id="frame">
{bar}
<header class="page-head">
  <h1>Deployments</h1>
  <p>{lede}</p>
  <p class="small">{legend}</p>
</header>
</div>
<main>
<data-views id="deployments" src="deployments.base" view="Gallery" frame="page" aria-label="Deployments and their datasets"></data-views>
</main>
<script type="module" src="../vendor/data-ui/data-ui.js"></script>
</body>
</html>
"""

DEPLOYMENTS_BASE_HEADER = """# The Deployments page: one row per robot, deployment and dataset (deployments.json), two views over the same rows.
# GENERATED by tools/build_coverage.py from robot_controllers, this repo's datasets and arm_motion_bench's (each row's
# source names its file): change the build, never this file.
# WHY a gallery grouped by robot and a table (Zach, 2026-11-24; feedback/2026-11-24-deployments-then-datasets.md): a stock
# data-ui table, and a gallery grouped by deployment type; McMaster-Carr's category page (a heading per group, a grid of
# picture tiles with names) is his reference.
"""


def deployments_base(rows: list[dict], robots: dict) -> dict:
    order = list(dict.fromkeys(row["robot"] for row in rows))
    return {
        "data": "deployments.json",
        "facets": [
            {"property": "robot", "as": "nav", "label": "Choose a robot", "clear": True},
            {"property": "status_label", "label": "In the ruler?"},
        ],
        "properties": {
            "name": {"displayName": "Name"}, "level": {"displayName": "Level"}, "key": {"displayName": "Key"},
            "robot": {"displayName": "Robot"},
            # WHY green and grey: in the ruler is the one state that is scored; the rest are listed, never alarming
            "status_label": {"displayName": "In the ruler?", "colors": {STATUS_LABELS["ruler-v1"]: 6,
                                                                          STATUS_LABELS["deferred"]: 0,
                                                                          STATUS_LABELS["not-in-ruler"]: 0}},
            "spec": {"displayName": "Spec"}, "why": {"displayName": "Why"},
            "datasets": {"displayName": "Datasets"}, "trajectories": {"displayName": "Trajectories"},
            "in_workbench": {"displayName": "On the Datasets page"},
        },
        "open": {"mode": "link", "url": "coverage"},
        "views": [
            {"type": "cards", "name": "Gallery", "filters": 'card == "yes"', "groupBy": {"property": "robot"},
             "groupOrder": order, "sections": True, "sort": [{"property": "order", "direction": "ASC"}],
             "image": "thumb", "imageFit": "contain", "imageAspectRatio": THUMB_ASPECT, "cardSize": 230,
             "order": ["name", "level", "key", "status_label", "datasets", "trajectories", "in_workbench"]},
            {"type": "table", "name": "Table", "tree": {"parent": "parent"}, "fold": "open",
             "columnSize": {"name": 250, "key": 200, "status_label": 150, "why": 460, "source": 420, "scene": 360},
             "sort": [{"property": "order", "direction": "ASC"}],
             "order": ["name", "level", "key", "status_label", "spec", "datasets", "dev", "holdout", "trajectories",
                       "duration_s", "in_workbench", "scene", "why", "source"],
             "display": {"status_label": "badge"}},
        ],
    }


def deployments_document(rows: list[dict], robots: dict) -> dict:
    text = lambda label, **extra: {"type": "text", "label": label, **extra}  # noqa: E731
    number = lambda label, **extra: {"type": "number", "label": label, **extra}  # noqa: E731
    return {
        "id": "tta-deployments",
        "title": "Deployments and their datasets",
        "titleProperty": "name",
        "linkProperty": "coverage",
        "imageProperty": "thumb",
        "source": "tools/build_coverage.py: robot_controllers' arm registry, this repo's datasets/ (ruler v1) and "
                  "arm_motion_bench's frozen datasets; every row's source names its file",
        "provenance": provenance(),
        "properties": {
            "id": text("Row", hidden=True),
            "name": text("Name"),
            "level": text("Level", description="Robot (a robot_controllers arm) > Deployment (the robot and its "
                                               "scene) > Dataset (a deployment and a task family)"),
            "key": text("Key"),
            "parent": text("Parent", hidden=True),
            "robot": text("Robot", labels={name: robot["title"] for name, robot in robots.items()}),
            "scene": text("Scene"),
            "status": text("Status key", hidden=True),
            "status_label": text("In the ruler?"),
            "spec": text("Spec", description="the specs/ note that defers it (OBJECTIVES §5)"),
            "why": text("Why"),
            "deployments": number("Deployments", hidden=True),
            "datasets": number("Datasets"),
            "dev": number("Dev", description="dev tasks at speed 1.0, from the dataset's manifest"),
            "holdout": number("Holdout", description="holdout tasks at speed 1.0, from the dataset's manifest"),
            "trajectories": number("Trajectories", description="dev + holdout at speed 1.0 (one trajectory per task)"),
            "duration_s": number("Duration", unitText="s", decimals=1, description="dev + holdout at speed 1.0"),
            "kinds": text("Task kinds"),
            "in_workbench": number("On the Datasets page", description="trajectories the Datasets page's coverage "
                                                                       "workbench holds (the ruler's datasets only)"),
            "coverage": text("Datasets page", hidden=True),
            "thumb": text("Picture", hidden=True),
            "card": text("In the gallery", hidden=True),
            "order": number("Order", hidden=True),
            "source": text("Source"),
        },
        "rows": rows,
    }


def write_deployments_host(rows: list[dict]) -> None:
    """site/deployments/index.html from the rows (also `pages`: from the committed deployments.json, no traj_compare)."""
    out = SITE / "deployments"
    live = [row for row in rows if row["level"] == "Dataset" and row["status"] == "ruler-v1"]
    deployments = [row for row in rows if row["level"] == "Deployment"]
    datasets = [row for row in rows if row["level"] == "Dataset"]
    lede = (f"A deployment is a robot and its scene; a dataset is a deployment and a task family. "
            f"{len(deployments)} deployments, {len(datasets)} datasets. Ruler v1 scores "
            + ", ".join(f"<code>{html.escape(row['key'])}</code>" for row in live)
            + ": open a robot or a deployment to see its datasets' trajectory coverage.")
    legend = ("The ones not in the ruler stay listed, greyed, with the reason (OBJECTIVES §5; specs O5.2 and O5.4); "
              "they have no Datasets page yet. Gallery and Table are two views of the same rows.")
    page = out / "index.html"
    page.write_text(DEPLOYMENTS_HTML.format(css=PAGE_CSS, lede=lede, legend=legend, bar=site_bar.tag(page, "coverage")))


def write_deployments(rows: list[dict], robots: dict) -> None:
    out = SITE / "deployments"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "deployments.json", deployments_document(rows, robots))
    (out / "deployments.base").write_text(DEPLOYMENTS_BASE_HEADER + _yaml(deployments_base(rows, robots)) + "\n")
    write_deployments_host(rows)
    thumbs = out / "thumbs"
    thumbs.mkdir(exist_ok=True)
    for row in rows:
        if row["thumb"] and row["thumb"].endswith(".svg"):
            (out / row["thumb"]).write_text(placeholder_svg(row))


def placeholder_svg(row: dict) -> str:
    """A greyed card picture for a row with no Datasets page: its status and spec, in the page's light or dark."""
    line1 = html.escape(row["status_label"])
    if row["spec"]:
        line2 = f"OBJECTIVES §5 · {row['spec']}"
    elif row.get("datasets"):
        line2 = f"{row['datasets']} dataset{'s' if row['datasets'] != 1 else ''}, not scored"
    else:
        line2 = "no frozen dataset"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200" width="320" height="200">
<style>
  .bg {{ fill: #f0f1ef; stroke: #b9bec5; }} .t {{ fill: #5e6570; font: 600 17px system-ui, sans-serif; }}
  .s {{ fill: #5e6570; font: 14px system-ui, sans-serif; }}
  @media (prefers-color-scheme: dark) {{ .bg {{ fill: #1f2329; stroke: #3a4049; }} .t, .s {{ fill: #a0a7b1; }} }}
</style>
<rect class="bg" x="2" y="2" width="316" height="196" rx="12" stroke-width="2" stroke-dasharray="7 6"/>
<text class="t" x="160" y="96" text-anchor="middle">{line1}</text>
<text class="s" x="160" y="122" text-anchor="middle">{line2}</text>
</svg>
"""


# ── a small YAML writer (a .base is YAML; flow mappings keep a facet or a view key on one line) ────────────────────

_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .·×/-]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"}


def _scalar(value) -> str:
    if value is None:
        return "null"
    if value is True or value is False:
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value)
    text = str(value)
    if _PLAIN.match(text) and text.lower() not in _RESERVED and not text.endswith(" ") and ": " not in text:
        return text
    return "'" + text.replace("'", "''") + "'"


def _flow(value) -> str:
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_scalar(k)}: {_flow(v)}" for k, v in value.items()) + " }" if value else "{}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    return _scalar(value)


def _yaml(value, indent: int = 0) -> str:
    pad = " " * indent
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, dict | list) and item and len(_flow(item)) > 100:
                lines.append(f"{pad}{_scalar(key)}:")
                lines.append(_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}{_scalar(key)}: {_flow(item)}")
    else:
        for item in value:
            if isinstance(item, dict) and len(_flow(item)) > 100:
                block = _yaml(item, indent + 2)
                lines.append(f"{pad}- {block.lstrip()}")
            else:
                lines.append(f"{pad}- {_flow(item)}")
    return "\n".join(lines)


# ── the Datasets page: traj_compare's workbench, run in traj_compare's venv ─────────────────────────────────────────


def workbench_main(argv: list[str]) -> None:
    """`workbench` (runs in traj_compare's venv): analyze() + write_workbench() over this repo's datasets of one robot,
    then the gallery pictures (the tool from above, per deployment and for the robot) from the parts it wrote."""
    parser = argparse.ArgumentParser(prog="build_coverage.py workbench")
    parser.add_argument("--robot", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--dataset", action="append", required=True, help="<deployment>/<dataset>/<version>, repeatable")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kit", required=True, help="the vendored data-ui kit's href, relative to --out")
    parser.add_argument("--thumbs", type=Path, required=True)
    parser.add_argument("--rrd", action="store_true", help="also write a .rrd per trajectory and the record's Rerun actions")
    parser.add_argument("--urdf", action="append", default=[],
                        help="<deployment>=<path>: draw that deployment's trajectories as this URDF arm (repeatable; with --tools)")
    parser.add_argument("--tools", type=Path, default=None,
                        help="the ruler's tool poses per trajectory in the URDF's root (an .npz the build writes)")
    parser.add_argument("--public-url", default=None)
    parser.add_argument("--served-at", default="")
    parser.add_argument("--rerun-server", action="store_true")
    args = parser.parse_args(argv)

    import numpy as np
    from robot_msgs import load_npz
    from robot_msgs.geometry.rotations import quat_from_matrix
    from robot_msgs.std import Header
    from robot_msgs.trajectory import PoseTrajectory
    from traj_compare.coverage import analyze
    from traj_compare.coverage.workbench import write_workbench

    urdfs = dict(item.split("=", 1) for item in args.urdf)
    trajectories, tools, tags, rrd, tape_digest = {}, {}, {}, {}, {}
    counts = {}
    for key in args.dataset:
        folder = RULER_DATASETS / key
        listed = json.loads((folder / "tapes_manifest.json").read_text())["files"]
        deployment = key.split("/")[0]
        rows = sorted(read_rows(folder / "tasks.jsonl"), key=lambda r: (SPLITS.index(r["split"]), r["order"], r["task_id"]))
        for row in rows:
            tape = folder / "tapes" / f"{row['task_id']}.npz"
            # fail closed, as `tta verify`: a tape that is not the frozen one is never drawn
            if sha256(tape) != listed.get(f"tapes/{tape.name}"):
                raise ValueError(f"{tape.relative_to(REPO)}: sha256 differs from tapes_manifest.json")
            trajectory = load_npz(tape)
            with np.load(tape) as arrays:
                position, rotation = np.asarray(arrays["tcp_pos"], float), np.asarray(arrays["tcp_rot"], float)
            name = f"{deployment}/{row['task_id']}"
            trajectories[name] = trajectory
            # WHY the tape's own TCP: the dataset's station TCP (flange + 0.144 m) is what arm_motion_bench's workbench
            # bins, so a dataset's coverage reads the same on both; the ruler scores the flange + 0.1 m (OBJECTIVES §2)
            tools[name] = PoseTrajectory(t=np.asarray(trajectory.t, float), positions=position,
                                         orientations=quat_from_matrix(rotation), header=Header(frame_id="base"))
            tags[name] = {"deployment": deployment, "dataset": key, "split": row["split"], "kind": row["kind"]}
            # WHY a flat file name: the record's "Download the .rrd" fills {rrd} URL-encoded, so a "/" would reach a
            # static host as %2F, which GitHub Pages does not read as a folder
            rrd[name] = f"rrd-{deployment}-{row['task_id']}.rrd"
            tape_digest[name] = listed[f"tapes/{tape.name}"]
        counts[key] = len(rows)
    n = len(trajectories)
    subtitle = (f"{len(args.dataset)} dataset{'s' if len(args.dataset) != 1 else ''} in ruler v1 · dev + holdout at speed "
                f"1.0 · {n} trajectories · tool = the dataset's TCP (flange + 0.144 m), base frame")
    # WHY explicit: these are the ruler's original full-speed tapes. Instantaneous joint speed cannot identify a tape's scale.
    coverage = analyze(trajectories, tool=tools, tags=tags, group_by="dataset", title=args.title, subtitle=subtitle,
                       speed_scales=dict.fromkeys(trajectories, 1.0))
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    for stale in [*out.glob("rrd-*.rrd"), out / "embed.html"]:
        if stale.exists() and not (args.rrd and stale.name in rrd.values()):
            stale.unlink()
    written = write_recordings(out, rrd, trajectories, tags, tape_digest, urdfs, args.tools) if args.rrd else {}
    # WHY pages=False: this site brings its own page around the writer's one <data-workbench src="coverage.base">
    # (write_datasets_host); WHY no Rerun server: GitHub Pages is static, so a record offers the Rerun web viewer at the
    # SDK version that wrote the file (public_url: where Pages serves out_dir) and the download
    write_workbench(coverage, trajectories, out, tool=tools, title=args.title, subtitle=subtitle,
                    rrd_for=rrd if args.rrd else None, dataset="dataset", facets=("split", "kind"), lead=("deployment",),
                    kit=args.kit, public_url=args.public_url if args.rrd else None,
                    rerun_server=bool(args.rrd and args.rerun_server), served_at=args.served_at, pages=False)
    import traj_compare

    write_json(out / "build.json", {"traj_compare": git_commit(Path(traj_compare.__file__).resolve().parents[2]),
                                    "data_ui": DATA_UI_REF})
    pictures = write_thumbs(out / "parts.json", out / "trajectories.json", args.thumbs, args.robot)
    print(json.dumps({"trajectories": n, "datasets": counts, "thumbs": pictures, **written,
                      "rrd_bytes": sum((out / p).stat().st_size for p in rrd.values()) if args.rrd else 0}))


RRD_INPUTS = "rrd_inputs.json"
PREVIOUS_WORKBENCH_SHA = "40862996254f43e975de00a30ac81aad71624c57a7f99d39fd8d13ccd781f4a7"
PREVIOUS_RRD_WRITER_SHA = "cee135d8f92df82f823b17ddb96080caa3343e10225d418bc8fd2cee1675cb4a"


def _viewer_sources() -> dict:
    """What decides a recording's bytes besides its inputs: the Rerun SDK and the two files that write it (robot_msgs'
    stock viewer, traj_compare's write_trajectory_rrd), by content. A change to either rewrites every .rrd; nothing else
    does. WHY not their git commits: an unrelated commit in either repo would rewrite all 54 files (seen 2026-11-25)."""
    import rerun
    import robot_msgs.viz.rerun as viewer
    from traj_compare.coverage.workbench import write_trajectory_rrd

    return {"rerun_sdk": rerun.__version__, "robot_msgs.viz.rerun": sha256(Path(viewer.__file__)),
            "traj_compare.write_trajectory_rrd": hashlib.sha256(inspect.getsource(write_trajectory_rrd).encode()).hexdigest()}


def write_recordings(out: Path, rrd: dict, trajectories: dict, tags: dict, tape_digest: dict, urdfs: dict,
                     tools_npz: Path | None) -> dict:
    """One .rrd per trajectory: robot_msgs' stock JointTrajectory viewer (traj_compare's write_trajectory_rrd with
    robot=), the deployment's URDF arm on the left, the ruler's tool point as its tool, no start / end ghosts.

    WHY only what changed is rewritten: a recording's bytes differ on every write (Rerun stamps ids and times), and the
    54 files are ~90 MB of a public repo's history; so each file's inputs (its tape, the URDF folder, the tool poses, the
    viewer's sources) are digested into rrd_inputs.json and an unchanged file is kept. Every file written is read back
    with Rerun's own reader and refused if any string in it names a private path."""
    import numpy as np
    from robot_msgs.geometry.rotations import quat_from_matrix
    from robot_msgs.std import Header
    from robot_msgs.trajectory import PoseTrajectory
    from traj_compare.coverage.workbench import write_trajectory_rrd

    if tools_npz is None or not urdfs:
        raise SystemExit("workbench --rrd needs --urdf <deployment>=<path> and --tools (the build passes both)")
    viewer = _viewer_sources()
    folder_digest = {}
    for deployment, urdf in urdfs.items():
        folder = Path(urdf).parent
        folder_digest[deployment] = hashlib.sha256("".join(
            f"{p.relative_to(folder).as_posix()}:{sha256(p)}\n" for p in sorted(folder.rglob("*")) if p.is_file()
        ).encode()).hexdigest()
    with np.load(tools_npz) as arrays:
        names = json.loads(str(arrays["names"]))
        poses = {name: (arrays[f"t_{i}"], arrays[f"p_{i}"], arrays[f"R_{i}"]) for i, name in enumerate(names)}
    record_path = out / RRD_INPUTS
    before = json.loads(record_path.read_text())["files"] if record_path.exists() else {}
    old_viewer = None
    # WHY migrate both hashes: the robot= writer delegates to robot_msgs. Coverage HTML edits in its old module do
    # not change the recording. Reuse old bytes only if this exact writer, robot_msgs, SDK, and recording inputs match.
    if viewer["traj_compare.write_trajectory_rrd"] == PREVIOUS_RRD_WRITER_SHA:
        old_viewer = {key: val for key, val in viewer.items() if key != "traj_compare.write_trajectory_rrd"}
        old_viewer["traj_compare.coverage.workbench"] = PREVIOUS_WORKBENCH_SHA
    files, wrote, kept = {}, [], []
    for name, file in rrd.items():
        deployment = tags[name]["deployment"]
        t, positions, rotations = poses[name]
        inputs = {
            "name": name, "tape": tape_digest[name], "robot": folder_digest[deployment], "ghosts": False,
            "tool": hashlib.sha256(b"".join(np.ascontiguousarray(a, dtype="<f8").tobytes() for a in (t, positions, rotations))).hexdigest(),
            "viewer": viewer,
        }
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        files[file] = digest
        old_digest = (hashlib.sha256(json.dumps({**inputs, "viewer": old_viewer}, sort_keys=True).encode()).hexdigest()
                      if old_viewer else None)
        if before.get(file) in (digest, old_digest) and file in before and (out / file).exists():
            kept.append(file)
            continue
        # the ruler's tool point (OBJECTIVES §2), in the URDF's root link: the arm's tool path and its TCP tab
        tool = PoseTrajectory(t=np.asarray(t, float), positions=np.asarray(positions, float),
                              orientations=quat_from_matrix(np.asarray(rotations, float)), header=Header(frame_id=""))
        write_trajectory_rrd(out / file, name, trajectories[name], tool=tool, robot=urdfs[deployment], ghosts=False)
        hits = rrd_private_hits(out / file)
        if hits:
            (out / file).unlink()
            raise SystemExit(f"{file}: private strings in the recording: {hits[:5]}")
        wrote.append(file)
    write_json(record_path, {
        "about": "what each .rrd was written from (tools/build_coverage.py write_recordings): a file whose digest still "
                 "matches its inputs is kept, never rewritten",
        **viewer, "ghosts": False, "robot": {d: f"robot/{Path(u).name}" for d, u in urdfs.items()}, "files": files})
    return {"rrd_written": len(wrote), "rrd_kept": len(kept)}


def rrd_private_hits(path: Path) -> list[str]:
    """Every string a recording holds (entity paths, string columns, field metadata; Rerun's own reader) and its raw
    bytes, against PRIVATE. Runs in traj_compare's venv (rerun)."""
    from rerun.chunk import RrdReader

    # the raw bytes (latin-1, so every byte is one character) against the paths only: an e-mail-shaped run of bytes
    # can occur by chance in compressed data
    raw = sorted({match.group(0) for match in PRIVATE_PATHS.finditer(path.read_bytes().decode("latin-1"))})
    strings = set()
    for chunk in RrdReader(path).stream():
        strings.add(chunk.entity_path)
        batch = chunk.to_record_batch()
        for field, column in zip(batch.schema, batch.columns, strict=True):
            strings.add(field.name)
            strings.update(f"{k!r}={v!r}" for k, v in (field.metadata or {}).items())
            if "string" in str(column.type) or "utf8" in str(column.type):
                strings.update(str(value) for value in column.to_pylist())
    return raw + sorted({match.group(0) for text in strings for match in PRIVATE.finditer(text)})


def scan_rrd_main(argv: list[str]) -> None:
    """`scan-rrd <file>...` (runs in traj_compare's venv): print {file: [private strings]} for every recording given."""
    print(json.dumps({path: rrd_private_hits(Path(path)) for path in argv}))


def write_thumbs(parts_path: Path, trajectories_path: Path, out: Path, robot: str) -> list[str]:
    """The gallery's pictures: the tool from above (the xy projection, colour = trajectories through the pixel, viridis,
    linear clipped at p98: the workbench's "trajectories" colouring of "The tool from above", through traj_compare's own
    scale and ramp), one per deployment and one for the robot, on white. Read from the parts the workbench wrote, so a
    picture is that page's view of the same trajectories. WHY trajectories, not samples: a picture this small needs the
    paths to read; samples per pixel leaves all but the slowest corners in the darkest colour."""
    import numpy as np
    from matplotlib import image as mpimg
    from traj_compare.coverage.matplotlib_view import ramp_rgb, scale_counts

    parts = [row for row in json.loads(parts_path.read_text())["rows"] if row["kind"] == "tool" and row["grid"] == "xy"]
    owner = {row["name"]: row["deployment"] for row in json.loads(trajectories_path.read_text())["rows"]}
    out.mkdir(parents=True, exist_ok=True)
    groups = {f"robot-{robot}": parts}
    for deployment in dict.fromkeys(owner.values()):
        groups[f"deployment-{deployment}"] = [row for row in parts if owner[row["trajectory"]] == deployment]
    written = []
    for stem, rows in groups.items():
        nu, nv = rows[0]["nu"], rows[0]["nv"]
        counts = np.zeros(nu * nv)
        for row in rows:
            if (row["nu"], row["nv"]) != (nu, nv):
                raise ValueError("the parts of one projection must share a grid")
            np.add.at(counts, np.asarray(row["at"], int), np.asarray(row["paths"], float))
        scaled = scale_counts(counts.reshape(nu, nv), "linear")
        t = scaled.t  # (nu, nv): -1 = never visited
        rgb = np.full((nv, nu, 3), 255, np.uint8)  # never visited: white, as the workbench draws it
        visited = (t >= 0).T[::-1]  # rows: y from the top; columns: x
        rgb[visited] = ramp_rgb(np.clip(t, 0, 1).T[::-1], "viridis")[visited]
        scale = max(1, int(round(240 / max(nu, nv))))
        big = np.kron(rgb, np.ones((scale, scale, 1), np.uint8))
        # on a white field as wide as the gallery's picture well (THUMB_ASPECT), so "contain" leaves no grey bars
        height = big.shape[0] + 2 * 6 * scale
        width = max(big.shape[1] + 2 * 6 * scale, int(round(height / THUMB_ASPECT)))
        framed = np.full((height, width, 3), 255, np.uint8)
        top, left = (height - big.shape[0]) // 2, (width - big.shape[1]) // 2
        framed[top:top + big.shape[0], left:left + big.shape[1]] = big
        path = out / f"{stem}.png"
        mpimg.imsave(path, framed)
        written.append(path.name)
    return written


# ── the host page around the workbench ──────────────────────────────────────────────────────────────────────────────

DATASETS_HTML = """<!doctype html>
<!-- GENERATED by tools/build_coverage.py (never edit; rebuild): the Datasets page for one robot, this site's host page
     around traj_compare's coverage workbench (coverage.base, trajectories.json and parts.json are its writer's,
     traj_compare.coverage.workbench.write_workbench): the site bar, then the writer's one element, unchanged. Deep links
     are data-ui's (CONTRACT §53): ?deployment=<key>&dataset=<key>&split=holdout#tab=tool-position -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Datasets · {robot_title} · Trajectory Tracking Agent</title>
<meta name="description" content="Trajectory coverage of {robot_title}'s datasets in ruler v1: what the trajectories visit, per joint and for the tool, filtered by deployment, dataset, split and kind.">
<link rel="stylesheet" href="{kit}/data-ui.css">
<style>{css}
  body {{ display: flex; flex-direction: column; min-height: 100vh; }}
  #frame {{ min-width: 0; }}
  /* the element's own height: the window less what sits above it (set by the script below), never less than 560 px */
  data-workbench {{ display: block; --data-height: max(560px, calc(100vh - var(--above, 160px))); }}
  .page-foot {{ padding: 6px 16px; font-size: 12px; color: var(--page-muted); border-top: 1px solid var(--line); }}
  .page-foot a {{ color: var(--page-accent); }}
</style>
</head>
<body>
<div id="frame">
{bar}
<header class="page-head">
  <h1>Datasets · {robot_title}</h1>
  <p>{lede}</p>
  <details class="small"><summary>About these numbers</summary><p class="small">{also}</p></details>
  <p class="notice" id="link-notice" role="status" hidden></p>
</header>
</div>
<data-workbench id="coverage" src="coverage.base" aria-label="{robot_title}: trajectory coverage"></data-workbench>
{foot}
<script type="module" src="{kit}/data-ui.js"></script>
<script type="module">
  // the workbench's height: the window less the site bar and the header above it, and the credit line under it
  const frame = document.getElementById('frame');
  const foot = document.querySelector('.page-foot');
  const fit = () => document.documentElement.style.setProperty('--above',
    frame.offsetHeight + (foot ? foot.offsetHeight : 0) + 'px');
  new ResizeObserver(fit).observe(frame);
  if (foot) new ResizeObserver(fit).observe(foot);
  fit();
  // a deep link to a deployment or dataset this page does not hold (deferred, not in the ruler) says why, from the
  // Deployments page's own rows, instead of showing an unexplained "0 of N"
  const params = new URLSearchParams(location.search);
  const asked = [['deployment', 'deployment'], ['dataset', 'dataset']]
    .flatMap(([param, level]) => (params.get(param) || '').split(',').filter(Boolean).map((key) => ({{ param, level, key }})));
  if (asked.length) {{
    try {{
      const [held, listed] = await Promise.all([
        fetch('trajectories.json').then((r) => r.json()),
        fetch('../../deployments/deployments.json').then((r) => r.json()),
      ]);
      const missing = asked.filter(({{ param, key }}) => !held.rows.some((row) => row[param] === key));
      if (missing.length) {{
        const note = document.getElementById('link-notice');
        note.textContent = missing.map(({{ level, key }}) => {{
          const row = listed.rows.find((r) => r.key === key && r.level.toLowerCase() === level);
          return row ? `${{row.name}} (${{key}}) is not on this page: ${{row.status_label}}. ${{row.why}}.`
                     : `${{key}} is not a ${{level}} this site knows.`;
        }}).join(' ');
        note.hidden = false;
      }}
    }} catch (error) {{ console.warn('could not check the deep link', error); }}
  }}
</script>
</body>
</html>
"""


# WHY a credit on the page and the licence beside the meshes: ur_description is BSD-3-Clause, whose binary
# redistribution (every .rrd embeds the meshes) must reproduce its notice in the materials that ship with it
def robot_credit(out: Path) -> str:
    urdfs = ", ".join(f'<a href="robot/{p.name}">{html.escape(p.name)}</a>' for p in sorted((out / "robot").glob("*.urdf")))
    return ("The arm in each recording: the ruler's UR5e kinematics (robot_controllers' MuJoCo Menagerie model) dressed in "
            "Universal Robots' ur_description collision meshes, BSD-3-Clause "
            f'(<a href="robot/LICENSE.ur_description">licence</a>; the URDF: {urdfs}).')


def write_datasets_host(out: Path, kit: str, robot_row: dict, rows: list[dict], rrd: bool) -> None:
    robot = robot_row["key"]
    mine = [row for row in rows if row["robot"] == robot]
    live = [row for row in mine if row["level"] == "Dataset" and row["in_workbench"]]
    others = [row for row in mine if row["level"] == "Deployment" and not row["in_workbench"]]
    held = sum(row["in_workbench"] for row in live)
    lede = (f"What the ruler's {html.escape(robot_row['name'])} trajectories visit: {len(live)} dataset"
            f"{'s' if len(live) != 1 else ''} ("
            + ", ".join(f"<code>{html.escape(row['key'])}</code>" for row in live)
            + f"), {held} trajectories, dev + holdout at speed 1.0. The rail filters trajectories; every tab recounts.")
    also = ("Tool = the dataset's TCP (flange + 0.144 m), base frame; the ruler scores the flange + 0.1 m "
            "(OBJECTIVES §2). ")
    if others:
        also += ("Not on this page yet: "
                + "; ".join(f"{html.escape(row['name'])} (<code>{html.escape(row['key'])}</code>, "
                            f"{row['datasets']} datasets, {row['trajectories']} trajectories: "
                            f"{html.escape(row['status_label'].lower())}{', ' + row['spec'] if row['spec'] else ''})"
                            for row in others)
                + ". See <a href=\"../../deployments/\">Deployments</a>.")
    if rrd:
        version = json.loads((out / RRD_INPUTS).read_text())["rerun_sdk"] if (out / RRD_INPUTS).exists() else "?"
        also += (f" A trajectory's record opens its recording in the Rerun web viewer (Rerun {html.escape(version)}, "
                 "the version that wrote it) or downloads the .rrd: the arm moving through the trajectory, the ruler's "
                 "tool point (flange + 0.1 m) and its path, and tabs of q, qd, qdd, qddd, % of limit and TCP, in degrees. "
                 + robot_credit(out))
        foot = f'<footer class="page-foot">{robot_credit(out)}</footer>'
    else:
        also += " A trajectory's Rerun recording is not built here; its record copies the name."
        foot = ""
    (out / "index.html").write_text(DATASETS_HTML.format(
        robot_title=html.escape(robot_row["name"]), kit=kit, css=PAGE_CSS, lede=lede, also=also.strip(),
        bar=site_bar.tag(out / "index.html", "coverage"), foot=foot))


def write_robot(out: Path, datasets: list[str]) -> dict[str, Path]:
    """The URDF arm each deployment's recordings draw (tools/ruler_urdf.py: the ruler's kinematics, ur_description's
    meshes and BSD licence) into <out>/robot/, and the ruler's tool poses of every trajectory (its tool point in the
    URDF's root) into outputs/coverage-build/<robot>-tools.npz. Returns {deployment: urdf path} and the .npz."""
    import numpy as np
    from robot_msgs import load_npz

    import ruler_urdf

    folder = out / "robot"
    deployments = sorted({key.split("/")[0] for key in datasets})
    files: dict[str, str] = {}
    for deployment in deployments:
        files.update(ruler_urdf.write(folder, deployment))
    for stale in folder.glob("*.urdf"):
        if stale.stem not in deployments:
            stale.unlink()
    arrays, names = {}, []
    for key in datasets:
        deployment = key.split("/")[0]
        folder_in = RULER_DATASETS / key
        for row in read_rows(folder_in / "tasks.jsonl"):
            tape = folder_in / "tapes" / f"{row['task_id']}.npz"
            trajectory = load_npz(tape)
            positions, rotations = ruler_urdf.tool_poses(deployment, np.asarray(trajectory.positions, float))
            index = len(names)
            names.append(f"{deployment}/{row['task_id']}")
            arrays.update({f"t_{index}": np.asarray(trajectory.t, float), f"p_{index}": positions, f"R_{index}": rotations})
    scratch = REPO / "outputs" / "coverage-build"
    scratch.mkdir(parents=True, exist_ok=True)
    tools = scratch / f"{out.name}-tools.npz"
    np.savez(tools, names=json.dumps(names), **arrays)
    return {"urdf": {d: folder / f"{d}.urdf" for d in deployments}, "tools": tools, "files": files}


def run_workbench(robot_row: dict, rows: list[dict], out: Path, kit: str, thumbs: Path, *, rrd: bool,
                  public_url: str | None, rerun_server: bool, served_at: str = "") -> dict:
    datasets = [row["key"] for row in rows if row["robot"] == robot_row["key"] and row["level"] == "Dataset"
                and row["status"] == "ruler-v1"]
    if not TRAJ_COMPARE_PYTHON.exists():
        raise FileNotFoundError(f"no traj_compare venv python at {TRAJ_COMPARE_PYTHON} (set TTA_TRAJ_COMPARE_PYTHON)")
    command = [str(TRAJ_COMPARE_PYTHON), str(Path(__file__).resolve()), "workbench", "--robot", robot_row["key"],
               "--title", WORKBENCH_TITLE.format(robot=robot_row["name"]), "--out", str(out), "--kit", kit,
               "--thumbs", str(thumbs)]
    for key in datasets:
        command += ["--dataset", key]
    if rrd:
        robot = write_robot(out, datasets)
        command += ["--rrd", "--tools", str(robot["tools"]), "--served-at", served_at]
        for deployment, urdf in robot["urdf"].items():
            command += ["--urdf", f"{deployment}={urdf}"]
        if public_url:
            command += ["--public-url", public_url]
        if rerun_server:
            command.append("--rerun-server")
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    result = subprocess.run(command, capture_output=True, text=True, env=env, cwd=REPO)
    if result.returncode != 0:
        raise RuntimeError(f"traj_compare workbench failed:\n{result.stderr[-4000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


# ── the kit ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def vendor_kit(force: bool = False) -> dict:
    """data-ui at DATA_UI_REF into site/vendor/data-ui with data-ui's own vendor command; VENDOR.json's `repo` (a local
    path) is replaced by the package name, since this site is public. Skipped when the pinned commit is already there."""
    record = KIT / "VENDOR.json"
    if not force and record.exists() and json.loads(record.read_text()).get("commit") == DATA_UI_REF:
        return json.loads(record.read_text())
    cli = DATA_UI / "bin" / "data-ui.mjs"
    command = ["node", str(cli), "vendor", DATA_UI_REF, "--into", str(KIT), "--views", ",".join(KIT_VIEWS),
               "--without", ",".join(KIT_WITHOUT)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"data-ui vendor failed: {(result.stderr or result.stdout)[-2000:]}")
    document = json.loads(record.read_text())
    document["repo"] = "data-ui"
    document["repo_note"] = "the local checkout's path is left out: this copy is published on a public site"
    record.write_text(json.dumps(document, indent=2) + "\n")
    return document


# ── build, local, check ─────────────────────────────────────────────────────────────────────────────────────────────


def build(args) -> None:
    robots, _ = robot_registry()
    kit = vendor_kit(force=args.revendor)
    print(f"data-ui kit {kit['commit'][:8]}: {_size(KIT) / 1e6:.2f} MB")
    first = facts(workbench={})
    thumbs = SITE / "deployments" / "thumbs"
    if thumbs.exists():
        for old in thumbs.iterdir():
            old.unlink()
    workbench = {}
    for robot_row in [row for row in first if row["level"] == "Robot" and row["status"] == "ruler-v1"]:
        out = SITE / "datasets" / robot_row["key"]
        # WHY every trajectory's recording ships (lane COV2, 2026-11-25; Zach picked the stock Rerun viewer, R3): the
        # record opens it in the Rerun web viewer straight from GitHub Pages, and downloads it
        made = run_workbench(robot_row, first, out, "../../vendor/data-ui", thumbs, rrd=True,
                             public_url=f"{PUBLIC_URL}datasets/{robot_row['key']}/", rerun_server=False,
                             served_at=f"/datasets/{robot_row['key']}/")
        print(f"datasets/{robot_row['key']}: {made}")
        workbench[robot_row["key"]] = json.loads((out / "trajectories.json").read_text())["rows"]
    rows = facts(workbench=workbench)
    write_deployments(rows, robots)
    for robot_row in [row for row in rows if row["level"] == "Robot" and row["in_workbench"]]:
        write_datasets_host(SITE / "datasets" / robot_row["key"], "../../vendor/data-ui", robot_row, rows, rrd=True)
    problems = check()
    report_sizes()
    if problems:
        raise SystemExit("check failed:\n" + "\n".join(problems))
    print("check: ok")


def pages() -> None:
    """Rewrite only the two host pages from the committed rows (site/deployments/deployments.json), without traj_compare:
    the site bar, the ledes. The workbench's own files and the rows are untouched; `check` holds them to their sources."""
    rows = json.loads((SITE / "deployments" / "deployments.json").read_text())["rows"]
    write_deployments_host(rows)
    for robot_row in [row for row in rows if row["level"] == "Robot" and row["in_workbench"]]:
        rrd = any((SITE / "datasets" / robot_row["key"]).glob("rrd-*.rrd"))
        write_datasets_host(SITE / "datasets" / robot_row["key"], "../../vendor/data-ui", robot_row, rows, rrd=rrd)
    print("site/deployments/index.html, " + ", ".join(f"site/datasets/{r['key']}/index.html" for r in rows
                                                     if r["level"] == "Robot" and r["in_workbench"]))


def local(args) -> None:
    """outputs/coverage-site/: a copy of site/ whose Datasets pages also carry a .rrd per trajectory and Open in Rerun
    (a POST to traj_compare.serve), for a local look; never committed."""
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE, out)
    rows = json.loads((SITE / "deployments" / "deployments.json").read_text())["rows"]
    for robot_row in [row for row in rows if row["level"] == "Robot" and row["in_workbench"]]:
        target = out / "datasets" / robot_row["key"]
        # served_at: Open in Rerun POSTs {rrd} to traj_compare.serve, which reads it against the served root
        made = run_workbench(robot_row, rows, target, "../../vendor/data-ui", out / "scratch-thumbs", rrd=True,
                             public_url=None, rerun_server=True, served_at=f"/datasets/{robot_row['key']}/")
        write_datasets_host(target, "../../vendor/data-ui", robot_row, rows, rrd=True)
        print(f"{target}: {made}")
    shutil.rmtree(out / "scratch-thumbs", ignore_errors=True)
    print(f"serve it: {TRAJ_COMPARE_PYTHON} -m traj_compare.serve {out} --port 8790   then /deployments/")


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def report_sizes() -> dict:
    parts = {"vendor/data-ui": _size(KIT), "deployments": _size(SITE / "deployments"),
             "datasets": _size(SITE / "datasets")}
    print("added to site/: " + ", ".join(f"{k} {v / 1e6:.2f} MB" for k, v in parts.items())
          + f"; total {sum(parts.values()) / 1e6:.2f} MB")
    return parts


PRIVATE = re.compile(r"/home/|bam_ws|zach_brain|\.claude|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
PRIVATE_PATHS = re.compile(r"/home/|/Users/|bam_ws|zach_brain|\.claude")


def our_files() -> list[Path]:
    roots = (SITE / "deployments", SITE / "datasets", KIT)
    return sorted(p for root in roots if root.exists() for p in root.rglob("*") if p.is_file())


def private_hits(paths: Iterable[Path]) -> list[str]:
    hits = []
    for path in paths:
        text = path.read_bytes().decode("utf-8", errors="replace") if path.suffix not in {".png", ".rrd"} else ""
        for number, line in enumerate(text.splitlines(), start=1):
            for match in PRIVATE.finditer(line):
                hits.append(f"{path.relative_to(REPO)}:{number}: {match.group(0)}")
    return hits


def check() -> list[str]:
    """The committed pages against their sources: the rows (re-derived, value for value), every link's filter against
    the workbench's rows, the stage list, private strings. [] when all hold."""
    problems = []
    document = json.loads((SITE / "deployments" / "deployments.json").read_text())
    try:
        expected = facts()
    except FileNotFoundError as error:
        problems.append(f"cannot re-derive the rows: {error}")
        expected = None
    if expected is not None and expected != document["rows"]:
        problems.append("site/deployments/deployments.json differs from its sources: rebuild")
    for row in document["rows"]:
        problems += link_problems(row)
    problems += bar_problems()
    problems += [f"private: {hit}" for hit in private_hits(our_files())]
    problems += recording_problems()
    return problems


FILE_LIMIT_BYTES = 100 * 1024 * 1024  # GitHub's per-file limit (tests/test_site_static.py cites it)


def recording_problems() -> list[str]:
    """Each Datasets page's recordings: one .rrd per trajectory row, on Pages at the row's rrd_url, listed in
    rrd_inputs.json, under GitHub's per-file limit; the record's web viewer is the Rerun version that wrote them; the
    URDF folder is what tools/ruler_urdf.py writes now (when arm_motion_bench is beside this repo) and ships its licence;
    no recording holds a private string (read with Rerun's own reader, in traj_compare's venv, when it is there)."""
    problems = []
    for data in sorted((SITE / "datasets").glob("*/trajectories.json")):
        out, robot = data.parent, data.parent.name
        rows = json.loads(data.read_text())["rows"]
        if not any(row.get("rrd") for row in rows):
            continue
        record = json.loads((out / RRD_INPUTS).read_text()) if (out / RRD_INPUTS).exists() else {"files": {}}
        shipped = sorted(p.name for p in out.glob("*.rrd"))
        if sorted(record["files"]) != shipped or sorted(row.get("rrd") or "" for row in rows) != shipped:
            problems.append(f"datasets/{robot}: the .rrd files, {RRD_INPUTS} and the rows' rrd disagree")
        for row in rows:
            if row.get("rrd_url") != f"{PUBLIC_URL}datasets/{robot}/{row.get('rrd')}":
                problems.append(f"datasets/{robot}: {row['name']}: rrd_url {row.get('rrd_url')!r} is not its file on Pages")
        problems += [f"datasets/{robot}/{p.name}: over GitHub's 100 MiB per file" for p in out.glob("*.rrd")
                     if p.stat().st_size > FILE_LIMIT_BYTES]
        base = (out / "coverage.base").read_text()
        viewer = f"https://app.rerun.io/version/{record.get('rerun_sdk')}/index.html?url={{rrd_url}}"
        if viewer not in base:
            problems.append(f"datasets/{robot}/coverage.base: no 'Open in the Rerun web viewer' at {viewer}")
        folder = out / "robot"
        if not (folder / "LICENSE.ur_description").exists():
            problems.append(f"datasets/{robot}/robot: the meshes ship without ur_description's BSD licence")
        try:
            import ruler_urdf

            for urdf in sorted(folder.glob("*.urdf")):
                if urdf.read_text() != ruler_urdf.urdf_text(urdf.stem):
                    problems.append(f"datasets/{robot}/robot/{urdf.name} differs from what tools/ruler_urdf.py writes: rebuild")
            for mesh in sorted((folder / "meshes").glob("*")):
                if mesh.read_bytes() != (ruler_urdf.UR_DESCRIPTION / "meshes" / mesh.name).read_bytes():
                    problems.append(f"datasets/{robot}/robot/meshes/{mesh.name} differs from ur_description's")
        except (FileNotFoundError, ImportError) as error:
            print(f"note: the URDF folder is not re-derived ({error})")
        if TRAJ_COMPARE_PYTHON.exists():
            files = [str(p) for p in sorted(out.glob("*.rrd"))]
            result = subprocess.run([str(TRAJ_COMPARE_PYTHON), str(Path(__file__).resolve()), "scan-rrd", *files],
                                    capture_output=True, text=True, cwd=REPO,
                                    env={k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"})
            if result.returncode != 0:
                problems.append(f"datasets/{robot}: could not read the recordings back: {result.stderr[-500:]}")
            else:
                for path, hits in json.loads(result.stdout.strip().splitlines()[-1]).items():
                    problems += [f"private in {Path(path).name}: {hit}" for hit in hits]
        else:
            print(f"note: no traj_compare venv at {TRAJ_COMPARE_PYTHON}: the recordings' strings are not read back")
    return problems


def link_problems(row: dict) -> list[str]:
    """A row's Datasets link must open a page whose rail keeps exactly that row's trajectories."""
    href = row.get("coverage")
    if not href:
        if row.get("in_workbench"):
            return [f"{row['id']}: {row['in_workbench']} trajectories on the Datasets page but no link"]
        return []
    parts = urlsplit(href)
    page = (SITE / "deployments" / parts.path).resolve()
    data = page / "trajectories.json"
    if not (page / "index.html").exists() or not data.exists():
        return [f"{row['id']}: {href} has no page"]
    held = json.loads(data.read_text())["rows"]
    query = {key: values[0].split(",") for key, values in parse_qs(parts.query).items()}
    kept = [r for r in held if all(r.get(key) in values for key, values in query.items())]
    problems = []
    if len(kept) != row["in_workbench"]:
        problems.append(f"{row['id']}: {href} keeps {len(kept)} trajectories, the row says {row['in_workbench']}")
    if row["level"] == "Deployment" and query.get("deployment") != [row["key"]]:
        problems.append(f"{row['id']}: {href} does not filter to deployment {row['key']}")
    if row["level"] == "Dataset" and query.get("dataset") != [row["key"]]:
        problems.append(f"{row['id']}: {href} does not filter to dataset {row['key']}")
    if row["level"] == "Robot" and query:
        problems.append(f"{row['id']}: a robot's link opens every dataset, got {href}")
    return problems


def bar_problems() -> list[str]:
    """The site bar: site/nav.json resolves, and each host page carries exactly one bar reading it (tools/site_bar.py)."""
    pages = [SITE / "deployments" / "index.html", *sorted((SITE / "datasets").glob("*/index.html"))]
    return site_bar.nav_problems() + site_bar.page_problems(pages)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "workbench":
        workbench_main(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "scan-rrd":
        scan_rrd_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="facts -> site/deployments; traj_compare's workbench -> site/datasets; check")
    b.add_argument("--rrd", action="store_true", help="(the default since 2026-11-25: every trajectory's .rrd ships)")
    b.add_argument("--revendor", action="store_true", help="vendor data-ui again even when the pinned commit is there")
    sub.add_parser("check", help="the committed pages against their sources")
    sub.add_parser("pages", help="only the host pages (index.html: the site bar, the lede) from the committed rows")
    loc = sub.add_parser("local", help="outputs/coverage-site/: the site plus .rrd files and Open in Rerun")
    loc.add_argument("--out", default=str(LOCAL_OUT))
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    elif args.command == "pages":
        pages()
    elif args.command == "check":
        problems = check()
        report_sizes()
        if problems:
            raise SystemExit("\n".join(problems))
        print("check: ok")
    else:
        local(args)


if __name__ == "__main__":
    main()
