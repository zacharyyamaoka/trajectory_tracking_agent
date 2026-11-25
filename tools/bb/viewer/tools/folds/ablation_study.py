"""The `ablation_study` slice (viewer/CONTRACT.md §16.1): the box's newest ablation study, for bb-ablation.

- The study file (`ablations/<study>.md`, the changelog format) is parsed by the box's OWN parser, `ablations/study.py`
  `parse_changelog`, loaded from the same ref (WHY: one parser, one meaning; the box owns its format).
- The per-view analysis (leave-one-out and add-one-in factors, pairs, the path, fronts, the lattice and its surrogate)
  is `proposals-ablation/_shared/build.py`'s `build()`, and the overall importance (measured and estimated, each method
  labelled with its basis) is `proposals-ablation-page/_build/build.py`'s `overall()` and `rows()`: both imported
  read-only, never copied, run over the ref's ledger.jsonl, ideas.md and solutions/*/meta.json written to a temporary
  folder (read through the fold's Tree, so `source.read` lists them; never a solution's code).

Returns None when the box has no study file at the ref (the component's empty state).
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import types
from pathlib import Path

BB_REPO = Path(__file__).resolve().parents[3]
PAGE_BUILD = BB_REPO / "proposals-ablation-page" / "_build" / "build.py"
VIEW_BUILD_DIR = BB_REPO / "proposals-ablation" / "_shared"
PARSER = "ablations/study.py"


def _box_parser(tree, facts):
    """The box's own study.py at the ref, as a module (its REPO constant is never used by parse_changelog). WHY recorded in
    source.ran, not source.read: it is the box's tool the fold runs (like costs.py), and `read` lists data only, never
    a .py (tests/boundary.test.mjs)."""
    mod = types.ModuleType("box_study")
    mod.__file__ = f"/{PARSER}"
    exec(compile(tree.git("show", f"{tree.sha}:{PARSER}"), PARSER, "exec"), mod.__dict__)
    facts.setdefault("ran", []).append(f"{PARSER} parse_changelog (the box's own parser, at {tree.sha[:7]})")
    return mod


def _page_build():
    """proposals-ablation-page/_build/build.py, imported read-only; it imports proposals-ablation/_shared/build.py."""
    saved_path, saved = list(sys.path), {k: sys.modules.get(k) for k in ("build", "formats")}
    try:
        for k in saved:
            sys.modules.pop(k, None)
        spec = importlib.util.spec_from_file_location("bb_ablation_page_build", PAGE_BUILD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = saved_path
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def fold(facts: dict):
    tree, state = facts["tree"], facts["state"]
    if facts.get("ledger") is None or PARSER not in tree.fileset:
        return None
    studies = []
    for path in tree.files:
        if re.match(r"^ablations/[^/]+\.md$", path):
            text = tree.text(path) or ""
            if re.match(r"---\n(?:.*\n)*?study:", text):
                studies.append(((tree.last_change(path) or {}).get("date") or "", path, text))
    if not studies:
        return None
    _, file, text = max(studies)
    box = _box_parser(tree, facts)
    study = box.parse_changelog(text)
    page = _page_build()
    with tempfile.TemporaryDirectory(prefix="bb-ablation-") as tmp:
        repo = Path(tmp) / state["about"]["repo"]  # build() records repo.name: the box's, never the temp folder's
        (repo / "solutions").mkdir(parents=True)
        (repo / "ledger.jsonl").write_text(tree.text("ledger.jsonl") or "")
        if "ideas.md" in tree.fileset:
            (repo / "ideas.md").write_text(tree.text("ideas.md"))
        for p in tree.files:
            if re.match(r"^solutions/[^/]+/meta\.json$", p):
                (repo / p).parent.mkdir(parents=True, exist_ok=True)
                (repo / p).write_text(tree.text(p))
        data = page.view_build.build(study, repo, "changelog")
    # the page build reads gate_pass_rate from each scorecard and checks it equals the ledger's; the ledger's is the fold's
    dev = {r.get("solution"): r for r in facts["ledger"] if r.get("split") == "dev"}
    for v in data["variants"]:
        if v["solution"] in dev:
            v["gate_pass_rate"] = dev[v["solution"]].get("gate_pass_rate")
    order = [c["key"] for c in study["components"]]
    names = {c["key"]: c["name"] for c in study["components"]}
    overall = page.overall(data, study)
    overall["methods"] = [{"key": k, "name": n, "basis": b, "line": line, "cite": c} for k, n, b, line, c in page.METHODS]
    overall["refs"] = {k: {"text": t, "url": u} for k, (t, u) in page.REFS.items()}
    rows = page.rows(data, order, names)
    site = (state.get("about") or {}).get("url")
    for r in rows:  # the solution's folder at the folded commit, not main (a page reads the ref it was folded from)
        r["link"] = f"{site}/tree/{tree.sha[:7]}/solutions/{r['solution']}/" if site else None
    data.pop("study_md", None)
    return {"file": file, "parser": f"{PARSER} parse_changelog (the box's own, at {tree.sha[:7]})",
            "analysis": "proposals-ablation/_shared/build.py build() + proposals-ablation-page/_build/build.py overall(), rows()",
            **data, "overall": overall, "rows": rows,
            "links": {"solution": f"{site}/tree/{tree.sha[:7]}/solutions/" if site else None,
                      "ideas": f"{site}/blob/{tree.sha[:7]}/ideas.md#L" if site else None,
                      "study": f"{site}/blob/{tree.sha[:7]}/{file}" if site else None}}
