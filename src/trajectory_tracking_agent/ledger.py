"""The ledger (CONTRACT §3): `ledger.jsonl`, one JSON object per evaluation, append-only; the local truth.

    append(row)                     # one evaluation (evaluate() builds the row)
    rows()                          # every row, in file order
    latest(split="dev")             # {solution: its newest row on that split}
    ranking()                       # OBJECTIVES §4: admissible by objective, then the rest by pass rate, then objective
    leaderboard_rows()              # the ranking with holdout beside each admissible solution

`PROGRESS.md` and `site/progress.svg` are regenerated from it by `tta progress` (`progress_markdown`).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trajectory_tracking_agent.ruler.dataset import REPO_ROOT
from trajectory_tracking_agent.ruler.gates import GATES

LEDGER_PATH = REPO_ROOT / "ledger.jsonl"
PROGRESS_PATH = REPO_ROOT / "PROGRESS.md"
ROW_KEYS = (
    "t", "solution", "parent", "split", "ruler", "objective", "admissible", "gate_pass_rate", "failed_gates",
    "diagnostics", "wall_time_s", "repo_commit", "proposed_by", "change", "task_objectives",
)  # fmt: skip

__all__ = ["LEDGER_PATH", "append", "latest", "leaderboard_rows", "progress_markdown", "ranking", "rows"]


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def append(row: Mapping[str, Any], path: Path = LEDGER_PATH) -> None:
    """Append one row (every CONTRACT §3 key present); the file is never rewritten."""
    missing = [key for key in ROW_KEYS if key not in row]
    if missing:
        raise ValueError(f"a ledger row needs {missing}")
    line = json.dumps(dict(row), sort_keys=False, allow_nan=False)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def rows(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


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


def best(path: Path = LEDGER_PATH) -> dict[str, Any] | None:
    """The best solution's dev row: the lowest-objective admissible one, else None."""
    admissible = [row for row in ranking(path) if row.get("admissible") is True and _finite(row.get("objective")) is not None]
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


def progress_markdown(order: Sequence[str], path: Path = LEDGER_PATH) -> str:
    """PROGRESS.md: the best solution, its objective, the admissible count, the last 10 rows and the gate failure
    matrix (dev, each solution's newest row). `order` is the solutions in creation order (the chart's x axis)."""
    every = rows(path)
    dev = latest("dev", path)
    top = best(path)
    admissible = sum(1 for row in dev.values() if row.get("admissible") is True)
    lines = ["# Progress", "", "Generated by `tta progress` from `ledger.jsonl` (ruler v1); never edit by hand.", ""]
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
    lines += ["", "![progress](site/progress.svg)", "", "## Last 10 ledger rows", "",
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
    lines = [line.strip() for line in IDEAS_PATH.read_text().splitlines()]
    open_items = [line[6:].strip() for line in lines if line.startswith("- [ ]")]
    done = [line for line in lines if line.lower().startswith("- [x]")]
    # WHY done_7d is every crossed-off idea: ideas.md has no dates per item, and the repo is days old (2026-11-24)
    return {"open": len(open_items), "done_7d": len(done), "top": open_items[:3]}


def status_record(now_s: float | None = None, path: Path = LEDGER_PATH) -> dict[str, Any]:
    """The member's status file: `kpi` is written from the ledger (never by a chat); `status` and `blocked_on` are kept
    from the existing status.json when a chat set them (default "idle")."""
    import time

    dev = latest("dev", path)
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
        "links": {"repo": str(REPO_ROOT), "report": "PROGRESS.md", "wandb": "Trajectory Tracking", "vault": None},
        "updated_t": float(now_s if now_s is not None else time.time()),
    }


def write_status(path: Path = LEDGER_PATH) -> Path:
    STATUS_PATH.write_text(json.dumps(status_record(path=path), indent=2) + "\n")
    return STATUS_PATH
