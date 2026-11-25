#!/usr/bin/env python3
"""The viewer's fold: one black-box repo at a git ref -> state.json (bb-state/1, viewer/CONTRACT.md §3).

    python3 viewer/tools/fold_state.py --repo ~/trajectory_tracking_agent --ref 9ead945 --out state.json
    python3 viewer/tools/fold_state.py --all            # every scenario in viewer/scenarios/scenarios.json
    python3 viewer/tools/fold_state.py --all --check    # re-fold, compare byte for byte, write nothing

Stdlib only, read-only on the box: every file through `git show <ref>:<path>` and `git log <ref>`, never the working
tree (WHY: a peer's in-flight files are never read, and the same ref folds to the same bytes). What it reads is the
box's metrics out and provenance only (README, OBJECTIVES.md, status.json, ledger.jsonl, solutions/*/meta.json and
the ruler's scorecards, ideas.md, feedback/, audits/, agents/, activity.jsonl, git log), never a solution's code
(Zach, 2026-11-24: "the blackbox viz is not related to the solution, only to the metrics out"). Every path read is
listed in state["source"]["read"], and a test holds that list to that rule.

Never invents a number: what cannot be read is left out, or null with a `why`.

Two kinds of box:
- `standard`: the agent-repo format (trajectory_tracking_agent, claude_party_agent).
- `rc`: robot_controllers' population grade (results/grade/results.json), one arm's base scenario.

A wave-2 slice is a module tools/folds/<slice>.py with `def fold(facts) -> object` (CONTRACT §3.3).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import subprocess
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIEWER = HERE.parent
BB_REPO = VIEWER.parent
SCENARIOS = VIEWER / "scenarios"
# the idea-queue lane's lossless ideas.md parser, imported read-only (never re-implemented: one parser, one meaning)
IDEAS_PARSE = BB_REPO / "proposals-ideas" / "_shared" / "ideas_parse.py"
RELATIVE_TIE = 1e-9  # GOTCHAS "Float ties as progress": a new best must beat the last by a relative 1e-9


# ── reading a repo at a ref ──────────────────────────────────────────────────────────────────────────────────────
class Tree:
    """One repo at one ref. Every file read goes through here and is recorded."""

    def __init__(self, repo: str, ref: str):
        self.repo = str(Path(repo).expanduser().resolve())
        self.sha = self.git("rev-parse", f"{ref}^{{commit}}").strip()
        self.files = self.git("ls-tree", "-r", "--name-only", self.sha).splitlines()
        self.fileset = set(self.files)
        self.read: set[str] = set()

    def git(self, *args: str) -> str:
        out = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"git {' '.join(args[:3])} in {self.repo}: {out.stderr.strip()}")
        return out.stdout

    def text(self, path: str) -> str | None:
        if path not in self.fileset:
            return None
        self.read.add(path)
        return self.git("show", f"{self.sha}:{path}")

    def json(self, path: str):
        text = self.text(path)
        return json.loads(text) if text else None

    def bytes(self, path: str) -> bytes:
        """A binary file (the box's saved playback), recorded like any read; FileNotFoundError when the ref lacks it."""
        if path not in self.fileset:
            raise FileNotFoundError(f"{Path(self.repo).name}@{self.sha[:7]}:{path}")
        self.read.add(path)
        out = subprocess.run(["git", "-C", self.repo, "show", f"{self.sha}:{path}"], capture_output=True)
        if out.returncode != 0:
            raise RuntimeError(f"git show {path} in {self.repo}: {out.stderr.decode().strip()}")
        return out.stdout

    @property
    def name(self) -> str:
        return Path(self.repo).name

    def where(self, path: str) -> str:
        return f"{self.name}@{self.sha[:7]}:{path}"

    def date(self, rev: str | None = None) -> str:
        return self.git("log", "-1", "--format=%cI", rev or self.sha).strip()

    def last_change(self, path: str) -> dict | None:
        out = self.git("log", self.sha, "-1", "--format=%h%x1f%cI%x1f%s", "--", path).strip()
        if not out:
            return None
        sha, date, subject = out.split("\x1f")
        return {"sha": sha, "date": date, "subject": subject}


def finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return int(x) if isinstance(value, int) else x


def ts(iso: str | None) -> float:
    if not iso:
        return math.inf
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return math.inf
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def natural(text: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


UNITS = [("_mm", "mm"), ("_pct", "%"), ("_ms", "ms"), ("_deg", "°"), ("_s", "s"), ("_nm", "N·m"), ("_min", "min")]


def web(url: str | None) -> str | None:
    """A link only when it is public (http/https): a local path in status.json never reaches a page (GOTCHAS)."""
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


def unit_of(name: str | None) -> str:
    for suffix, unit in UNITS:
        if name and name.endswith(suffix):
            return unit
    return ""


def sig_decimals(v) -> int | None:
    """Decimals that show 3 significant digits (0 for a whole number): a reporting KPI is never printed to 17 digits."""
    if v is None:
        return None
    if float(v).is_integer():
        return 0
    return max(0, 2 - math.floor(math.log10(abs(v))))


def better(a: float, b: float | None, direction: str) -> bool:
    """a beats b by more than a relative float tie."""
    if b is None:
        return True
    tie = RELATIVE_TIE * abs(b)
    return a < b - tie if direction == "lower" else a > b + tie


# ── OBJECTIVES.md ────────────────────────────────────────────────────────────────────────────────────────────────
def objectives(text: str) -> dict:
    title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("# ")), "")
    ruler = re.search(r"ruler (v\d+), frozen (\d{4}-\d\d-\d\d)", title)
    obj = re.search(r"\*\*Objective \(one number, (lower|higher) is better\): `([A-Za-z_0-9]+)`\*\*", text)
    gates, in_gates = [], False
    for line in text.splitlines():
        if line.startswith("| Gate |"):
            in_gates = True
            continue
        if in_gates:
            if not line.startswith("|"):
                in_gates = False
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not cells or set(cells[0]) <= {"-", " ", ":"}:
                continue
            gates.append({"id": cells[0].strip("`"), "pass_when": cells[1] if len(cells) > 1 else None,
                          "why": cells[2] if len(cells) > 2 and cells[2] not in ("—", "-") else None})
    return {"title": title, "ruler": ruler.group(1) if ruler else None, "frozen": ruler.group(2) if ruler else None,
            "name": obj.group(2) if obj else None, "direction": obj.group(1) if obj else "lower", "gates": gates}


# ── ideas.md (through the idea-queue lane's parser) ─────────────────────────────────────────────────────────────
_parser = None


def ideas_parser():
    global _parser
    if _parser is None:
        spec = importlib.util.spec_from_file_location("ideas_parse", IDEAS_PARSE)
        _parser = importlib.util.module_from_spec(spec)
        sys.modules["ideas_parse"] = _parser
        spec.loader.exec_module(_parser)
    return _parser


def ideas_rows(text: str) -> list[dict]:
    doc = ideas_parser().parse(text)
    rows = []
    for i in doc.ideas:
        rows.append({"id": i.block_id or f"L{i.line_no}", "line": i.line_no, "lane": i.lane, "section": i.section,
                     "open": not i.checked, "title": i.title, "text": i.text, "expect": i.expect_text,
                     "solutions": i.solution_ids()})
    return rows


def needs_from(ideas: list[dict], status: dict) -> list[dict]:
    out = []
    if status.get("blocked_on"):
        out.append({"ask": status["blocked_on"], "text": status["blocked_on"], "source": "status.json blocked_on",
                    "section": None, "kind": "blocked"})
    for i in ideas:
        if i["lane"] == "human" and i["open"]:
            title = i["title"]
            kind = "ruler" if title.lower().startswith("ruler") else ("test" if "test" in title.lower() else "decision")
            out.append({"ask": title, "text": i["text"], "source": f"ideas.md:{i['line']}", "section": i["section"], "kind": kind})
    return out


# ── shared derivations ───────────────────────────────────────────────────────────────────────────────────────────
def judge(rows: list[dict], direction: str) -> None:
    """Verdict, best so far and best holder, in place, in the rows' order (CONTRACT §3.2)."""
    best = None
    for n, r in enumerate(rows, 1):
        r["n"] = n
        obj, ok = r["objective"], r["admissible"]
        if not ok or obj is None:
            r["verdict"] = "failed"
        elif better(obj, best[1] if best else None, direction):
            r["verdict"] = "kept"
            best = (r["id"], obj)
        else:
            r["verdict"] = "discarded"
        r["best_so_far"] = best[1] if best else None
        r["best_holder"] = best[0] if best else None


def pct_change(first: float, last: float) -> str | None:
    if not first:
        return None
    return f"{100 * (last - first) / first:+.0f} % since iteration 1".replace("-", "−")


def kpi_best(its: list[dict], objective: dict) -> dict:
    spark = [r["best_so_far"] for r in its]
    last = spark[-1] if spark else None
    first = next((b for b in spark if b is not None), None)
    ints = its and all(isinstance(r["objective"], int) for r in its if r["objective"] is not None)
    k = {"id": "best", "label": "Best objective", "value": last, "unit": objective["unit"],
         "decimals": 0 if ints else 3, "better": objective["direction"], "spark": spark,
         "from": f"{objective['name']}, best admissible over {len(its)} iteration{'s' if len(its) != 1 else ''}",
         "delta": pct_change(first, last) if (first is not None and last is not None and len(its) > 1) else None,
         "tone": "good" if (first is not None and last is not None and last != first) else "neutral",
         "source": "ledger.jsonl + solutions/*/meta.json"}
    if last is None:
        k["why"] = "no admissible solution yet" if its else "no solution scored yet"
    return k


def kpi_admissible(its: list[dict], source: str) -> dict:
    adm, share = 0, []
    for k, r in enumerate(its, 1):
        adm += bool(r["admissible"])
        share.append(round(100.0 * adm / k, 1))
    out = {"id": "admissible", "label": "Admissible share", "value": share[-1] if share else None, "unit": "%",
           "decimals": 1, "better": "higher", "spark": share,
           "from": f"{adm} of {len(its)} iterations pass every gate", "delta": None, "tone": "neutral", "source": source}
    if not its:
        out["why"] = "no solution scored yet"
    return out


def report_files(t: Tree) -> list[dict]:
    want = []
    fixed = [("PROGRESS.md", "digest", "Progress"), ("site/index.html", "landing page", "The landing page"),
             ("site/proposals/index.html", "proposal round", "Proposal round")]
    for path, kind, title in fixed:
        if path in t.fileset:
            want.append((path, kind, title))
    for path in t.files:
        if re.match(r"^site/(views/)?[^/]+\.svg$", path):
            want.append((path, "chart", Path(path).stem.replace("_", " ").capitalize()))
        elif path.startswith("reports/") and path.endswith(".html"):
            want.append((path, "report", Path(path).name))
        elif re.match(r"^docs/peps/[^/]+\.md$", path):
            want.append((path, "decision record", Path(path).name))
        elif re.match(r"^ablations/[^/]+\.md$", path):
            want.append((path, "ablation study", f"Ablation study {Path(path).stem}"))
    out = []
    for path, kind, title in want:
        last = t.last_change(path) or {}
        first = t.git("log", t.sha, "--diff-filter=A", "--format=%cI", "--", path).split()
        out.append({"path": path, "kind": kind, "title": title, "date": last.get("date"), "sha": last.get("sha"),
                    "format": Path(path).suffix.lstrip(".") or None, "added": first[-1] if first else None})
    out.sort(key=lambda r: (-ts(r["date"]), r["path"]))
    return out


def simple_yaml(block: str) -> dict:
    """A front matter block's simple YAML: `key: value`, `key: [a, b]` and `key:` followed by `- item` lines, as lists.
    WHY lists: feedback/*.md writes `specs: [O4.3, O4.2]` (trajectory_tracking_agent 79ccd4a); read as a string, the
    Spec link was lost (lane FS, 2026-11-24)."""
    meta, key = {}, None
    unq = lambda s: s.strip().strip('"').strip("'")  # noqa: E731
    for line in block.splitlines():
        if re.match(r"^\s*-\s+", line) and key is not None:
            meta[key] = (meta[key] if isinstance(meta.get(key), list) else []) + [unq(line.split("-", 1)[1])]
        elif ":" in line and not line.startswith((" ", "-", "#")):
            key, v = (s.strip() for s in line.split(":", 1))
            if v.startswith("[") and v.endswith("]"):
                meta[key] = [unq(x) for x in v[1:-1].split(",") if x.strip()]
            else:
                meta[key] = unq(v) if v else []
    return meta


def front_matter_rows(t: Tree, folder: str) -> list[dict]:
    """feedback/, audits/, agents/: one row per Markdown file, its simple `key: value` front matter and first heading."""
    rows = []
    for path in sorted(p for p in t.files if p.startswith(folder + "/") and p.endswith(".md")):
        text = t.text(path) or ""
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        meta = simple_yaml(m.group(1)) if m else {}
        if folder == "feedback":  # the contract's names (§3.2: spec[], date) beside the file's own (specs, added)
            if "spec" not in meta and isinstance(meta.get("specs"), list):
                meta["spec"] = meta["specs"]
            if "date" not in meta and meta.get("added"):
                meta["date"] = meta["added"]
        title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("# ")), Path(path).stem)
        row = {"path": path, "title": title, **meta}
        if folder == "feedback":  # Zach 2026-11-24: feedback/*.md = front matter + ## Observed / ## Desired / ## Why
            body = text[m.end():] if m else text
            parts, cur = {}, None
            for line in body.splitlines():
                if line.startswith("## "):
                    cur = line[3:].strip().lower()
                    parts[cur] = []
                elif cur is not None:
                    parts[cur].append(line)
            for key in ("observed", "desired", "why"):
                if key in parts:
                    row[key] = "\n".join(parts[key]).strip() or None
            # plain text for now; TODO: data-ui's markdown rows + side panel (lane MD) once data-ui is re-vendored
            row["description"] = "\n".join(l for l in body.splitlines() if not l.startswith("# ")).strip() or None
        rows.append(row)
    return rows


# ── standard agent repos ─────────────────────────────────────────────────────────────────────────────────────────
def gate_columns(row: dict, gates: list[dict]) -> dict:
    """The flat fields a row view's presets name (CONTRACT §16.1; proposals-pages/iterations.base): who proposed it, how
    many gate failures, and pass/fail per OBJECTIVES.md gate. Read from the row's own fields, nothing new."""
    fg = row.get("failed_gates") or {}
    row["proposer"] = (row.get("proposed_by") or {}).get("agent")
    row["failed_tasks"] = sum(fg.values())
    for g in gates:
        row[f"g_{g['id']}"] = "fail" if fg.get(g["id"]) else "pass"
    return row


def proposer_row(agent, model, sids: list[str], its: list[dict], ablations: list[dict], metas: dict, direction: str) -> dict:
    """agents.proposers (CONTRACT §16.1): one backfilled proposer (a meta.json proposed_by group) and what its solutions
    did, read from the iteration and ablation rows (proposals-pages/agents.base names these fields)."""
    mine = set(sids)
    it = [r for r in its if r["id"] in mine]
    adm = [r for r in it if r["admissible"] and r["objective"] is not None]
    best = (min if direction == "lower" else max)(adm, key=lambda r: r["objective"]) if adm else None
    created = sorted(c for c in (metas[s].get("created") for s in sids) if c)
    return {"agent": agent, "model": model, "solutions": len(sids), "kind": "proposer", "iterations": len(it),
            "kept": sum(r["verdict"] == "kept" for r in it), "failed": sum(r["verdict"] == "failed" for r in it),
            "best": best["objective"] if best else None, "best_id": best["id"] if best else None,
            "study_runs": sum(1 for r in ablations if r["id"] in mine),
            "start": created[0] if created else None, "end": created[-1] if created else None,
            "source": "solutions/*/meta.json proposed_by (backfilled)"}


def activity_recent(t: Tree, ledger: list[dict], metas: dict) -> list[dict]:
    """activity.recent (CONTRACT §16.1): the same events activity.rows counts when backfilled (each commit of the ref,
    each ledger row), newest first. `who` is the commit's author or the solution's proposer."""
    rows = []
    out = t.git("log", t.sha, "--format=%h%x1f%cI%x1f%an%x1f%s")
    for line in out.splitlines():
        sha, date, author, subject = line.split("\x1f", 3)
        rows.append({"t": date, "day": date[:10], "kind": "commit", "what": subject, "who": author, "commit": sha,
                     "solution": None, "verdict": None, "objective": None})
    for r in ledger:
        sid = r.get("solution")
        split = r.get("split")
        study = "ablation" in ((metas.get(sid) or {}).get("tags") or [])
        kind = "study run" if study else {"dev": "evaluation", "holdout": "holdout"}.get(split, split or "evaluation")
        obj = finite(r.get("objective"))
        verdict = None if obj is None else ("admissible" if r.get("admissible") is True else "failed a gate")
        rows.append({"t": r.get("t"), "day": (r.get("t") or "")[:10] or None, "kind": kind,
                     "what": f"{sid} scored on {split}" + (f" ({r.get('ruler')})" if r.get("ruler") else ""),
                     "who": ((r.get("proposed_by") or (metas.get(sid) or {}).get("proposed_by") or {}).get("agent")),
                     "commit": (r.get("repo_commit") or "")[:7] or None, "solution": sid, "verdict": verdict, "objective": obj})
    rows.sort(key=lambda r: -ts(r["t"]))
    return rows


def added_in(t: Tree) -> dict[str, dict]:
    """solution id -> the box commit that first added solutions/<id>/meta.json."""
    out = t.git("log", t.sha, "--diff-filter=A", "--format=@%H%x1f%cI%x1f%s", "--name-only", "--", "solutions/")
    oldest: dict[str, dict] = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("@"):
            sha, date, subject = line[1:].split("\x1f", 2)
            cur = {"sha": sha, "date": date, "subject": subject, "where": "this repo"}
        elif line.endswith("/meta.json") and cur and line.count("/") == 2:
            oldest[line.split("/")[1]] = cur  # newest first: the last write is the oldest add
    return oldest


def gates_slice(t: Tree, obj: dict, its: list[dict], fallback_failed: dict | None) -> list[dict] | None:
    if not obj["gates"]:
        return None
    best = next((r for r in reversed(its) if r["verdict"] == "kept"), None) or (its[-1] if its else None)
    card = t.json(f"solutions/{best['id']}/scorecard.json") if best else None
    out = []
    for g in obj["gates"]:
        row = {"id": g["id"], "pass_when": g["pass_when"], "why": g["why"], "op": None, "threshold": None,
               "of": best["id"] if best else None, "passed": None, "failed_tasks": None, "tasks": None,
               "worst": None, "worst_task": None, "margin": None, "unit": unit_of(g["id"]) or None, "source": None}
        if best is None:
            row["why_null"] = "no solution scored yet"
        elif card and not isinstance((card.get("gates") or {}).get(g["id"], {}), dict):
            # a box whose scorecard records each gate as one pass/fail (claude_party_agent): no threshold, no margin
            failed = (card.get("failed_gates") or {}).get(g["id"])
            row.update({"passed": card["gates"][g["id"]] is True, "failed_tasks": finite(failed) if failed is not None else None,
                        "tasks": len(card.get("tasks") or []) or None, "source": f"solutions/{best['id']}/scorecard.json",
                        "why_null": "pass/fail gate: no margin"})
        elif card and g["id"] in (card.get("gates") or {}):
            spec = card["gates"][g["id"]]
            tasks = card.get("tasks") or []
            row.update({"op": spec.get("op"), "threshold": finite(spec.get("threshold")),
                        "failed_tasks": len(spec.get("failed_tasks") or []), "tasks": len(tasks),
                        "source": f"solutions/{best['id']}/scorecard.json"})
            row["passed"] = row["failed_tasks"] == 0
            # the gate's own per-task measure: the kpi of the same name (or "<gate>_violations")
            values = []
            for task in tasks:
                kp = task.get("kpis") or {}
                v = kp.get(g["id"], kp.get(g["id"] + "_violations"))
                if isinstance(v, bool):
                    continue
                v = finite(v)
                if v is not None:
                    values.append((v, task.get("task")))
            thr, op = row["threshold"], row["op"]
            if values and thr is not None and op in ("<=", "<", ">=", ">"):
                lower = op in ("<=", "<")
                worst = max(values) if lower else min(values)
                row["worst"], row["worst_task"] = worst[0], worst[1]
                row["margin"] = (thr - worst[0]) if lower else (worst[0] - thr)
            else:
                row["why_null"] = "pass/fail gate: no margin" if op == "is" else "no per-task value recorded"
        else:
            failed = (best.get("failed_gates") or {}) if best else {}
            row["passed"] = g["id"] not in failed
            row["failed_tasks"] = failed.get(g["id"], 0)
            row["source"] = "ledger.jsonl failed_gates"
            row["why_null"] = "the box records no per-task gate values"
        out.append(row)
    return out


# ── per solution, per gate: why a cell is red (bb-gates' timeline view, CONTRACT §16.7) ─────────────────────────────
# WHY here and not a plug-in slice: these are fields of the iterations / ablations rows (S0's slices), so the gate
# history reads them from the slices it already declares; a plug-in returns a whole slice of its own.
_fold_runs = None
# a saved run's lane has no worded peak for these two gates: word it as the lane's own label does (lane G's runs.py)
PEAK_WORDS = {"saturation_share_pct": "highest joint torque {:.0f} % of its cap",
              "limit_violations": "fastest joint {:.0f} % of its speed limit"}


def fold_runs():
    """viewer/tools/fold_runs.py: the codec for a box's saved playback, one reader for the run records and the moments."""
    global _fold_runs
    if _fold_runs is None:
        spec = importlib.util.spec_from_file_location("bb_fold_runs", HERE / "fold_runs.py")
        _fold_runs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_fold_runs)
    return _fold_runs


class SavedRuns:
    """The runs a box's export saved at the ref (trajectory_tracking_agent: site/data/playback/, written by its
    tools/build_site.py from `tta evaluate`'s run records; codec TTAPLAY1). Each record is decoded once, by the same
    fold_runs.tta_record that writes the bb-run/1 records bb-evidence plays, so a moment here is the one the player shows."""

    INDEX = "site/data/playback/index.json"
    # WHY: from trajectory_tracking_agent 581e83e the export writes the bb-run/1 records themselves (site/data/runs/,
    # one JSON per run, listed in runs/index.json) and retires the TTAPLAY1 binaries; read whichever the ref has.
    RUNS_INDEX = "site/data/runs/index.json"

    def __init__(self, t: Tree):
        self.t = t
        self.index = t.json(self.INDEX) if self.INDEX in t.fileset else None
        self.runs_index = t.json(self.RUNS_INDEX) if self.index is None and self.RUNS_INDEX in t.fileset else None
        self.by = {s["id"]: s.get("tasks") or {} for s in (self.index or self.runs_index or {}).get("solutions") or []}
        self.cache: dict = {}

    @property
    def saved(self) -> bool:
        return self.index is not None or self.runs_index is not None

    def has(self, sid: str, task: str) -> bool:
        return task in self.by.get(sid, {})

    def gates(self, sid: str, task: str) -> dict:
        key = (sid, task)
        if key not in self.cache:
            try:
                if self.index is not None:
                    rec = fold_runs().tta_record(self.t, self.index, sid, task, f"{sid} on {task}")
                else:
                    rec = self.t.json(f"site/data/{self.by[sid][task]['record']}")
                out = {}
                for m in rec["metrics"]:
                    if m.get("kind") != "gate":
                        continue
                    ev = m.get("evidence") or {}
                    peak = dict(ev["peak"]) if ev.get("peak") else None
                    if peak and not peak.get("label") and m["id"] in PEAK_WORDS:
                        peak["label"] = PEAK_WORDS[m["id"]].format(peak["value"])
                    out[m["id"]] = {"passed": m.get("passed"), "red": ev.get("flags") or [],
                                    "peak": {k: peak[k] for k in ("t", "value", "label") if k in peak} if peak else None}
                self.cache[key] = {"duration_s": rec["time"]["t"][-1], "gates": out}
            except (AssertionError, KeyError, ValueError, FileNotFoundError, RuntimeError) as e:
                self.cache[key] = {"why": f"the saved run could not be read: {e}"}
        return self.cache[key]


def gate_results(t: Tree, row: dict, gates: list[dict], runs: SavedRuns) -> dict | None:
    """One solution's own verdict on each OBJECTIVES.md gate, from its dev scorecard (the ruler's output, never its code):
    the failing tasks with the gate's per-task value and the ruler's note on that task, the worst task and the margin
    (positive = inside the limit), and where the box saved a run of a failing task, the moment in it: the red spans, the
    run's length, its worst instant. Null with a why where the box records less; never a number it did not write."""
    card = t.json(f"solutions/{row['id']}/scorecard.json")
    if not card or card.get("split") != "dev":
        return None
    tasks = [x for x in card.get("tasks") or [] if isinstance(x, dict)]
    task_ids = [x.get("task", x.get("id")) for x in tasks]
    per_task = dict(zip(task_ids, tasks))
    ledger_failed = row.get("failed_gates") or {}
    out = {}
    for g in gates:
        spec = (card.get("gates") or {}).get(g["id"])
        if spec is None:
            continue
        res = {"failed": None, "failed_tasks": None, "tasks": len(tasks) or None, "worst": None, "worst_task": None, "margin": None}
        if not isinstance(spec, dict):
            # a box whose scorecard records each gate as one pass/fail (claude_party_agent): it names no failing task
            n = (card.get("failed_gates") or {}).get(g["id"])
            res.update({"failed_tasks": finite(n) if n is not None else (0 if spec is True else None),
                        "why_null": "pass/fail gate: the scorecard names no failing task and records no margin"})
            out[g["id"]] = res
            continue
        failed = [x for x in spec.get("failed_tasks") or [] if x in per_task]
        op, thr = spec.get("op"), finite(spec.get("threshold"))

        def value(task):
            kp = per_task[task].get("kpis") or {}
            v = kp.get(g["id"], kp.get(g["id"] + "_violations"))
            return v if isinstance(v, bool) else finite(v)

        res["failed"] = [{"task": x, "value": value(x), "note": "; ".join(per_task[x].get("notes") or []) or None} for x in failed]
        res["failed_tasks"] = len(failed)
        values = [(value(x), x) for x in task_ids]
        values = [(v, x) for v, x in values if v is not None and not isinstance(v, bool)]
        if values and thr is not None and op in ("<=", "<", ">=", ">"):
            lower = op in ("<=", "<")
            worst = max(values, key=lambda p: p[0]) if lower else min(values, key=lambda p: p[0])
            res["worst"], res["worst_task"] = worst[0], worst[1]
            res["margin"] = (thr - worst[0]) if lower else (worst[0] - thr)
        else:
            res["why_null"] = "pass/fail gate: no margin" if op == "is" else "no per-task value recorded"
        if len(failed) != int(ledger_failed.get(g["id"], 0)):
            res["why"] = (f"scorecard.json names {len(failed)} failing tasks, the ledger row {int(ledger_failed.get(g['id'], 0))}: "
                          "the scorecard is shown")
        moments = []
        for x in failed:
            if not runs.has(row["id"], x):
                continue
            rec = runs.gates(row["id"], x)
            if "why" in rec:
                moments.append({"task": x, "why": rec["why"]})
            elif g["id"] in rec["gates"]:
                moments.append({"task": x, "duration_s": rec["duration_s"], **rec["gates"][g["id"]]})
        if failed and runs.saved:  # absent: the box saved no runs at this ref (no playback export)
            res["moments"] = moments
        out[g["id"]] = res
    return out


def fold_standard(t: Tree) -> tuple[dict, dict]:
    readme = t.text("README.md") or ""
    name = next((l[2:].strip() for l in readme.splitlines() if l.startswith("# ")), Path(t.repo).name)
    status = t.json("status.json") or {}
    obj_doc = objectives(t.text("OBJECTIVES.md") or "")
    unit = unit_of(obj_doc["name"])
    links = status.get("links") or {}
    kpi = status.get("kpi") or {}
    objective = {"name": obj_doc["name"], "label": obj_doc["name"], "unit": unit, "direction": obj_doc["direction"],
                 "ruler": obj_doc["ruler"], "frozen": obj_doc["frozen"],
                 "target": finite(kpi.get("target")) if (kpi.get("name") or "").startswith(obj_doc["name"] or "\0") else None}

    ledger = [json.loads(l) for l in (t.text("ledger.jsonl") or "").splitlines() if l.strip()]
    ruler = ledger[-1].get("ruler") if ledger else obj_doc["ruler"]
    first_dev, dev, hold = {}, {}, {}
    for r in ledger:  # append order: the newest row per (solution, split) on the current ruler wins
        sid = r.get("solution")
        if not sid:
            continue
        if r.get("split") == "dev":
            first_dev.setdefault(sid, r.get("t"))
            if r.get("ruler") == ruler:
                dev[sid] = r
        elif r.get("split") == "holdout" and r.get("ruler") == ruler:
            hold[sid] = r

    ids = sorted({p.split("/")[1] for p in t.files if re.match(r"^solutions/[^/]+/meta\.json$", p)}, key=natural)
    metas = {sid: t.json(f"solutions/{sid}/meta.json") or {} for sid in ids}
    adds = added_in(t)
    gen: dict[str, int] = {}

    def generation(sid: str, seen=()) -> int:
        if sid not in gen:
            p = metas.get(sid, {}).get("parent")
            gen[sid] = 0 if not p or p not in metas or p in seen else generation(p, seen + (sid,)) + 1
        return gen[sid]

    def row(sid: str) -> dict:
        m, d = metas[sid], dev[sid]
        src = m.get("source") or {}
        if src.get("created_commit"):  # imported from upstream: the commit axis is where it was written (headliner rule)
            commit = {"sha": src["created_commit"], "date": m.get("created"), "subject": src.get("created_commit_subject"),
                      "where": "upstream (meta.json source)"}
        else:
            commit = adds.get(sid)
        pb = m.get("proposed_by") or d.get("proposed_by") or {}
        fg = d.get("failed_gates") or {}
        fg = {g: 1 for g in fg} if isinstance(fg, list) else {g: int(n) for g, n in fg.items() if n}
        out = {"n": None, "id": sid, "parent": m.get("parent"), "verdict": None, "objective": finite(d.get("objective")),
               "best_so_far": None, "admissible": d.get("admissible") is True, "evaluated": first_dev.get(sid),
               "created": m.get("created"), "change": m.get("change") or d.get("change"), "tags": m.get("tags") or [],
               "gen": generation(sid),
               "proposed_by": {"agent": pb.get("agent"), "model": pb.get("model"), "backfilled": bool(pb.get("backfilled"))} if pb else None,
               "failed_gates": fg, "gate_pass_rate": finite(d.get("gate_pass_rate")),
               "holdout": finite((hold.get(sid) or {}).get("objective")), "commit": commit, "best_holder": None}
        return gate_columns(out, obj_doc["gates"])

    scored = [sid for sid in ids if sid in dev]
    order = sorted(scored, key=lambda s: (ts(first_dev.get(s)), ts(metas[s].get("created")), natural(s)))
    its = [row(s) for s in order if "ablation" not in (metas[s].get("tags") or [])]
    judge(its, objective["direction"])
    ablations = []
    for s in order:
        if "ablation" in (metas[s].get("tags") or []):
            r = row(s)
            r["verdict"] = "ablation"
            before = [i["n"] for i in its if ts(i["evaluated"]) <= ts(r["evaluated"])]
            r["after"] = max(before) if before else None
            ablations.append(r)
    if obj_doc["gates"]:
        runs = SavedRuns(t)
        for r in its + ablations:
            res = gate_results(t, r, obj_doc["gates"], runs)
            if res is not None:
                r["gate_results"] = res
    unscored = [{"id": s, "parent": metas[s].get("parent"), "change": metas[s].get("change"), "created": metas[s].get("created")}
                for s in ids if s not in dev]

    # ideas.md now, and its open "I'll try" count at every committed version up to the ref
    ideas_text = t.text("ideas.md")
    ideas = ideas_rows(ideas_text) if ideas_text is not None else []
    history = []
    if ideas_text is not None:
        for line in t.git("log", t.sha, "--format=%H", "--", "ideas.md").splitlines()[::-1]:
            rows = ideas_rows(t.git("show", f"{line}:ideas.md"))
            history.append(sum(1 for i in rows if i["lane"] == "agent" and i["open"]))

    kpis = [kpi_best(its, objective), kpi_admissible(its, "ledger.jsonl (admissible)")]
    if ideas_text is not None:
        open_now = sum(1 for i in ideas if i["lane"] == "agent" and i["open"])
        kpis.append({"id": "ideas", "label": "Open ideas", "value": open_now, "unit": "", "decimals": 0, "better": "higher",
                     "spark": history, "from": f"ideas.md “I'll try”, over its {len(history)} committed version{'s' if len(history) != 1 else ''}",
                     "delta": None, "tone": "bad" if open_now <= 2 else "neutral", "source": "ideas.md (git history)"})
    if kpi and not (kpi.get("name") or "").startswith(obj_doc["name"] or "\0"):
        live = [r for r in ledger if r.get("split") == "live"]
        k = {"id": "status_kpi", "label": kpi.get("name"), "value": finite(kpi.get("value")), "unit": kpi.get("unit") or "",
             "decimals": sig_decimals(finite(kpi.get("value"))), "better": "lower" if kpi.get("direction") == "down" else "higher",
             "spark": [finite(r.get("objective")) for r in live],
             "from": "status.json kpi" + (f"; sparkline: {len(live)} daily live rows of ledger.jsonl" if live else ""),
             "delta": None, "tone": "neutral", "source": "status.json"}
        if kpi.get("target") is not None:
            k["delta"] = f"target {kpi['target']}"
        kpis.append(k)
    ck = status.get("counter_kpi") or {}
    if ck.get("name"):
        v = finite(ck.get("value"))
        kpis.append({"id": "counter_kpi", "label": ck["name"], "value": v, "unit": ck.get("unit") or "",
                     "decimals": sig_decimals(v), "better": None, "spark": [],
                     "from": "status.json counter_kpi (reporting only)", "delta": None, "tone": "neutral", "source": "status.json"})

    commits = t.git("log", t.sha, "--format=%H").split()
    activity_text = t.text("activity.jsonl")
    proposers = Counter()
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for sid in sorted(ids, key=lambda s: ts(metas[s].get("created"))):
        pb = metas[sid].get("proposed_by") or {}
        groups.setdefault((pb.get("agent"), pb.get("model"), pb.get("session")), []).append(sid)
        proposers[pb.get("agent")] += 1
    agent_files = [p for p in t.files if re.match(r"^agents/[^/]+\.md$", p)]
    reports = report_files(t)

    state = {
        "schema": "bb-state/1", "box": name, "ref": t.sha[:7], "read_at": t.date(), "ref_date": t.date(),
        "about": {"repo": Path(t.repo).name, "url": web(links.get("repo")), "site": web(links.get("site") or links.get("pages")),
                  "remit": status.get("remit")},
        "objective": objective,
        "kpis": kpis,
        "iterations": its,
        "ablations": ablations,
        "unscored": unscored,
        "needs": needs_from(ideas, status),
        "ideas": ideas,
        "gates": gates_slice(t, obj_doc, its, None),
        "feedback": front_matter_rows(t, "feedback"),
        "audits": front_matter_rows(t, "audits"),
        "agents": {"registered": len(agent_files), "backfilled": len(groups) if ids else 0,
                   "proposers": [proposer_row(a, m, s, its, ablations, metas, objective["direction"]) for (a, m, _), s in groups.items()]},
        "activity": ({"rows": len([l for l in activity_text.splitlines() if l.strip()]), "backfilled": False}
                     if activity_text is not None else {"rows": len(commits) + len(ledger), "backfilled": True,
                                                        "recent": activity_recent(t, ledger, metas)}),
        "reports": len(reports),
        "report_files": reports,
    }
    if state["gates"] is None:
        del state["gates"]
    facts = {"tree": t, "status": status, "objectives": obj_doc, "ledger": ledger, "metas": metas, "state": state}
    return state, facts


# ── robot_controllers' population grade ──────────────────────────────────────────────────────────────────────────
def fold_rc(t: Tree, arm: str) -> tuple[dict, dict]:
    path = "results/grade/results.json"
    res = t.json(path)
    readme = t.text("README.md") or ""
    name = next((l[2:].strip() for l in readme.splitlines() if l.startswith("# ")), Path(t.repo).name)
    summ = res["summary"][arm]
    base = summ["base_scenario"]
    head = summ["headline"]["accuracy"]
    metric = head["metric"]
    graded = t.last_change(path)  # the commit that wrote this grade
    code = res["generated"]["commit"]
    try:
        code_commit = {"sha": t.git("rev-parse", code).strip(), "date": t.date(code),
                       "subject": t.git("log", "-1", "--format=%s", code).strip(), "where": "this repo (the graded code)"}
    except RuntimeError:
        code_commit = {"sha": code, "date": None, "subject": None, "where": "results.json generated.commit"}
    rows = {r["config"]: r for r in res["rows"] if r["arm"] == arm and r["scenario"] == base}
    unit = unit_of(metric)
    objective = {"name": metric, "label": f"{metric} on {base}", "unit": unit, "direction": "lower",
                 "ruler": res.get("schema"), "frozen": res["generated"].get("date"), "target": None}
    its = []
    for cfg in res["population"]:
        r = rows.get(cfg["config"])
        if not r:
            continue
        its.append({"n": None, "id": cfg["config"], "parent": None, "verdict": None,
                    "objective": finite((r.get("metrics") or {}).get(metric)), "best_so_far": None,
                    "admissible": r.get("passed") is True, "evaluated": graded["date"], "created": graded["date"],
                    "change": cfg.get("title"), "tags": [f"ff={cfg.get('feedforward')}", f"fb={cfg.get('feedback')}",
                                                         f"lookahead={cfg.get('lookahead_mode')}", f"interp={cfg.get('interpolation')}"],
                    "gen": 0, "proposed_by": None,
                    "failed_gates": {g: 1 for g in (r.get("failed_gates") or [])}, "gate_pass_rate": None, "holdout": None,
                    "commit": code_commit, "best_holder": None})
        gate_columns(its[-1], [])
    judge(its, "lower")
    cards = summ.get("cards") or {}
    cards = dict(cards) if isinstance(cards, list) else cards
    every = sum(1 for c in cards.values() if c.get("rows") and c.get("passed") == c.get("rows"))
    kpis = [kpi_best(its, objective), kpi_admissible(its, f"{path} rows (passed) on the base scenario")]
    kpis[0]["source"] = path
    kpis[0]["from"] = f"{metric} on {arm}'s base scenario, best passing config of {len(its)}"
    kpis[0]["delta"] = None  # a population graded at once has no "since iteration 1"
    if cards:
        kpis.append({"id": "every_scenario", "label": "Configs passing every scenario", "value": every, "unit": f"of {len(cards)}",
                     "decimals": 0, "better": "higher", "spark": [],
                     "from": f"summary.{arm}.cards over {len(summ.get('scenarios') or [])} scenarios", "delta": None,
                     "tone": "neutral", "source": path})
    state = {
        "schema": "bb-state/1", "box": name, "ref": t.sha[:7], "read_at": graded["date"], "ref_date": graded["date"],
        "about": {"repo": Path(t.repo).name, "url": None, "site": None, "remit": next(
            (p.strip() for p in readme.split("\n\n")[1:] if p.strip() and not p.startswith(("#", "!", "|", "```"))), None)},
        "objective": objective, "kpis": kpis, "iterations": its, "ablations": [], "unscored": [],
        "needs": [], "reports": 0, "report_files": [],
    }
    reports = report_files(t)
    state["reports"], state["report_files"] = len(reports), reports
    return state, {"tree": t, "results": res, "state": state}


# ── plug-in slices (wave 2) and the driver ───────────────────────────────────────────────────────────────────────
def plugin_slices(facts: dict) -> None:
    folder = HERE / "folds"
    for mod_path in sorted(folder.glob("*.py")) if folder.exists() else []:
        if mod_path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"bbfold_{mod_path.stem}", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        value = mod.fold(facts)
        if value is not None:
            facts["state"][mod_path.stem] = value


def fold(kind: str, repo: str, ref: str, arm: str = "ur5e", spec_map: str | None = None, junit: str | None = None,
         junit_dir: str | None = None) -> dict:
    t = Tree(repo, ref)
    state, facts = fold_rc(t, arm) if kind == "rc" else fold_standard(t)
    # the spec slice's inputs (CONTRACT §16.1), paths relative to viewer/: a spec map, a junit XML of a run at the ref;
    # §16.8: a directory of junit XMLs, one per commit (<sha7>.xml or .xml.gz), for the spec_history slice
    facts["spec_map"], facts["junit"], facts["junit_dir"] = spec_map, junit, junit_dir
    plugin_slices(facts)
    state["source"] = {"fold": "viewer/tools/fold_state.py", "repo": Path(t.repo).name, "ref": t.sha, "read": sorted(t.read)}
    if facts.get("ran"):  # a box's own tool a plug-in ran on an archive of the ref (CONTRACT §16.1: costs)
        state["source"]["ran"] = facts["ran"]
    return state


def dump(state: dict) -> str:
    return json.dumps(state, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--kind", choices=["standard", "rc"], default="standard")
    ap.add_argument("--arm", default="ur5e")
    ap.add_argument("--out")
    ap.add_argument("--spec-map", help="a blackbox-spec-map/1 JSON, relative to viewer/ (the spec slice's rows)")
    ap.add_argument("--junit", help="a junit XML of a test run at the ref, relative to viewer/ (the spec slice's counts)")
    ap.add_argument("--junit-dir", help="a directory of junit XMLs, one per commit (<sha7>.xml[.gz]), relative to viewer/ (spec_history)")
    ap.add_argument("--all", action="store_true", help="every scenario in scenarios/scenarios.json")
    ap.add_argument("--check", action="store_true", help="with --all: re-fold and compare, write nothing")
    a = ap.parse_args()
    if a.all:
        listing = json.loads((SCENARIOS / "scenarios.json").read_text())
        stale = []
        for sc in listing["scenarios"]:
            text = dump(fold(sc["kind"], sc["repo"], sc["ref"], sc.get("arm", "ur5e"), sc.get("spec_map"), sc.get("junit"), sc.get("junit_dir")))
            out = SCENARIOS / sc["name"] / "state.json"
            if a.check:
                if not out.exists() or out.read_text() != text:
                    stale.append(sc["name"])
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text)
                s = json.loads(text)
                print(f"{sc['name']:14} {s['box']} @ {s['ref']}: {len(s.get('iterations', []))} iterations, "
                      f"{len(s.get('ablations', []))} ablations, {len(s.get('unscored', []))} unscored, "
                      f"{len(s.get('needs', []))} needs, {len(s.get('kpis', []))} kpis")
        if a.check:
            print("stale: " + ", ".join(stale) if stale else f"all {len(listing['scenarios'])} scenarios re-fold identically")
            return 1 if stale else 0
        return 0
    if not a.repo:
        ap.error("--repo (or --all) is required")
    text = dump(fold(a.kind, a.repo, a.ref, a.arm, a.spec_map, a.junit, a.junit_dir))
    if a.out:
        Path(a.out).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
