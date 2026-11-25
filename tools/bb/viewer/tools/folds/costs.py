"""The `costs` slice (viewer/CONTRACT.md §12, §16.1): what each scored solution cost, for bb-frontier.

One row per scored solution (iterations, then ablation runs): its objective and admissibility (so a row draws on its
own), and four costs, every one lower-is-better:

- `energy_j`, `host_compute_ms_p95`: the ruler's own diagnostics, from the newest dev ledger row on the current ruler.
- `code_lines`, `identified_params`: the box's OWN measuring tool, `ablations/costs.py --all`, run as a subprocess on a
  `git archive` of the ref. WHY a subprocess on an archive, never a copy and never the working tree: the box owns what
  "code size" means (Zach: build only the smallest missing piece), the same ref always measures the same bytes, and the
  fold itself never opens a solution's code; the tool's output is the metric. `source.ran` records the run.

A cost the box does not record is `null` with `why_null[<cost>]`. `tier_<cost>` places each row on that cost's chart:
`on the front` (Pareto-optimal over admissible iterations), `admissible`, `not admissible`, or `ablation run` (a study
variant, never on the front). Returns None when no solution has any cost (the component's empty state).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

COSTS = ("energy_j", "host_compute_ms_p95", "code_lines", "identified_params")
DIAGNOSTIC = ("energy_j", "host_compute_ms_p95")
MEASURED = ("code_lines", "identified_params")
TOOL = "ablations/costs.py"


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def _measure(tree) -> tuple[dict, str | None]:
    """{solution: {code_lines, identified_params}} from the box's own costs.py at the ref, and why when it cannot."""
    if TOOL not in tree.fileset:
        return {}, f"{TOOL} is not in the box at {tree.sha[:7]}"
    blob = subprocess.run(["git", "-C", tree.repo, "archive", "--format=tar", tree.sha, "ablations", "solutions"],
                          capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory(prefix="bb-costs-") as tmp:
        with tarfile.open(fileobj=BytesIO(blob)) as tar:
            tar.extractall(tmp, filter="data")
        # -I: the box's tool runs on the stdlib alone, with no site-packages and nothing from the fold's own directory
        out = subprocess.run([sys.executable, "-I", str(Path(tmp) / TOOL), "--all"], capture_output=True, text=True, cwd=tmp)
    if out.returncode != 0:
        return {}, f"{TOOL} --all failed at {tree.sha[:7]}: {out.stderr.strip().splitlines()[-1] if out.stderr.strip() else out.returncode}"
    rows = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
    return {r["solution"]: r for r in rows}, None


def _front(points: list[tuple[str, float, float]], lower_objective: bool) -> set[str]:
    """Ids on the Pareto front of (cost, objective): no other point is at least as good on both and better on one."""
    sign = 1 if lower_objective else -1
    on = set()
    for sid, c, o in points:
        if not any((c2 <= c and sign * o2 <= sign * o) and (c2 < c or sign * o2 < sign * o) for _, c2, o2 in points):
            on.add(sid)
    return on


def fold(facts: dict):
    ledger, state, tree = facts.get("ledger"), facts["state"], facts["tree"]
    if ledger is None:  # a population grade (robot_controllers): no ledger, no per-solution cost recorded
        return None
    ruler = ledger[-1].get("ruler") if ledger else None
    dev = {}
    for r in ledger:
        if r.get("split") == "dev" and r.get("ruler") == ruler and r.get("solution"):
            dev[r["solution"]] = r
    sols = [("iteration", i) for i in state.get("iterations") or []] + [("ablation", a) for a in state.get("ablations") or []]
    if not sols:
        return None
    measured, why_measured = _measure(tree)
    if not why_measured:
        facts.setdefault("ran", []).append(f"{TOOL} --all (the box's own tool, on a git archive of {tree.sha[:7]})")
    rows = []
    for kind, s in sols:
        diag = (dev.get(s["id"]) or {}).get("diagnostics") or {}
        m = measured.get(s["id"]) or {}
        row = {"id": s["id"], "kind": kind, "n": s.get("n"), "verdict": s.get("verdict"), "objective": s.get("objective"),
               "admissible": s.get("admissible")}
        why = {}
        for c in DIAGNOSTIC:
            row[c] = _num(diag.get(c))
            if row[c] is None:
                why[c] = f"the dev ledger row records no {c}"
        for c in MEASURED:
            row[c] = _num(m.get(c))
            if row[c] is None:
                why[c] = why_measured or f"{TOOL} measured no {c} for {s['id']}"
        row["why_null"] = why
        rows.append(row)
    if all(r[c] is None for r in rows for c in COSTS):
        return None
    lower = (state.get("objective") or {}).get("direction", "lower") == "lower"
    for c in COSTS:
        pts = [(r["id"], r[c], r["objective"]) for r in rows
               if r["kind"] == "iteration" and r["admissible"] and r[c] is not None and r["objective"] is not None]
        on = _front(pts, lower)
        for r in rows:
            r[f"tier_{c}"] = ("ablation run" if r["kind"] == "ablation" else "not admissible" if not r["admissible"]
                              else "on the front" if r["id"] in on else "admissible")
    return rows
