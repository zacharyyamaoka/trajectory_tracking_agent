"""The population (CONTRACT §2): one folder per solution under `solutions/`, its lineage in `meta.json`.

    ids_in_creation_order()                 # ['p2', 'p8', ...]: meta.created, then the id
    meta("p7s")                             # the meta.json dict
    load_build("p7s")                       # solutions/p7s/solution.py's build(trajectory, deployment)
    new("p7s+coulomb", parent="p7s", change="...", proposed_by={...})   # copies the parent's folder

A solution may import any public package (robot_msgs, robot_controllers, numpy), never this repo's ruler or its
datasets (no peeking at the scorer, never the holdout). `check_source` enforces that statically before anything runs
(an import of `trajectory_tracking_agent`, or a string naming `datasets` or `holdout`); the ledger is the real guard.
"""

from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from trajectory_tracking_agent import files
from trajectory_tracking_agent.ruler.dataset import REPO_ROOT

SOLUTIONS_DIR = REPO_ROOT / "solutions"
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9+._-]{0,63}")
SCORECARD_FILES = ("scorecard.json", "scorecard_holdout.json")
META_KEYS = ("id", "parent", "change", "proposed_by", "created", "tags")

__all__ = [
    "SOLUTIONS_DIR",
    "check_source",
    "ids_in_creation_order",
    "load_build",
    "meta",
    "new",
    "solution_dir",
    "solution_sha256",
]


def solution_dir(solution_id: str) -> Path:
    if not isinstance(solution_id, str) or not ID_PATTERN.fullmatch(solution_id):
        raise ValueError(f"a solution id is short, lowercase and readable ({ID_PATTERN.pattern}), got {solution_id!r}")
    return SOLUTIONS_DIR / solution_id


def meta(solution_id: str) -> dict[str, Any]:
    path = solution_dir(solution_id) / "meta.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: every solution has a meta.json (CONTRACT §2)")
    record = json.loads(path.read_text())
    missing = [key for key in META_KEYS if key not in record]
    if missing:
        raise ValueError(f"{path}: missing {missing}")
    if record["id"] != solution_id:
        raise ValueError(f"{path}: id {record['id']!r} is not the folder's {solution_id!r}")
    return record


def all_ids() -> list[str]:
    if not SOLUTIONS_DIR.exists():
        return []
    return sorted(p.name for p in SOLUTIONS_DIR.iterdir() if p.is_dir() and (p / "meta.json").exists())


def ids_in_creation_order() -> list[str]:
    """Every solution, oldest first: by meta.json `created` (ISO-8601, compared as instants), then by id (naturally)."""

    def key(solution_id: str) -> tuple[float, list[Any]]:
        created = str(meta(solution_id)["created"])
        try:
            instant = _dt.datetime.fromisoformat(created)
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=_dt.UTC)
            stamp = instant.timestamp()
        except ValueError:
            stamp = float("inf")
        # WHY a natural order for ties: p8, p9, p10 entered robot_controllers in one commit, and p10 is not before p8
        natural = [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", solution_id)]
        return stamp, natural

    return sorted(all_ids(), key=key)


# ── the guard and the loader ────────────────────────────────────────────────────────────────────────────────


def check_source(path: Path) -> list[str]:
    """Why `path` may not run as a solution ([] = it may): an import of this repo's package (its ruler, dataset or
    evaluator) or a string constant naming `datasets` or `holdout` (reading the frozen data, the holdout above all)."""
    try:
        tree = ast.parse(Path(path).read_text(), filename=str(path))
    except SyntaxError as error:
        return [f"{path}: does not parse: {error}"]
    problems = []
    # WHY bare string statements are exempt: a docstring that says "never tuned on holdout" reads nothing
    prose = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)}
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in (
            "__import__",
            "import_module",
        ):
            names = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
        for name in names:
            if name.split(".")[0] == "trajectory_tracking_agent":
                problems.append(f"{path.name}:{node.lineno}: imports {name} (a solution never imports the ruler)")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose:
            lowered = node.value.lower()
            if "holdout" in lowered or "datasets" in lowered:
                problems.append(f"{path.name}:{node.lineno}: names {node.value!r} (a solution never reads the datasets)")
    return problems


def solution_sha256(solution_id: str) -> str:
    """sha256 over the solution folder's files (path and bytes, sorted), scorecards and caches left out."""
    folder = solution_dir(solution_id)
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = path.relative_to(folder).as_posix()
        if relative in SCORECARD_FILES or "__pycache__" in relative or relative.endswith(".pyc"):
            continue
        digest.update(relative.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


_LOADED: dict[tuple[str, str], Callable[..., Any]] = {}


def load_build(solution_id: str) -> Callable[..., Any]:
    """`build(trajectory, deployment)` from solutions/<id>/solution.py, after `check_source` (cached per process and
    folder content)."""
    folder = solution_dir(solution_id)
    source = folder / "solution.py"
    if not source.exists():
        raise FileNotFoundError(f"{source} is missing")
    problems = check_source(source)
    if problems:
        raise PermissionError("the solution may not run:\n- " + "\n- ".join(problems))
    key = (solution_id, solution_sha256(solution_id))
    if key in _LOADED:
        return _LOADED[key]
    module_name = "tta_solution_" + re.sub(r"[^a-z0-9_]", "_", solution_id) + "_" + key[1][:12]
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    build = getattr(module, "build", None)
    if not callable(build):
        raise TypeError(f"{source} has no build(trajectory, deployment)")
    _LOADED[key] = build
    return build


# ── a new solution ──────────────────────────────────────────────────────────────────────────────────────────


def new(
    solution_id: str,
    *,
    parent: str | None,
    change: str,
    proposed_by: Mapping[str, Any] | None = None,
    tags: list[str] | None = None,
    created: str | None = None,
) -> Path:
    """Create solutions/<id>/: the parent's files (its scorecards left out) and a fresh meta.json. Never reuses an id."""
    folder = solution_dir(solution_id)
    if folder.exists():
        raise FileExistsError(f"{folder} exists: a solution id is never reused")
    if not change or not change.strip():
        raise ValueError("change: one line saying what differs from the parent")
    if parent is not None:
        source = solution_dir(parent)
        meta(parent)  # the parent must be a real solution
        shutil.copytree(
            source,
            folder,
            ignore=shutil.ignore_patterns(*SCORECARD_FILES, "meta.json", "__pycache__", "*.pyc"),
        )
    else:
        folder.mkdir(parents=True)
        files.write_text(
            folder / "solution.py",
            '"""A new solution: build(trajectory, deployment) returns a robot_msgs JointController."""\n\n\n'
            "def build(trajectory, deployment):\n"
            '    raise NotImplementedError("write the controller")\n'
        )
    record = {
        "id": solution_id,
        "parent": parent,
        "change": change.strip(),
        "proposed_by": dict(proposed_by or {"agent": None, "model": None, "session": None}),
        "created": created or _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "tags": list(tags or []),
    }
    files.write_text(folder / "meta.json", json.dumps(record, indent=2) + "\n")
    return folder
