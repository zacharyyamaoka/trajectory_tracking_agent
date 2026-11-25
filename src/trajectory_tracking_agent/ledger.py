"""The ledger (CONTRACT §3): `ledger.jsonl`, one JSON object per evaluation, append-only; the local truth.

    append(row)                     # one evaluation (evaluate() builds the row)
    rows()                          # every row, in file order
    latest(split="dev")             # {solution: its newest row on that split}
    ranking()                       # OBJECTIVES §4: admissible by objective, then the rest by pass rate, then objective
    leaderboard_rows()              # the ranking with holdout beside each admissible solution

`PROGRESS.md` and `site/progress.svg` are regenerated from it by `tta progress` (`progress_markdown`).
"""

from __future__ import annotations

import fcntl
import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trajectory_tracking_agent import files
from trajectory_tracking_agent.ruler.dataset import REPO_ROOT
from trajectory_tracking_agent.ruler.gates import GATES

LEDGER_PATH = REPO_ROOT / "ledger.jsonl"
PROGRESS_PATH = REPO_ROOT / "PROGRESS.md"
ROW_KEYS = (
    "t", "solution", "parent", "split", "ruler", "objective", "admissible", "gate_pass_rate", "failed_gates",
    "diagnostics", "wall_time_s", "repo_commit", "proposed_by", "change", "task_objectives",
)  # fmt: skip

__all__ = ["LEDGER_PATH", "append", "latest", "leaderboard_rows", "population_markdown", "progress_markdown", "ranking",
           "rows"]


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def append(row: Mapping[str, Any], path: Path = LEDGER_PATH) -> None:
    """Append one row (every CONTRACT §3 key present); no whole row is ever rewritten.

    WHY one write, flushed, under a lock (Zach, 2026-11-24: the search should run overnight unattended): a row is
    whole or absent, two lanes appending at once never interleave, and a power cut loses at most the row in flight. A
    torn tail a killed writer left (a last line with no newline that does not parse) was never a row: it is cut off
    first, so this row starts on a line of its own. A whole last row that lost only its newline is kept."""
    missing = [key for key in ROW_KEYS if key not in row]
    if missing:
        raise ValueError(f"a ledger row needs {missing}")
    data = (json.dumps(dict(row), sort_keys=False, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _end_on_a_whole_row(descriptor)
        while data:
            data = data[os.write(descriptor, data):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _end_on_a_whole_row(descriptor: int) -> None:
    size = os.fstat(descriptor).st_size
    if size == 0 or os.pread(descriptor, 1, size - 1) == b"\n":
        return
    start = size
    while start > 0 and b"\n" not in os.pread(descriptor, size - start, start):
        start = max(0, start - 65536)
    head = os.pread(descriptor, size - start, start)
    cut = start + head.rfind(b"\n") + 1  # 0 when the file is one line with no newline
    tail = os.pread(descriptor, size - cut, cut)
    try:
        json.loads(tail)
    except ValueError:
        os.ftruncate(descriptor, cut)  # torn: a write that never finished
    else:
        os.write(descriptor, b"\n")  # whole: only its newline was missing


def rows(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    """Every row in file order. A torn last line (no newline after it) is a killed writer's leftover and is skipped;
    a bad line anywhere else is damage and raises, since dropping it would silently lose a score."""
    path = Path(path)
    if not path.exists():
        return []
    lines = path.read_text().split("\n")
    out = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError as error:
            if number == len(lines):
                break
            raise ValueError(f"{path.name} line {number} is not a ledger row: {error}") from None
    return out


def latest(split: str = "dev", path: Path = LEDGER_PATH) -> dict[str, dict[str, Any]]:
    """Each solution's newest row on `split` (the last one in file order: the ledger is appended in time order)."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows(path):
        if row.get("split") == split and row.get("ruler") == "v1":
            out[row["solution"]] = row
    return out


def rank_key(row: Mapping[str, Any]) -> tuple[int, float, float, str]:
    """OBJECTIVES §4's order: admissible first by objective (lower first); then by gate pass rate (higher first),
    then objective; a missing objective sorts last in its group."""
    objective = _finite(row.get("objective"))
    objective = math.inf if objective is None else objective
    if row.get("admissible") is True:
        return 0, 0.0, objective, str(row.get("solution"))
    return 1, -float(row.get("gate_pass_rate") or 0.0), objective, str(row.get("solution"))


def ranking(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    return sorted(latest("dev", path).values(), key=rank_key)


def ablation_ids() -> set[str]:
    """Solutions an ablation study made (meta.json tag `ablation`): measurements of a finished line's parts, never
    search steps. WHY left out of the best, the counts and status (Zach, 2026-11-24): ablation variants must not read
    as search progress; PROGRESS.md had said "61 of 64 admissible" with the 30 variants counted."""
    from trajectory_tracking_agent import population

    out = set()
    for solution in population.ids_in_creation_order():
        try:
            meta = population.meta(solution)
        except FileNotFoundError:
            continue
        if "ablation" in (meta.get("tags") or []):
            out.add(solution)
    return out


def searched(rows_by_solution: Mapping[str, Any]) -> dict[str, Any]:
    """`latest(...)` without the ablation variants."""
    skip = ablation_ids()
    return {solution: row for solution, row in rows_by_solution.items() if solution not in skip}


def best(path: Path = LEDGER_PATH, include_ablations: bool = False) -> dict[str, Any] | None:
    """The best solution's dev row: the lowest-objective admissible one (ablation variants left out unless asked), else None."""
    skip = set() if include_ablations else ablation_ids()
    admissible = [row for row in ranking(path) if row.get("admissible") is True and _finite(row.get("objective")) is not None
                  and row.get("solution") not in skip]
    return admissible[0] if admissible else None


def leaderboard_rows(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    """The ranking, each with its holdout objective and holdout - dev where both exist (reporting only)."""
    holdout = latest("holdout", path)
    out = []
    for rank, row in enumerate(ranking(path), start=1):
        dev_objective = _finite(row.get("objective"))
        other = holdout.get(row["solution"])
        held = _finite(other.get("objective")) if other else None
        out.append({
            "rank": rank,
            "solution": row["solution"],
            "objective_dev": dev_objective,
            "admissible": bool(row.get("admissible")),
            "gate_pass_rate": float(row.get("gate_pass_rate") or 0.0),
            "failed_gates": {g: int(n) for g, n in (row.get("failed_gates") or {}).items() if n},
            "objective_holdout": held,
            "holdout_minus_dev": None if held is None or dev_objective is None else held - dev_objective,
            "holdout_admissible": None if other is None else bool(other.get("admissible")),
            "t": row.get("t"),
        })  # fmt: skip
    return out


# ── PROGRESS.md ─────────────────────────────────────────────────────────────────────────────────────────────


def _mm(value: Any) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number:.3f}"


def population_markdown(population: Mapping[str, Any] | None = None) -> list[str]:
    """PROGRESS.md's "Population" section: the three views `tools/population_views.py` writes into site/views/, and
    (when `population` is its summary) the per-task winners in text, so an agent reading this file gets them too."""
    lines = ["## Population", "",
             "Drawn from [`ledger.jsonl`](ledger.jsonl) (metrics and provenance) by `tta progress`.", ""]
    if population and population.get("niche_winners"):
        winners = ", ".join(f"`{s}` {n}" for s, n in population["niche_winners"])
        weakest = population.get("weakest_family")
        lines += [f"**Per-task winners** (dev, admissible, tasks won of {population.get('tasks')}): {winners}; "
                  f"{population.get('distinct_winners')} distinct among {population.get('admissible')} admissible."
                  + (f" The best is weakest on {weakest[1]} (median {weakest[0]:.2f}× the per-task best)." if weakest else ""),
                  ""]  # fmt: skip
    lines += ["**Lineage**: each tree from a generation-0 root; colour = dev mm, thick orange = the path to the best, "
              "edge = Δ mm vs the parent.", "", "![lineage](site/views/lineage.svg)", "",
              "**Gates**: dev tasks failing each gate, with the objective beside.", "", "![gates](site/views/gates.svg)", "",
              "**Specialists**: each task's error ÷ the best admissible one; the dots are the niche winners to branch from.",
              "", "![specialists](site/views/specialists.svg)", ""]  # fmt: skip
    return lines


def progress_markdown(order: Sequence[str], path: Path = LEDGER_PATH, population: Mapping[str, Any] | None = None) -> str:
    """PROGRESS.md: the best solution, its objective, the admissible count, the population views, the last 10 rows and
    the gate failure matrix (dev, each solution's newest row). `order` is the solutions in creation order (the chart's
    x axis); `population` is `tools/population_views.py`'s summary (the per-task winners), when there is one."""
    every = rows(path)
    dev = searched(latest("dev", path))
    top = best(path)
    admissible = sum(1 for row in dev.values() if row.get("admissible") is True)
    lines = ["# Progress", "", "Generated by `tta progress` from [`ledger.jsonl`](ledger.jsonl) (ruler v1).", ""]
    if not dev:
        return "\n".join(lines + ["No solutions scored yet.", ""])
    if top is None:
        lines.append(f"**No admissible solution yet**: 0 of {len(dev)} scored solutions pass every gate on every dev "
                     "task. The gate failure matrix below says which gates fail, on how many tasks.")
    else:
        holdout = latest("holdout", path).get(top["solution"])
        held = "" if holdout is None else f"; holdout {_mm(holdout.get('objective'))} mm (reporting only)"
        lines.append(f"**Best: `{top['solution']}`**, tool_track_rms_mm **{_mm(top['objective'])} mm** on dev{held}. "
                     f"{admissible} of {len(dev)} scored solutions are admissible.")
    lines += ["", "![progress](site/progress.svg)", ""] + population_markdown(population)
    lines += ["## Last 10 ledger rows", "",
              "| t | solution | split | objective (mm) | admissible | gate pass rate | failed gates (tasks) |",
              "|---|---|---|---|---|---|---|"]
    for row in every[-10:]:
        failed = ", ".join(f"{g} {n}" for g, n in (row.get("failed_gates") or {}).items() if n) or "—"
        lines.append(f"| {row.get('t')} | `{row.get('solution')}` | {row.get('split')} | {_mm(row.get('objective'))} | "
                     f"{'yes' if row.get('admissible') else 'no'} | {100 * float(row.get('gate_pass_rate') or 0):.1f} % | "
                     f"{failed} |")
    lines += ["", "## Gate failure matrix (dev)", "",
              "Dev tasks failing each gate, from each solution's newest dev row, in creation order. 0 everywhere = admissible.",
              "", "| solution | objective (mm) | " + " | ".join(f"`{g}`" for g in GATES) + " |",
              "|---|---|" + "---|" * len(GATES)]
    for solution in [s for s in order if s in dev] + sorted(set(dev) - set(order)):
        row = dev[solution]
        failed = row.get("failed_gates") or {}
        lines.append(f"| `{solution}` | {_mm(row.get('objective'))} | "
                     + " | ".join(str(int(failed.get(g, 0))) for g in GATES) + " |")
    lines.append("")
    return "\n".join(lines)


# ── status.json (schema ai-team-status/1, vault `PROJECT - AI Team`) ────────────────────────────────────────

STATUS_PATH = REPO_ROOT / "status.json"
IDEAS_PATH = REPO_ROOT / "ideas.md"
MEMBER = "Trajectory Tracking Agent"


def _ideas() -> dict[str, Any]:
    """ideas.md's checkboxes: open (`- [ ]`), done (`- [x]`) and the first three open lines."""
    if not IDEAS_PATH.exists():
        return {"open": 0, "done_7d": 0, "top": []}
    # WHY only the "I'll try" list: "Suggestions for Zach" are his to pick, not the agent's queue (2026-11-24)
    lines, section = [], None
    for raw in IDEAS_PATH.read_text().splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if section is None or section.startswith("i'll try") or section.startswith("i’ll try"):
            lines.append(line)
    open_items = [line[6:].strip() for line in lines if line.startswith("- [ ]")]
    done = [line for line in lines if line.lower().startswith("- [x]")]
    # WHY done_7d is every crossed-off idea: ideas.md has no dates per item, and the repo is days old (2026-11-24)
    return {"open": len(open_items), "done_7d": len(done), "top": open_items[:3]}


def status_record(now_s: float | None = None, path: Path = LEDGER_PATH) -> dict[str, Any]:
    """The member's status file: `kpi` is written from the ledger (never by a chat); `status` and `blocked_on` are kept
    from the existing status.json when a chat set them (default "idle")."""
    import time

    dev = searched(latest("dev", path))
    top = best(path)
    admissible = sum(1 for row in dev.values() if row.get("admissible") is True)
    held = latest("holdout", path).get(top["solution"]) if top else None
    gap = None
    if top and held and _finite(held.get("objective")) is not None and _finite(top.get("objective")) is not None:
        gap = _finite(held["objective"]) - _finite(top["objective"])
    previous: dict[str, Any] = {}
    if STATUS_PATH.exists():
        try:
            previous = json.loads(STATUS_PATH.read_text())
        except json.JSONDecodeError:
            previous = {}
    return {
        "schema": "ai-team-status/1",
        "member": MEMBER,
        "team": "Robot Team",
        "remit": "make robots track a given trajectory more accurately, inside the gates (ruler v1, OBJECTIVES.md)",
        "kpi": {
            "name": "tool_track_rms_mm (best admissible, dev)",
            "value": None if top is None else _finite(top.get("objective")),
            "unit": "mm",
            "direction": "down",
            "target": None,
            "level": f"{admissible} of {len(dev)} admissible",
            "level_name": "ruler v1 · ur5e_alone · workspace/v2 dev",
            "next_gate": ("an admissible solution (every dev task passes every gate)" if top is None
                          else f"an admissible solution below {_finite(top['objective']):.3f} mm"),
            "on_track": top is not None,
        },
        "counter_kpi": {
            "name": "holdout - dev of the best (mm; reporting only, never selected on)",
            "value": gap,
            "unit": "mm",
            "owner": MEMBER,
        },
        "status": previous.get("status", "idle"),
        "blocked_on": previous.get("blocked_on"),
        "todo": _ideas(),
        "links": {"repo": "https://github.com/zacharyyamaoka/trajectory_tracking_agent", "report": "PROGRESS.md", "wandb": "Trajectory Tracking", "vault": None},
        "updated_t": float(now_s if now_s is not None else time.time()),
    }


def write_status(path: Path = LEDGER_PATH) -> Path:
    files.write_text(STATUS_PATH, json.dumps(status_record(path=path), indent=2) + "\n")
    return STATUS_PATH
