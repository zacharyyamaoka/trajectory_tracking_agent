"""The `spec` slice (viewer/CONTRACT.md §3.2, §16.1): requirement rows mapped to tests, and the counts bb-nav shows.

Where the rows come from, first that exists at the ref:
1. **`specs/*.md`** in the box (Zach, 2026-11-24: spec and feedback come from markdown folders): one row per file, its
   front matter as fields, its body as `description` (plain text; TODO: data-ui's markdown rows and side panel, lane MD,
   render it once data-ui is re-vendored), tests mapped by its `tests:` patterns.
2. **A spec map** (`blackbox-spec-map/1`; trajectory_tracking_agent's is `proposals-vibetracks/_build/spec_map.json`),
   whose items quote OBJECTIVES.md: matched to tests by `proposals-vibetracks/_build/model.py`'s `spec()`, imported
   read-only (one matcher, one meaning), and each section's title read from OBJECTIVES.md at the ref.
Neither: the slice is absent.

Pass counts come only from a **junit XML** the fold is given (`--junit`, or `junit` in scenarios.json), read by
`proposals-vibetracks/_build/extract.py`'s `junit()`. The fold never runs a test. No junit: every count is `null` with
`why`, and each row's result is `not run`.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import re
import sys
from pathlib import Path

VIEWER = Path(__file__).resolve().parents[2]
VT = VIEWER.parent / "proposals-vibetracks" / "_build"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def front_matter(text: str) -> tuple[dict, str]:
    """`key: value` and `key:` + `- item` lists from a --- block; the rest is the body. (Simple YAML only, like the fold's
    feedback/ and audits/ reader.)"""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    meta, key = {}, None
    for line in m.group(1).splitlines():
        if re.match(r"^\s+-\s+", line) and key:
            meta[key] = (meta[key] if isinstance(meta.get(key), list) else []) + [line.split("-", 1)[1].strip().strip("'\"")]
        elif ":" in line and not line.startswith((" ", "#")):
            key, v = (s.strip() for s in line.split(":", 1))
            v = v.strip("'\"")
            meta[key] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()] if v.startswith("[") and v.endswith("]") else (v or [])
    return meta, text[m.end():]


def sections(body: str) -> tuple[str | None, str, dict]:
    """(first # heading, the text before the first ## section, {## heading lower-cased: text})."""
    title, lead, parts, cur = None, [], {}, None
    for line in body.splitlines():
        if line.startswith("# ") and title is None and cur is None:
            title = line[2:].strip()
        elif line.startswith("## "):
            cur = line[3:].strip().lower()
            parts[cur] = []
        elif cur is None:
            lead.append(line)
        else:
            parts[cur].append(line)
    return title, "\n".join(lead).strip(), {k: "\n".join(v).strip() for k, v in parts.items()}


def objective_sections(text: str) -> dict[int, str]:
    return {int(n): t.strip() for n, t in re.findall(r"^## (\d+)\.\s+(.+)$", text or "", re.M)}


def counts(rows: list[dict], tests: dict | None) -> dict:
    shalls = [r for r in rows if r["kind"] == "objective" and r["verb"] == "shall"]
    out = {"shall_active": len(shalls), "should": sum(r["verb"] == "should" for r in rows),
           "deferred": sum(r["verb"] == "deferred" for r in rows)}
    if tests is None:
        out.update({"shall_pass": None, "shall_fail": None, "shall_unverified": None, "pass_pct": None, "tests": None,
                    "tests_failed": None, "why": "no test run folded: give the fold a junit XML (--junit); it never runs a test"})
    else:
        sp = sum(r["result"] == "pass" for r in shalls)
        out.update({"shall_pass": sp, "shall_fail": sum(r["result"] == "fail" for r in shalls),
                    "shall_unverified": sum(r["result"] == "unverified" for r in shalls),
                    "pass_pct": round(100.0 * sp / len(shalls), 1) if shalls else None,
                    "tests": tests["tests"], "tests_failed": tests["failures"] + tests["errors"]})
    return out


def match(rows: list[dict], test_rows: list[dict] | None) -> list[str]:
    """Give each row its tests (first row whose pattern matches takes a test, the spec map's rule) and its result."""
    taken = {}
    for t in test_rows or []:
        for r in rows:
            if any(fnmatch.fnmatchcase(t["id"], p) or fnmatch.fnmatchcase(re.sub(r"\[.*\]$", "", t["id"]), p) for p in r["patterns"]):
                taken[t["id"]] = r["id"]
                break
    for r in rows:
        mine = [t for t in test_rows or [] if taken.get(t["id"]) == r["id"]]
        if test_rows is None:
            r.update({"tests": None, "pass": None, "fail": None, "failing": [],
                      "result": "deferred" if r["verb"] == "deferred" else "not run"})
            continue
        f = sum(t["status"] == "fail" for t in mine)
        r.update({"tests": len(mine), "pass": sum(t["status"] == "pass" for t in mine), "fail": f,
                  "failing": [t["id"] for t in mine if t["status"] == "fail"],
                  "result": "deferred" if r["verb"] == "deferred" else "unverified" if not mine else "fail" if f else "pass"})
    return [t["id"] for t in test_rows or [] if t["id"] not in taken]


def fold(facts: dict):
    tree = facts["tree"]
    junit_path = facts.get("junit")
    tests = None
    if junit_path:
        tests = _load("bb_vt_extract", VT / "extract.py").junit(str(VIEWER / junit_path))
    titles = objective_sections(tree.text("OBJECTIVES.md") or "") if "OBJECTIVES.md" in tree.fileset else {}
    # WHY: natural order, so O4.10 follows O4.9 (a plain sort put it before O4.2 on the Spec tab).
    files = sorted((p for p in tree.files if re.match(r"^specs/[^/]+\.md$", p)),
                   key=lambda p: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p)])
    rows = []
    if files:
        for path in files:
            meta, body = front_matter(tree.text(path) or "")
            title, lead, parts = sections(body)
            pats = meta.get("tests") or meta.get("proves") or []
            sec = meta.get("section")
            sec = int(sec) if isinstance(sec, str) and sec.isdigit() else sec
            # WHY: a box's specs/*.md may write the verb as `kind: shall|should|deferred` (trajectory_tracking_agent
            # 79ccd4a does); the spec map's kind is objective|contract, so read such a kind as the verb.
            kind, verb = (meta.get("kind") or "objective").lower(), (meta.get("verb") or "").lower()
            if kind in ("shall", "should", "deferred"):
                kind, verb = "objective", verb or kind
            statement = meta.get("statement") or lead or re.sub(r"^>\s?", "", parts.get("requirement", ""), flags=re.M).strip()
            rows.append({**{k: v for k, v in meta.items() if k not in ("tests", "proves")},
                         "id": meta.get("id") or Path(path).stem, "kind": kind,
                         "section": sec, "section_title": titles.get(sec) if isinstance(sec, int) else None,
                         "name": meta.get("name") or meta.get("title") or title or Path(path).stem,
                         "verb": verb or "shall", "statement": statement or None,
                         "description": body.strip() or None, "sections": parts, "source": path,
                         "patterns": pats if isinstance(pats, list) else [pats]})
        where = "specs/*.md"
        smap_name = None
    else:
        smap_name = facts.get("spec_map")
        if not smap_name:
            return None
        smap = json.loads((VIEWER / smap_name).read_text())
        for kind, items in (("objective", smap["items"]), ("contract", smap["contract"]["items"])):
            for it in items:
                sec = it.get("section")
                rows.append({"id": it["id"], "kind": kind, "section": sec, "section_title": titles.get(sec),
                             "name": it.get("name"), "verb": it.get("verb", "contract"), "statement": it.get("statement"),
                             "description": None, "source": it.get("source") or smap.get("source"),
                             "patterns": list(it.get("tests") or [])})
        where = smap_name
    unmapped = match(rows, tests["rows"] if tests else None)
    return {"from": where, "map": smap_name, "junit": junit_path,
            "junit_run": {k: tests[k] for k in ("tests", "failures", "errors", "skipped", "at")} if tests else None,
            "requirements": rows, "unmapped_tests": unmapped, **counts(rows, tests)}
