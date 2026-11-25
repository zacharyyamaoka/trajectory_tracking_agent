"""Read one black-box agent repo at a pinned commit and write the facts every proposal builds on: _data/box.json.

    python3 extract.py --repo ~/trajectory_tracking_agent --ref 79b2625 \
        --junit <clean run junit.xml> [--lane-junit <working-tree run junit.xml>]

Read-only: every file is read through `git show <ref>:<path>` and `git log <ref>`, never from the working tree, so a
peer's in-flight files are never read and the build is reproducible. Nothing here writes into the repo.

What it records, and nothing else (never invented; a missing thing is null or an empty list, said plainly):
- the repo, the ref, its commit time, and how many working-tree changes it did NOT read;
- OBJECTIVES.md's title, sections and gates table; status.json;
- every solution folder (meta.json, scorecard.json, scorecard_holdout.json) and the commit that added it;
- every ledger row (the metrics out, never a solution's code);
- ideas.md, parsed by the idea-queue lane's lossless parser (proposals-ideas/_shared/ideas_parse.py, imported read-only),
  and the open-idea count at every committed version of ideas.md;
- git log: sha, author, time, subject, trailers, files;
- the test run(s): one row per test node id with pass / fail (from pytest's junit xml);
- the files that are reports (README's table, PROGRESS.md, site pages, reports/, ablation studies, docs/peps/).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IDEAS_LANE = os.path.join(os.path.dirname(ROOT), "proposals-ideas", "_shared")


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def show(repo: str, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", repo, "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def show_json(repo: str, ref: str, path: str):
    text = show(repo, ref, path)
    return json.loads(text) if text else None


# ── OBJECTIVES.md ────────────────────────────────────────────────────────────────────────────────────────────────
def objectives(text: str) -> dict:
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip() if lines else ""
    sections = []
    for i, line in enumerate(lines):
        m = re.match(r"^## (\d+)\. (.+)$", line)
        if m:
            sections.append({"n": int(m.group(1)), "title": m.group(2).strip(), "line": i + 1})
    gates = []
    in_gates = False
    for line in lines:
        if line.startswith("| Gate |"):
            in_gates = True
            continue
        if in_gates:
            if not line.startswith("|"):
                in_gates = False
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set(cells[0]) <= {"-", " "}:
                continue
            gates.append({"id": cells[0].strip("`"), "pass_when": cells[1], "why": cells[2]})
    ruler = re.search(r"ruler (v\d+), frozen (\d{4}-\d\d-\d\d)", title)
    objective = re.search(r"\*\*Objective \(one number, (lower|higher) is better\): `([a-z_]+)`\*\*", text)
    return {"title": title, "ruler": ruler.group(1) if ruler else None, "frozen": ruler.group(2) if ruler else None,
            "sections": sections, "gates": gates,
            "objective": objective.group(2) if objective else None,
            "direction": ("lower" if objective and objective.group(1) == "lower" else "higher") if objective else None}


# ── git log ──────────────────────────────────────────────────────────────────────────────────────────────────────
SEP = "\x1e"


def commits(repo: str, ref: str) -> list[dict]:
    fmt = "\x1f" + SEP.join(["%H", "%h", "%an", "%aI", "%s", "%(trailers:unfold,only)"]) + "\x1d"
    out = git(repo, "log", ref, f"--format={fmt}", "--name-only")
    rows = []
    for chunk in out.split("\x1f"):
        if not chunk.strip():
            continue
        head, _, files = chunk.partition("\x1d")
        parts = head.split(SEP)
        if len(parts) < 6:
            continue
        sha, short, author, date, subject, trailers = parts[:6]
        tr = []
        for line in trailers.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                tr.append({"key": k.strip(), "value": v.strip()})
        names = [f for f in files.strip().splitlines() if f.strip()]
        rows.append({"sha": sha, "short": short, "author": author, "date": date, "subject": subject,
                     "trailers": tr, "files": len(names),
                     "solutions": sorted({f.split("/")[1] for f in names if f.startswith("solutions/") and f.count("/") >= 2}),
                     "touches": sorted({f.split("/")[0] for f in names})})
    return rows


def added_in(repo: str, ref: str) -> dict[str, str]:
    """solution id -> short sha of the commit that added its meta.json."""
    out = git(repo, "log", ref, "--diff-filter=A", "--format=@%h", "--name-only", "--", "solutions/")
    # git log is newest first; a re-added file shows twice, and the OLDEST add is the one kept (the last written).
    oldest: dict[str, str] = {}
    sha = None
    for line in out.splitlines():
        if line.startswith("@"):
            sha = line[1:]
        elif line.endswith("/meta.json") and sha:
            oldest[line.split("/")[1]] = sha
    return oldest


# ── tests ────────────────────────────────────────────────────────────────────────────────────────────────────────
def junit(path: str) -> dict:
    root = ET.parse(path).getroot()
    suite = next(root.iter("testsuite"))
    rows = []
    for tc in root.iter("testcase"):
        status = "pass"
        for ch in tc:
            if ch.tag in ("failure", "error"):
                status = "fail"
            elif ch.tag == "skipped":
                status = "skip"
        cls = tc.attrib.get("classname", "")
        file = "tests/" + cls.split(".")[-1] + ".py" if cls.startswith("tests.") else cls
        name = tc.attrib["name"]
        rows.append({"id": f"{file}::{name}", "file": file, "fn": re.sub(r"\[.*$", "", name), "status": status})
    a = suite.attrib
    return {"tests": int(a["tests"]), "failures": int(a["failures"]), "errors": int(a["errors"]),
            "skipped": int(a["skipped"]), "seconds": float(a["time"]), "at": a.get("timestamp"), "rows": rows}


# ── reports ──────────────────────────────────────────────────────────────────────────────────────────────────────
def last_change(repo: str, ref: str, path: str) -> dict | None:
    out = git(repo, "log", ref, "-1", "--format=%h%x1f%aI%x1f%s", "--", path).strip()
    if not out:
        return None
    sha, date, subject = out.split("\x1f")
    return {"sha": sha, "date": date, "subject": subject}


def reports(repo: str, ref: str, tree: list[str]) -> list[dict]:
    want = []
    for path, kind, title in [
        ("PROGRESS.md", "digest", "Progress (generated by tta progress)"),
        ("site/index.html", "landing page", "The landing page"),
        ("site/proposals/index.html", "proposal round", "Five ways to show what the metrics mean"),
        ("site/progress.svg", "chart", "Progress chart"),
        ("site/views/lineage.svg", "chart", "Lineage view"),
        ("site/views/gates.svg", "chart", "Gates view"),
        ("site/views/specialists.svg", "chart", "Specialists view"),
    ]:
        if path in tree:
            want.append({"path": path, "kind": kind, "title": title})
    for path in tree:
        if path.startswith("reports/media/") and path.endswith(".html"):
            want.append({"path": path, "kind": "report", "title": os.path.basename(path)})
        if path.startswith("docs/peps/") and path.endswith(".md"):
            want.append({"path": path, "kind": "decision record", "title": os.path.basename(path)})
    studies = sorted({p.split("/")[1] for p in tree if p.startswith("ablations/") and p.count("/") >= 2})
    for s in studies:
        if f"ablations/{s}.md" in tree:  # the study file (changelog format) is the report; its folder is the code
            want.append({"path": f"ablations/{s}.md", "kind": "ablation study", "title": f"Ablation study {s}"})
        else:
            want.append({"path": f"ablations/{s}/", "kind": "ablation study", "title": f"Ablation study {s}"})
    for w in want:
        w["last"] = last_change(repo, ref, w["path"])
    return want


# ── ideas ────────────────────────────────────────────────────────────────────────────────────────────────────────
def ideas(repo: str, ref: str) -> dict:
    sys.path.insert(0, IDEAS_LANE)
    import ideas_parse  # the idea-queue lane's lossless parser, read-only

    text = show(repo, ref, "ideas.md") or ""
    doc = ideas_parse.parse(text)
    items = [{"lane": i.lane, "section": i.section, "open": not i.checked, "title": i.title, "text": i.text,
              "line": i.line_no, "solutions": i.solution_ids()} for i in doc.ideas]
    history = []
    for line in git(repo, "log", ref, "--format=%h%x1f%aI", "--", "ideas.md").splitlines()[::-1]:
        sha, date = line.split("\x1f")
        d = ideas_parse.parse(show(repo, sha, "ideas.md") or "")
        history.append({"sha": sha, "date": date,
                        "open_agent": sum(1 for i in d.ideas if not i.checked and i.lane == "agent"),
                        "open_human": sum(1 for i in d.ideas if not i.checked and i.lane == "human")})
    return {"items": items, "history": history, "parser": "proposals-ideas/_shared/ideas_parse.py"}


def quotes(repo: str, ref: str) -> list[dict]:
    """The dated words of Zach's the repo already quotes, at the lines quotes.json names (the line read here, verbatim)."""
    declared = json.load(open(os.path.join(HERE, "quotes.json"), encoding="utf-8"))["items"]
    out = []
    for q in declared:
        lines = (show(repo, ref, q["path"]) or "").splitlines()
        text = lines[q["line"] - 1].strip() if 0 < q["line"] <= len(lines) else None
        intro = None
        if text:
            probe = text[:60].strip()
            hits = git(repo, "log", ref, f"-S{probe}", "--format=%h", "--reverse", "--", q["path"]).split()
            intro = hits[0] if hits else None
        out.append({**q, "text": text, "found": bool(text and "Zach" in text), "introduced_in": intro})
    return out


def test_citations(repo: str, ref: str, tree: list[str]) -> dict[str, list[int]]:
    """Which OBJECTIVES.md sections each test file already cites in its own text ("OBJECTIVES §1", "OBJECTIVES section 4",
    "objectives_section_2"): the link a git-only proposal can read with no new file."""
    cite = re.compile(r"OBJECTIVES(?:\.md)?\s*(?:§|section\s*)(\d)|objectives_section_(\d)", re.IGNORECASE)
    out = {}
    for path in tree:
        if path.startswith("tests/test_") and path.endswith(".py"):
            found = sorted({int(a or b) for a, b in cite.findall(show(repo, ref, path) or "")})
            out[path] = found
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--junit", required=True, help="pytest junit xml of a run on a clean checkout of --ref")
    ap.add_argument("--junit-at", default=None, help="when that run started (ISO)")
    ap.add_argument("--lane-junit", default=None, help="optional: a run on the dirty working tree (a lane run)")
    ap.add_argument("--lane-head", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "_data", "box.json"))
    a = ap.parse_args()
    repo, ref = a.repo, git(a.repo, "rev-parse", a.ref).strip()

    tree = git(repo, "ls-tree", "-r", "--name-only", ref).splitlines()
    sol_ids = sorted({p.split("/")[1] for p in tree if p.startswith("solutions/") and p.endswith("/meta.json")})
    adds = added_in(repo, ref)
    sols = []
    for sid in sol_ids:
        meta = show_json(repo, ref, f"solutions/{sid}/meta.json") or {}
        card = show_json(repo, ref, f"solutions/{sid}/scorecard.json")
        hold = show_json(repo, ref, f"solutions/{sid}/scorecard_holdout.json")
        keep = lambda c: None if not c else {k: c.get(k) for k in ("objective", "admissible", "gate_pass_rate", "failed_gates", "evaluated")} | {
            "energy_j": (c.get("diagnostics") or {}).get("energy_j"),
            "saturation_share_pct": (c.get("diagnostics") or {}).get("saturation_share_pct"),
            "repo_commit": (c.get("code") or {}).get("repo_commit")}
        sols.append({"id": sid, "parent": meta.get("parent"), "change": meta.get("change"),
                     "proposed_by": meta.get("proposed_by"), "created": meta.get("created"), "tags": meta.get("tags") or [],
                     "added_in": adds.get(sid), "dev": keep(card), "holdout": keep(hold)})

    ledger = []
    for line in (show(repo, ref, "ledger.jsonl") or "").splitlines():
        if line.strip():
            r = json.loads(line)
            ledger.append({k: r.get(k) for k in ("t", "solution", "parent", "split", "ruler", "objective", "admissible",
                                                 "gate_pass_rate", "repo_commit", "proposed_by", "change")})

    dirty = [l for l in git(repo, "status", "--porcelain").splitlines() if l.strip()]
    head_now = git(repo, "rev-parse", "HEAD").strip()
    obj = objectives(show(repo, ref, "OBJECTIVES.md") or "")
    run = junit(a.junit)
    run.update({"sha": ref[:7], "clean": True, "where": "a clean `git archive` of the ref (siblings ../robot_msgs and ../robot_controllers as in pyproject)",
                "command": "uv run --all-extras pytest -q", "started": a.junit_at})
    lane = None
    if a.lane_junit:
        lane = junit(a.lane_junit)
        lane.pop("rows")
        lane.update({"sha": (a.lane_head or "")[:7], "clean": False, "where": "the working tree (uncommitted changes)"})

    readme = show(repo, ref, "README.md") or ""
    lead = next((p.strip() for p in readme.split("\n\n")[1:] if p.strip() and not p.startswith(("!", "|", "```", "#"))), "")
    box = {
        "schema": "blackbox-facts/1",
        "name": (readme.splitlines()[0].lstrip("# ").strip() if readme else os.path.basename(repo)),
        "repo": os.path.basename(repo),
        "url": ((show_json(repo, ref, "status.json") or {}).get("links") or {}).get("repo"),
        "ref": ref, "ref_short": ref[:7], "ref_date": git(repo, "log", "-1", "--format=%aI", ref).strip(),
        "head_now": head_now[:7], "uncommitted_not_read": len(dirty),
        "read_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "lead": lead,
        "objectives": obj,
        "status": show_json(repo, ref, "status.json"),
        "solutions": sols, "ledger": ledger,
        "ideas": ideas(repo, ref),
        "commits": commits(repo, ref),
        "tests": run, "lane_tests": lane,
        "reports": reports(repo, ref, tree),
        "peps": [p for p in tree if p.startswith("docs/peps/")],
        "quotes": quotes(repo, ref),
        "test_citations": test_citations(repo, ref, tree),
        "tags": git(repo, "tag", "--merged", ref).split(),
        "tree_has": {k: any(p == k or p.startswith(k + "/") for p in tree)
                     for k in ("feedback", "agents", "audits", "activity.jsonl", "reports/index.md", "specs", "SPEC.md", ".vibetrack")},
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(box, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {a.out}: {len(sols)} solutions, {len(ledger)} ledger rows, {len(box['commits'])} commits, "
          f"{run['tests']} tests ({run['failures'] + run['errors']} failing) at {ref[:7]}")


if __name__ == "__main__":
    main()
