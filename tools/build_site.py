"""Build the landing page's data and runtime (site/), measure in-browser parity, and shoot its media.

    uv run python tools/build_site.py build          # wheels + the shim's field table + site/data/*.json
    uv run python tools/build_site.py native-run     # the native reference run (outputs/site/native.json)
    uv run --no-project --with playwright==1.64.1 python tools/build_site.py parity   # headless Chrome vs native (1.64.1: its cached Chromium)
    uv run --no-project --with playwright==1.64.1 python tools/build_site.py shoot    # screenshots + hero video

`build` runs in the project env (it needs native mujoco for the field table). `parity` and `shoot` drive headless
Chromium through Playwright (its cached browser; never a visible window) and serve site/ on 127.0.0.1 themselves,
stopping the server when they finish. `parity` runs the native side with the project's .venv interpreter.

What `build` writes (all committed; nothing private, every path relative):

- site/wheels/*.whl: robot_msgs, robot_controllers and this repo's package, each built from its repo's committed
  HEAD (`git archive`, so an uncommitted edit can never reach the public page), plus dataclass-values from PyPI
  (sha256 from uv.lock). The worker installs them with micropip, no dependencies resolved over the network.
- site/runtime/mujoco_fields.json: the trailing shape of every MjModel / MjData array, read from native mujoco, so
  the shim shapes arrays exactly as the native bindings do (`site_xpos` (nsite, 3), ...).
- site/runtime/manifest.json: the pinned runtime (Pyodide, MuJoCo WASM, three.js), each wheel's sha256 and the
  commit it was built from.
- site/data/page.json: everything the page shows that is not computed live: the OBJECTIVES block, the best
  solution's source, the robot_msgs types used with their GitHub source lines, the leaderboard (read from
  solutions/*/scorecard.json; "not scored yet" when there are none - never placeholder numbers).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
WHEELS = SITE / "wheels"
RUNTIME = SITE / "runtime"
DATA = SITE / "data"
OUTPUTS = REPO / "outputs" / "site"

# The pinned runtime (WHY these: Pyodide 314.0.8 is the newest stable (CPython 3.14, as the native env);
# @mujoco/mujoco 3.11.0 is the same MuJoCo release as the native mujoco==3.11.0 wheel robot_controllers pins;
# three 0.186.1 is what robotdescription.com's viewer already runs).
PYODIDE_VERSION = "314.0.8"
MUJOCO_WASM_VERSION = "3.11.0"
THREE_VERSION = "0.186.1"
HIGHLIGHT_VERSION = "11.11.1"
GITHUB = "https://github.com/zacharyyamaoka"

SOURCE_REPOS = {  # distribution -> (repo dir relative to this repo, GitHub repo name, package dir in src/)
    "robot-msgs": ("../robot_msgs", "robot_msgs", "robot_msgs"),
    "robot-controllers": ("../robot_controllers", "robot_controllers", "robot_controllers"),
}


# ── wheels ─────────────────────────────────────────────────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_wheel(repo: Path, out: Path, *, require_clean: tuple[str, ...], worktree: bool = False) -> tuple[Path, str]:
    """A wheel of `repo` at its committed HEAD; refuses when `require_clean` paths have uncommitted edits (the
    native env imports the working tree, so a dirty tree would make the parity compare two different codes).
    `worktree` (local development only, `build --dev`) builds the working tree instead and marks the commit dirty."""
    commit = _git(repo, "rev-parse", "HEAD").strip()
    dirty = _git(repo, "status", "--porcelain", "--", *require_clean).strip()
    if dirty and not worktree:
        raise SystemExit(f"{repo}: uncommitted changes in {require_clean}; commit them first:\n{dirty}")
    with tempfile.TemporaryDirectory() as tmp:
        if worktree:
            commit += "+dirty" if dirty else ""
            for rel in ("pyproject.toml", "README.md", "LICENSE", "src"):
                source = repo / rel
                if source.is_dir():
                    shutil.copytree(source, Path(tmp) / rel, ignore=shutil.ignore_patterns("__pycache__"))
                elif source.exists():
                    shutil.copy2(source, Path(tmp) / rel)
        else:
            archive = subprocess.run(["git", "-C", str(repo), "archive", "HEAD"], check=True,
                                     capture_output=True).stdout
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(tmp, filter="data")
        before = set(out.glob("*.whl"))
        subprocess.run(["uv", "build", "--wheel", "--quiet", "--out-dir", str(out), tmp], check=True)
        built = sorted(set(out.glob("*.whl")) - before) or sorted(out.glob("*.whl"), key=os.path.getmtime)[-1:]
    return built[-1], commit


def _locked_wheel(name: str) -> tuple[str, str]:
    """(url, sha256) of `name`'s py3-none-any wheel in uv.lock."""
    lock = tomllib.loads((REPO / "uv.lock").read_text())
    for package in lock["package"]:
        if package["name"] == name:
            for wheel in package.get("wheels", []):
                if wheel["url"].endswith("-py3-none-any.whl"):
                    return wheel["url"], wheel["hash"].removeprefix("sha256:")
    raise SystemExit(f"uv.lock has no pure-Python wheel for {name}")


def build_wheels(dev: bool = False) -> list[dict[str, Any]]:
    WHEELS.mkdir(parents=True, exist_ok=True)
    for old in WHEELS.glob("*.whl"):
        old.unlink()
    out: list[dict[str, Any]] = []
    for dist, (rel, github, _package) in SOURCE_REPOS.items():
        repo = (REPO / rel).resolve()
        wheel, commit = _build_wheel(repo, WHEELS, require_clean=("src", "pyproject.toml"))
        out.append({"dist": dist, "file": wheel.name, "sha256": _sha256(wheel), "bytes": wheel.stat().st_size,
                    "source": f"{GITHUB}/{github}/tree/{commit}", "commit": commit})
    wheel, commit = _build_wheel(REPO, WHEELS, require_clean=("src/trajectory_tracking_agent", "pyproject.toml"),
                                 worktree=dev)
    out.append({"dist": "trajectory-tracking-agent", "file": wheel.name, "sha256": _sha256(wheel),
                "bytes": wheel.stat().st_size, "source": "this repo", "commit": commit})
    url, sha = _locked_wheel("dataclass-values")
    target = WHEELS / url.rsplit("/", 1)[1]
    with urllib.request.urlopen(url) as response:  # noqa: S310 - a pinned PyPI URL from uv.lock
        target.write_bytes(response.read())
    if _sha256(target) != sha:
        target.unlink()
        raise SystemExit(f"{target.name}: sha256 does not match uv.lock")
    out.append({"dist": "dataclass-values", "file": target.name, "sha256": sha, "bytes": target.stat().st_size,
                "source": url, "commit": None})
    # WHY: `uv build --out-dir` drops a "*" .gitignore into the folder it writes, which would keep the wheels the
    # public page installs out of git
    (WHEELS / ".gitignore").unlink(missing_ok=True)
    # robot_msgs first: robot_controllers imports it; this repo's package last
    order = {"dataclass-values": 0, "robot-msgs": 1, "robot-controllers": 2, "trajectory-tracking-agent": 3}
    return sorted(out, key=lambda row: order[row["dist"]])


# ── the repo files the package reads, mirrored for the browser ─────────────────────────────────────────────

REPO_MIRROR = DATA / "repo"
DATASET_REL = Path("datasets/ur5e_alone/workspace/v2")


def mirror_repo_files() -> list[dict[str, Any]]:
    """Copy into site/data/repo/ what the ruler reads relative to the repo root: the dataset's tasks.jsonl, station.json
    and manifest.json, the dev tapes only (the page never runs holdout), and every solution's solution.py + meta.json.
    The worker writes them at the same paths relative to the installed package's REPO_ROOT, so dataset.py and
    population.py read them unmodified."""
    if REPO_MIRROR.exists():
        shutil.rmtree(REPO_MIRROR)
    rows = [json.loads(line) for line in (REPO / DATASET_REL / "tasks.jsonl").read_text().splitlines() if line.strip()]
    # WHY not manifest.json: only verify() reads it (the page never does), and it records the generator's local paths
    wanted = [DATASET_REL / name for name in ("tasks.jsonl", "station.json")]
    wanted += [DATASET_REL / "tapes" / f"{row['task_id']}.npz" for row in rows if row["split"] == "dev"]
    for folder in sorted((REPO / "solutions").iterdir()):
        if folder.is_dir() and (folder / "solution.py").exists() and (folder / "meta.json").exists():
            # WHY every file but the scorecards (2026-11-24): gen-1 solutions read fitted parameters beside their code
            # (model.json, identified.json, ...); with only solution.py + meta.json the browser run of p5s-pass3
            # raised on the missing model.json and every gate failed closed. Scorecards are outputs, never inputs.
            wanted += [
                path.relative_to(REPO)
                for path in sorted(folder.iterdir())
                if path.is_file() and not path.name.startswith("scorecard") and path.suffix in {".py", ".json"}
            ]
    out = []
    for rel in wanted:
        source = REPO / rel
        target = REPO_MIRROR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        out.append({"path": rel.as_posix(), "bytes": target.stat().st_size})
    return out


# ── the shim's field table ─────────────────────────────────────────────────────────────────────────────────


def mujoco_fields() -> dict[str, Any]:
    """{"MjModel": {field: trailing dims}, "MjData": {...}} from native mujoco, over two different models so a
    trailing dimension that depends on the model's sizes is caught (and left out: the shim then refuses it)."""
    import mujoco
    import numpy as np
    from robot_controllers.bench.arm import ARM, build_model
    from robot_controllers.bench.types import Scene
    from robot_controllers.bench.ur5e import load_model

    def arrays(obj: Any) -> dict[str, tuple[int, ...]]:
        out = {}
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                value = getattr(obj, name)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(value, np.ndarray):
                out[name] = tuple(int(v) for v in value.shape[1:])
        return out

    planar, _ = build_model(Scene(belt=True), ARM)
    models = [load_model(), planar]
    tables: dict[str, dict[str, list[int]]] = {"MjModel": {}, "MjData": {}}
    for kind in tables:
        per_model = [arrays(m if kind == "MjModel" else mujoco.MjData(m)) for m in models]
        for name in sorted(set(per_model[0]) & set(per_model[1])):
            if per_model[0][name] == per_model[1][name]:
                tables[kind][name] = list(per_model[0][name])
    return {"mujoco": mujoco.__version__, **tables}


# ── page data ──────────────────────────────────────────────────────────────────────────────────────────────

ROBOT_MSGS_TYPES = (  # the vocabulary the black box speaks, in the order the page lists it
    "JointTrajectory", "JointState", "JointController", "ServoCommand", "ServoState", "Header",
)


def _objectives_block() -> str:
    text = (REPO / "OBJECTIVES.md").read_text()
    match = re.search(r"## 1\. The black box\s+```python\n(.*?)```", text, re.S)
    return match.group(1).rstrip() if match else ""


def _robot_msgs_types() -> list[dict[str, Any]]:
    """Each type's source lines in robot_msgs at the commit the wheel was built from (found by `class <Name>`)."""
    repo = (REPO / SOURCE_REPOS["robot-msgs"][0]).resolve()
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
            "name": name,
            "module": module,
            "url": f"{GITHUB}/robot_msgs/blob/{commit}/{rel.as_posix()}#L{decorator + 1}-L{end}",
            "lines": [decorator + 1, end],
            "summary": " ".join(doc.group(1).split()) if doc else "",
            "fields": fields[:14],
        })
    return out


def _leaderboard() -> dict[str, Any]:
    rows = []
    for card_path in sorted((REPO / "solutions").glob("*/scorecard.json")):
        card = json.loads(card_path.read_text())
        meta_path = card_path.with_name("meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        rows.append({
            "id": card_path.parent.name,
            "parent": meta.get("parent"),
            "change": meta.get("change", ""),
            "split": card.get("split"),
            "objective": card.get("objective"),
            "admissible": card.get("admissible"),
            "gate_pass_rate": card.get("gate_pass_rate"),
            "gates": card.get("gates", {}),
            "diagnostics": card.get("diagnostics", {}),
        })

    def key(row: dict[str, Any]) -> tuple:
        objective = row["objective"] if isinstance(row["objective"], (int, float)) else float("inf")
        return (not row["admissible"], -(row["gate_pass_rate"] or 0.0) if not row["admissible"] else 0.0, objective)

    rows.sort(key=key)
    best = next((row["id"] for row in rows if row["admissible"]), None)
    return {"rows": rows, "best": best, "scored": bool(rows),
            "progress_svg": (SITE / "progress.svg").exists()}


def _solution_source(solution_id: str | None) -> dict[str, Any] | None:
    if solution_id is None:
        return None
    path = REPO / "solutions" / solution_id / "solution.py"
    return {"id": solution_id, "path": f"solutions/{solution_id}/solution.py", "code": path.read_text()} \
        if path.exists() else None


def _dev_tasks() -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (REPO / DATASET_REL / "tasks.jsonl").read_text().splitlines() if line.strip()]
    dev = sorted((row for row in rows if row["split"] == "dev"), key=lambda row: (row["order"], row["task_id"]))
    out = []
    for row in dev:
        tape = REPO / DATASET_REL / "tapes" / f"{row['task_id']}.npz"
        from robot_msgs import load_npz

        duration = float(load_npz(tape).t[-1])
        out.append({"id": row["task_id"], "kind": row["kind"], "duration_s": duration})
    return out


def _solutions() -> list[dict[str, Any]]:
    """Every solution folder: its meta and, when scored, its native per-task numbers (the page shows them beside the
    numbers the browser computes)."""
    out = []
    for folder in sorted((REPO / "solutions").iterdir()):
        if not (folder / "meta.json").exists():
            continue
        meta = json.loads((folder / "meta.json").read_text())
        card_path = folder / "scorecard.json"
        native = {}
        if card_path.exists():
            card = json.loads(card_path.read_text())
            for row in card.get("tasks", []):
                native[row["task"]] = {"objective": row.get("objective"), "kpis": row.get("kpis", {}),
                                       "verdicts": row.get("verdicts", {})}
        out.append({"id": folder.name, "parent": meta.get("parent"), "change": meta.get("change", ""),
                    "tags": meta.get("tags", []), "native": native})
    order = {sid: index for index, sid in enumerate(_creation_order())}
    return sorted(out, key=lambda row: (order.get(row["id"], 1e9), row["id"]))


def _creation_order() -> list[str]:
    rows = []
    for meta_path in (REPO / "solutions").glob("*/meta.json"):
        meta = json.loads(meta_path.read_text())
        rows.append((str(meta.get("created", "")), meta_path.parent.name))
    return [sid for _, sid in sorted(rows)]


def page_data(wheels: list[dict[str, Any]]) -> dict[str, Any]:
    board = _leaderboard()
    status_path = REPO / "status.json"
    return {
        "tasks": _dev_tasks(),
        "solutions": _solutions(),
        # only the KPI and the queue's top: status.json's links name local paths that must not reach a public page
        "status": {key: json.loads(status_path.read_text()).get(key) for key in ("kpi", "counter_kpi", "todo")}
        if status_path.exists() else None,
        "objectives_block": _objectives_block(),
        "robot_msgs": _robot_msgs_types(),
        "leaderboard": board,
        "best_solution": _solution_source(board["best"]),
        "wheels": wheels,
        "repo_commit": _git(REPO, "rev-parse", "HEAD").strip(),
    }


def build(dev: bool = False) -> None:
    wheels = build_wheels(dev)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "mujoco_fields.json").write_text(json.dumps(mujoco_fields(), indent=0, sort_keys=True) + "\n")
    manifest = {
        "pyodide": PYODIDE_VERSION,
        "pyodide_url": f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/",
        "mujoco_wasm": MUJOCO_WASM_VERSION,
        "mujoco_url": f"https://cdn.jsdelivr.net/npm/@mujoco/mujoco@{MUJOCO_WASM_VERSION}/mujoco.js",
        "three": THREE_VERSION,
        "wheels": wheels,
        "repo_files": mirror_repo_files(),
    }
    (RUNTIME / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "page.json").write_text(json.dumps(page_data(wheels), indent=1) + "\n")
    for row in wheels:
        print(f"{row['file']:60s} {row['bytes']:>9,d} B  {row['commit'] or row['source']}")


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


def _browser_call(page: Any, url: str, timeout_s: float = 600.0) -> dict[str, Any]:
    page.goto(url)
    page.wait_for_function("window.__parity !== undefined", timeout=timeout_s * 1e3)
    return page.evaluate("window.__parity")


def _native(*args: str) -> dict[str, Any]:
    out = OUTPUTS / "native-tmp.json"
    subprocess.run(["uv", "run", "--quiet", "--no-sync", "--project", str(REPO), "python", str(RUNTIME / "pipeline.py"), *args,
                    "--out", str(out)], check=True, cwd=REPO, stdout=subprocess.DEVNULL)
    result = json.loads(out.read_text())
    out.unlink()
    return result


def _max_abs(a: Any, b: Any) -> float:
    if isinstance(a, list):
        return max((_max_abs(x, y) for x, y in zip(a, b, strict=True)), default=0.0)
    if a is None or b is None:
        return 0.0 if a is b else math.inf
    return abs(float(a) - float(b))


def _relative(a: Any, b: Any) -> float | None:
    if a is None or b is None:
        return None if a is b else math.inf
    a, b = float(a), float(b)
    return 0.0 if a == b else abs(a - b) / max(abs(a), abs(b))


PARITY_TOLERANCE = 1e-9  # relative, on the objective and every gate number (see parity())


def parity() -> dict[str, Any]:
    """The same runs natively and in headless Chromium, compared (outputs/site/parity.json).

    Cases: the ruler's own `run_task` (exactly what `tta evaluate` runs per task) for three solutions, among them a
    calibrated one (two extra calibration episodes) and one with feed-forward at the host (mj_inverse every tick), and
    robot_controllers' own UR5e path under P2 with every 4 kHz joint and tool sample compared. The ruler sends each
    command at its wake time (deployment.timing), so both sides run the same schedule; the robot_controllers path is
    run the same way.

    WHY 1e-9: both sides run MuJoCo 3.11.0, but compiled by different toolchains (clang to wasm32 vs the native
    x86-64 wheel) against different libm (musl's vs glibc's sin/cos/tanh differ in the last bit), and numpy 2.4.6
    (Pyodide) vs 2.5.5; last-bit differences grow through ~16000 closed-loop steps. 1e-9 is far above that and far
    below anything the page shows (4 significant digits).
    """
    from playwright.sync_api import sync_playwright

    # (title, what, options, gated): gated cases must agree within PARITY_TOLERANCE; the others are measured and reported
    cases = [
        ("p2 on workspace-dev-000: the ruler's run_task", "run", {"solution": "p2", "task": "workspace-dev-000"}, True),
        ("p2 on workspace-dev-021: the ruler's run_task", "run", {"solution": "p2", "task": "workspace-dev-021"}, True),
        ("p6s on workspace-dev-000: run_task, calibration episodes sent at their wake time", "run",
         {"solution": "p6s", "task": "workspace-dev-000", "pin_calibration": True}, True),
        ("p7s on workspace-dev-002: run_task, calibration episodes sent at their wake time", "run",
         {"solution": "p7s", "task": "workspace-dev-002", "pin_calibration": True}, True),
        ("p7s on workspace-dev-002: run_task as tta evaluate runs it (host-dependent calibration)", "run",
         {"solution": "p7s", "task": "workspace-dev-002"}, False),
        ("robot_controllers ur5e/path@nominal, P2, sent at the wake time", "path",
         {"config": "P2", "deterministic": True}, True),
    ]
    results = []
    with Server() as server, sync_playwright() as playwright:
        browser = _browser(playwright)
        for title, what, options, gated in cases:
            args = [what]
            query = [f"what={what}"]
            if what == "run":
                args += ["--solution", options["solution"], "--task", options["task"]]
                query += [f"solution={options['solution']}", f"task={options['task']}"]
            else:
                args += ["--config", options["config"]]
                query += [f"config={options['config']}"]
            if options.get("deterministic"):
                args.append("--deterministic")
                query.append("deterministic=1")
            if options.get("pin_calibration"):
                args.append("--pin-calibration")
                query.append("pin_calibration=1")
            native = _native(*args)
            page = browser.new_page()
            web = _browser_call(page, f"{server.url}/runtime/parity.html?{'&'.join(query)}")
            page.close()
            if web.get("error"):
                results.append({"case": title, "error": web["error"], "gated": gated})
                continue
            if what == "run":
                numbers = {"tool_track_rms_mm": (native["row"]["objective"], web["row"]["objective"])}
                for name, value in native["row"]["kpis"].items():
                    numbers[name] = (value, web["row"]["kpis"].get(name))
                arrays = {name: _max_abs(native["explain"][name], web["explain"][name]) for name in ("q", "tool")}
                arrays_note = "q (rad) and tool (m) at the task's 100 Hz target instants"
                host = {"native_ms": native["host_compute_ms"], "browser_ms": web["host_compute_ms"]}
            else:
                numbers = {"tick_tool_error_rms_mm": (native["metrics"]["tick_tool_error_rms_mm"],
                                                      web["metrics"]["tick_tool_error_rms_mm"])}
                arrays = {"q": _max_abs(native["full"]["q"], web["full"]["q"]),
                          "tool_pos": _max_abs(native["full"]["tool_pos"], web["full"]["tool_pos"])}
                arrays_note = "every 4 kHz plant sample: q (rad), tool_pos (m)"
                host = None
            rows = {name: {"native": a, "browser": b, "relative": _relative(a, b)} for name, (a, b) in numbers.items()}
            worst = max((row["relative"] or 0.0) for row in rows.values())
            results.append({
                "case": title, "numbers": rows,
                "max_abs_diff": arrays, "arrays": arrays_note, "worst_relative": worst,
                "within_tolerance": worst <= PARITY_TOLERANCE, "gated": gated,
                "host_compute": host,
                "runtime": {"native": native["runtime"], "browser": web["runtime"]},
                "wall_s": {"native": native["wall"], "browser": web["browser"]},
            })
            print(f"{title}: worst relative {worst:.3g}{'' if gated else ' (not gated)'}")
        browser.close()
    report = {
        "schema": "tta.site_parity/1",
        "tolerance_relative": PARITY_TOLERANCE,
        "tolerance_why": parity.__doc__.split("WHY 1e-9: ", 1)[1].strip(),
        "pass": bool(results) and all(r.get("within_tolerance") for r in results if r.get("gated", True)),
        "not_gated_why": "A solution whose build() calibrates its lookahead (robot_controllers' 'calibrated' configs: P1, "
        "P4-P7 and their s variants) runs robot_controllers' calibration episodes, which send each command at wake + "
        "the tick's measured CPU time; the browser's ticks are slower and its clock resolves 0.1 ms, so the calibrated "
        "lookahead can differ by one 0.25 ms board tick on a joint, and the score with it. That is the solution "
        "measuring its host, not the runtime: with those episodes sent at their wake time (the gated cases) both "
        "sides agree to the last digits.",
        "browser": "headless Chromium (Playwright), swiftshader WebGL",
        "pyodide": PYODIDE_VERSION,
        "mujoco_wasm": MUJOCO_WASM_VERSION,
        "cases": results,
        "measured": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    (OUTPUTS / "parity.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


# ── shoot: the page measured and recorded in headless Chromium ─────────────────────────────────────────────

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


def _wait_run(page: Any, timeout_s: float = 300.0) -> dict[str, Any]:
    page.wait_for_function("window.__page && window.__page.run && !window.__page.busy", timeout=timeout_s * 1e3)
    return page.evaluate("window.__page.run.row")


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


def shoot() -> dict[str, Any]:
    """Screenshots of every card's explanation (3D + 2D), light / dark / phone, a measured check that the cards show
    the run's numbers and that each click changes both views, and the hero video (outputs/site/)."""
    from playwright.sync_api import sync_playwright

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"cards": {}, "checks": {}}
    with Server() as server, sync_playwright() as playwright:
        browser = _browser(playwright)

        # 1. desktop, light: the default run (the best solution on the cube), every card clicked
        page = browser.new_page(viewport={"width": 1280, "height": 860}, color_scheme="light")
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        started = time.time()
        page.goto(f"{server.url}/index.html")
        row = _wait_run(page)
        report["load_to_scores_s"] = round(time.time() - started, 1)
        run_setup = page.evaluate("window.__page.run.setup")
        _pause_at(page, 2.2)
        page.screenshot(path=str(OUTPUTS / "page-light.png"))
        shown = page.evaluate("[...document.querySelectorAll('.card')].map((c) => [c.dataset.id, c.querySelector('.value').textContent])")
        report["checks"]["cards_show_the_run"] = _cards_match(dict(shown), row)
        previous = _fingerprint(page)
        for card in (*CARD_IDS[1:], CARD_IDS[0]):  # start away from the default, end back on it
            page.click(f".card[data-id='{card}']")
            page.wait_for_timeout(600)
            now = _fingerprint(page)
            report["cards"][card] = {"canvas_changed": now["canvas"] != previous["canvas"],
                                     "plot_changed": now["plot"] != previous["plot"], "title": now["title"]}
            previous = now
            page.locator("#viewer").screenshot(path=str(OUTPUTS / f"card-{card}-3d.png"))
            page.locator("#explain").screenshot(path=str(OUTPUTS / f"card-{card}-2d.png"))
        page.screenshot(path=str(OUTPUTS / "page-light-full.png"), full_page=True)
        report["run"] = {"setup": run_setup, "objective": row["objective"], "verdicts": row["verdicts"]}
        report["page_errors"] = errors
        page.close()

        # 2. dark and phone width
        for name, viewport, scheme in (("page-dark", {"width": 1280, "height": 860}, "dark"),
                                       ("page-phone", {"width": 390, "height": 844}, "light")):
            page = browser.new_page(viewport=viewport, color_scheme=scheme)
            page.goto(f"{server.url}/index.html?solution=p2&task=workspace-dev-001")
            _wait_run(page)
            _pause_at(page, 2.2)
            page.screenshot(path=str(OUTPUTS / f"{name}.png"))
            page.screenshot(path=str(OUTPUTS / f"{name}-full.png"), full_page=True)
            report["checks"][f"{name}_no_horizontal_scroll"] = page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth")
            page.close()

        # 3. the hero video: load -> boot -> run -> click a score -> its 3D explanation
        video_dir = Path(tempfile.mkdtemp(dir=OUTPUTS))
        context = browser.new_context(viewport={"width": 1280, "height": 1000}, color_scheme="light",
                                      record_video_dir=str(video_dir), record_video_size={"width": 1280, "height": 1000})
        context.add_init_script(CURSOR)
        page = context.new_page()
        recording_started = time.monotonic()
        page.goto(f"{server.url}/index.html")
        page.mouse.move(1000, 480)
        _wait_run(page)
        scores_at = time.monotonic() - recording_started
        page.wait_for_timeout(2500)
        page.evaluate("window.scrollTo({top: 300, behavior: 'smooth'})")
        page.wait_for_timeout(900)
        for card in ("stop_error_max_mm", "saturation_share_pct", "floor_clearance"):
            box = page.locator(f".card[data-id='{card}']").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=20)
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(2700)
        video = page.video.path()
        context.close()
        raw = Path(video)
        # WHY one jump cut: booting Python + MuJoCo and running the solution takes ~10 s of a spinner and a status line;
        # the clip keeps its first 2.5 s, cuts to 1 s before the scores arrive, and runs unedited from there
        cut_to = max(2.5, scores_at - 1.0)
        report["hero_cut"] = {"kept_s": [0.0, 2.5], "resumes_at_s": round(cut_to, 2), "removed_s": round(cut_to - 2.5, 2)}
        graph = (f"[0:v]trim=0:2.5,setpts=PTS-STARTPTS[a];[0:v]trim=start={cut_to:.3f},setpts=PTS-STARTPTS[b];"
                 "[a][b]concat=n=2:v=1:a=0,scale=1280:-2[out]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-filter_complex", graph, "-map", "[out]",
                        "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(OUTPUTS / "hero.mp4")], check=True)
        shutil.rmtree(video_dir, ignore_errors=True)
        browser.close()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                            str(OUTPUTS / "hero.mp4")], capture_output=True, text=True)
    report["hero_mp4_s"] = float(probe.stdout.strip() or "nan")
    report["pass"] = (all(report["checks"].values())
                      and all(card["canvas_changed"] and card["plot_changed"] for card in report["cards"].values())
                      and not report["page_errors"])
    (OUTPUTS / "shoot.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def _cards_match(shown: dict[str, str], row: dict[str, Any]) -> bool:
    """Each card's text is the run's own value, as the page formats it (3 significant digits, or an integer / yes-no)."""
    values = {"tool_track_rms_mm": row["objective"], **row["kpis"],
              "floor_clearance": row["kpis"].get("floor_clearance_violations", row["kpis"].get("floor_clearance"))}
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
            print(f"card {card}: shows {text!r}, the run has {value!r}")
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("build", "parity", "shoot"))
    parser.add_argument("--dev", action="store_true",
                        help="build this repo's wheel from the working tree (local development; never commit it)")
    args = parser.parse_args(argv)
    if args.command == "build":
        build(dev=args.dev)
    elif args.command == "parity":
        report = parity()
        print(f"parity: {'PASS' if report['pass'] else 'FAIL'} -> {OUTPUTS / 'parity.json'}")
        return 0 if report["pass"] else 1
    elif args.command == "shoot":
        report = shoot()
        print(json.dumps({key: report[key] for key in ("checks", "cards", "pass", "hero_mp4_s", "load_to_scores_s")}, indent=1))
        return 0 if report["pass"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
