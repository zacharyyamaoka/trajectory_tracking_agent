"""The `spec_history` slice (viewer/CONTRACT.md §16.8): every test's state at every commit of the box up to the ref, from a
directory of junit XMLs the fold is given, one per commit (`junit_dir` in scenarios.json, or --junit-dir). The fold never
runs a test: a commit with no XML in the directory is a commit where no suite ran ("-" for every test).

Zach, 2026-11-24 (PICKS.md, lane NG): the gate matrix nests "spec section → requirement → test file → test across 61
commits"; the matrix (data-ui's tracker, CONTRACT §56) reads rows the component expands from this slice. Lane G's rules
(proposals-gates/_build/fold.py, `spec()`), so its gates.js is this slice's oracle (tests/spec-history.test.mjs):

- every test that ever ran, in the order the newest run lists it, then the ones deleted before it (oldest commit first);
- a test belongs to the first requirement whose map pattern matches its id, or its id without the [parameter] (the spec
  map's rule, as tools/folds/spec.py's `match`); the requirements are this state's `spec` slice's, so the Spec tab and the
  history agree; a test no pattern matches is `unlinked`;
- a state per commit: P pass, F fail (a failure or an error), S skipped, - absent (no suite ran, or the test did not
  exist); the first line of a failure's message is kept, at most 160 characters;
- `added`: the box commit that first added each iteration's solutions/<id>/meta.json, so an iteration column can read
  the suite as it stood at that commit.

Shape: {junit_dir, commits: [{sha, date, subject, ran, tests, failed, skipped}], files: [path],
        tests: [[name, file index, requirement id, states]], failures: {"<test index>": {"<commit index>": line}},
        added: {solution id: commit index}}
"""

from __future__ import annotations

import fnmatch
import gzip
import re
import xml.etree.ElementTree as ET
from pathlib import Path

VIEWER = Path(__file__).resolve().parents[2]


def junit_states(raw: bytes) -> dict:
    """{test id: (state, message)} for one junit XML, lane G's reading (classname dots to a path + '.py' :: name)."""
    out = {}
    for case in ET.fromstring(raw).iter("testcase"):
        cls, name = case.get("classname", ""), case.get("name", "")
        tid = f"{cls.replace('.', '/') + '.py' if cls else ''}::{name}"
        state, msg = "P", None
        for child in case:
            if child.tag in ("failure", "error"):
                state = "F"
                msg = ((child.get("message") or "") + "\n" + (child.text or "")).strip()
                if child.tag == "error":
                    msg = "error: " + msg
            elif child.tag == "skipped":
                state = "S"
        out[tid] = (state, msg)
    return out


def read_xml(folder: Path, short: str) -> bytes | None:
    for name in (f"{short}.xml", f"{short}.xml.gz"):
        p = folder / name
        if p.exists():
            raw = p.read_bytes()
            return gzip.decompress(raw) if name.endswith(".gz") else raw
    return None


def first_line(msg: str | None) -> str | None:
    if not msg:
        return None
    line = next((x.strip() for x in msg.splitlines() if x.strip()), "")
    return line[:160] or None


def fold(facts: dict):
    junit_dir = facts.get("junit_dir")
    spec = (facts.get("state") or {}).get("spec")
    if not junit_dir or not spec or not spec.get("requirements"):
        return None
    t = facts["tree"]
    folder = VIEWER / junit_dir
    log = t.git("log", "--reverse", "--format=%H%x1f%cI%x1f%s", t.sha).splitlines()
    commits, per = [], []
    for line in log:
        sha, date, subject = line.split("\x1f", 2)
        raw = read_xml(folder, sha[:7])
        states = junit_states(raw) if raw is not None else None
        per.append(states)
        vals = [s for s, _ in states.values()] if states is not None else None
        commits.append({"sha": sha[:7], "date": date, "subject": subject, "ran": states is not None,
                        "tests": len(vals) if vals is not None else None, "failed": vals.count("F") if vals is not None else None,
                        "skipped": vals.count("S") if vals is not None else None})
    # every test ever: the newest run's, in its order, then the deleted ones as the history meets them (oldest first)
    newest = next((s for s in reversed(per) if s is not None), {})
    order, seen = list(newest), set(newest)
    for states in per:
        for tid in states or {}:
            if tid not in seen:
                seen.add(tid)
                order.append(tid)
    reqs = spec["requirements"]

    def owner(tid: str) -> str:
        base = re.sub(r"\[.*\]$", "", tid)
        for r in reqs:
            if any(fnmatch.fnmatchcase(tid, p) or fnmatch.fnmatchcase(base, p) for p in r.get("patterns") or []):
                return r["id"]
        return "unlinked"

    files, tests, failures = [], [], {}
    for k, tid in enumerate(order):
        file, _, name = tid.partition("::")
        if file not in files:
            files.append(file)
        hist = []
        for j, states in enumerate(per):
            st, msg = (states or {}).get(tid, ("-", None))
            hist.append(st)
            if st == "F" and first_line(msg):
                failures.setdefault(str(k), {})[str(j)] = first_line(msg)
        tests.append([name, files.index(file), owner(tid), "".join(hist)])
    # the box commit that first added each solution (fold_state.added_in's query), as a commit index
    idx = {c["sha"]: j for j, c in enumerate(commits)}
    added = {}
    out = t.git("log", t.sha, "--diff-filter=A", "--format=@%H", "--name-only", "--", "solutions/")
    cur = None
    for line in out.splitlines():
        if line.startswith("@"):
            cur = line[1:8]
        elif line.endswith("/meta.json") and cur and line.count("/") == 2 and cur in idx:
            added[line.split("/")[1]] = idx[cur]  # newest first: the last write is the oldest add
    return {"junit_dir": junit_dir, "commits": commits, "files": files, "tests": tests, "failures": failures,
            "added": dict(sorted(added.items(), key=lambda kv: (kv[1], kv[0])))}
