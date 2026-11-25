"""The `ideas` slice with the Lens board's fields (viewer/CONTRACT.md §16.1; PICKS.md "Idea queue" = proposals-ideas-v2
01 Lens board, + 02's Agent / Zach split, + 03's gate state).

    def fold(facts) -> list | None      (tools/fold_state.py runs it for every scenario: CONTRACT §3.3)

One row per idea: S0's base row (`facts["state"]["ideas"]`, every field unchanged) plus the Lens board's fields, worked
out by the ideas lanes' own code, imported read-only and never copied (one rule, one meaning; the way fold_state.py
imports proposals-ideas/_shared/ideas_parse.py):

    proposals-ideas/_shared/ideas_model.py        ideas.md + its git history + ledger.jsonl + meta.json: each idea's
                                                  I-NNN, status, solutions, bet, the commits that queued and crossed it off
    proposals-ideas-v2/_shared/roadmap.py         the backfill (each idea's rung and Needs: edge, with how and why) and the
                                                  ladder, read from OBJECTIVES.md (rungs_from_text)
    proposals-ideas-v2/01-lens-board/format.py    migrate (the backfill as '- Rung:' / '- Needs:' sub-bullets, each
                                                  "· inferred by lane I2 from …") and read (what that markdown says)
    proposals-ideas-v2/_shared/common.py          rows(): board, outcome, order, horizon, unlocks, waits_on, the links

What it reads: the box at the ref only, every file through facts["tree"] (`git show <ref>:<path>`, listed in
state.source.read): OBJECTIVES.md, ideas.md and its committed versions, status.json, ledger.jsonl, solutions/*/meta.json.
Never a solution's code. The lanes' modules read a checkout; `_at_ref` points their file and git reads at the ref for
the length of one call (WHY: the same code then folds any commit, and a peer's in-flight files are never read).

Inferred stays inferred (PICKS.md: "define what edges mean and who owns them; never invent one"): ideas.md has no
'- Rung:' or '- Needs:' line at any scenario's ref yet, so the fold migrates a copy in memory (never written to the
box), reads it back, and every value it placed says so (rung_set "inferred by lane I2 · from records|words", the rung
cell's basis and note, needs_how "inferred", needs_why). A line the box's own file already has is read as the file
writes it and never overridden. What nothing settles stays "Unassigned".

Field names that S0's base row already uses keep S0's meaning; the Lens board's own value goes beside it:
01 `id` (I-NNN) -> `iid`, 01 `lane` (Agent | Zach) -> `whose`, 01 `solutions` (Markdown links) -> `solutions_md`,
01 `expect` (the Expect: words while the idea was still open, the bet as placed) -> `expect_then`.
`needs`, `unlocks`, `built_on` and `answered_by` name ideas by `iid` (the `Needs: I-0xx` grammar).
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import contextmanager
from pathlib import Path

BB = Path(__file__).resolve().parents[3]            # blackbox_agent/ (this file: viewer/tools/folds/)
V1 = BB / "proposals-ideas" / "_shared"
V2 = BB / "proposals-ideas-v2" / "_shared"
LENS = BB / "proposals-ideas-v2" / "01-lens-board"
ROOT = "/box-at-ref"                                # the repo path the lanes' modules are handed: never a real path


class Lane:
    """The ideas lanes' modules, each loaded once from its own file."""

    def __init__(self):
        # WHY put back after loading: the modules insert their folders at the front of sys.path and register plain names
        # ("roadmap"), which would shadow another fold's own `import common` / `import roadmap` later in the same run.
        # Every import they make is at load time, so nothing needs either once they are loaded.
        path, before = list(sys.path), {n: sys.modules.get(n) for n in ("ideas_history", "ideas_model", "roadmap")}
        try:
            sys.path[:0] = [str(V1), str(V2)]
            # under the plain names their siblings import them by (roadmap: `import ideas_model`; format: `import roadmap`)
            self.parse = _module("ideas_parse", V1 / "ideas_parse.py")
            self.hist = _module("ideas_history", V1 / "ideas_history.py")
            self.model = _module("ideas_model", V1 / "ideas_model.py")
            self.roadmap = _module("roadmap", V2 / "roadmap.py")
            # these two under their own names: nothing imports them, and "common" / "format" are names others use
            self.common = _module("bbfold_ideas_v2_common", V2 / "common.py")
            self.fmt = _module("bbfold_ideas_v2_lens_format", LENS / "format.py")
        finally:
            sys.path[:] = path
            for name, mod in before.items():
                if mod is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = mod


def _module(name: str, path: Path):
    have = sys.modules.get(name)
    if have is not None and Path(getattr(have, "__file__", "") or "").resolve() == path.resolve():
        return have
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_lane: Lane | None = None


def lane() -> Lane:
    global _lane
    if _lane is None:
        _lane = Lane()
    return _lane


class _TreeOs:
    """The part of `os` the lanes' modules use (path.join/exists/isfile/isdir, listdir, sep), over the box at the ref.
    A git tree has no empty folder, so a folder the ref lacks lists as empty (a fresh box has no solutions yet)."""

    sep = "/"

    def __init__(self, tree):
        self.t = tree
        self.path = self

    @staticmethod
    def join(*parts: str) -> str:
        return "/".join(str(p).rstrip("/") for p in parts if p != "")

    @staticmethod
    def rel(path: str) -> str:
        path = str(path)
        if path == ROOT:
            return ""
        if not path.startswith(ROOT + "/"):
            raise FileNotFoundError(f"outside the box at the ref: {path}")
        return path[len(ROOT) + 1:].rstrip("/")

    def isfile(self, path: str) -> bool:
        return self.rel(path) in self.t.fileset

    def isdir(self, path: str) -> bool:
        r = self.rel(path)
        return r == "" or any(f.startswith(r + "/") for f in self.t.files)

    def exists(self, path: str) -> bool:
        return self.isfile(path) or self.isdir(path)

    def listdir(self, path: str) -> list[str]:
        r = self.rel(path)
        pre = r + "/" if r else ""
        return sorted({f[len(pre):].split("/")[0] for f in self.t.files if f.startswith(pre)})


@contextmanager
def _at_ref(tree, m: Lane):
    """For one call: the lanes' modules read files through `tree` (recorded in source.read) and run git at its ref."""
    shim = _TreeOs(tree)

    def text(path: str) -> str:
        r = shim.rel(path)
        body = tree.text(r)
        if body is None:
            if r == "status.json":
                return "{}"   # WHY: a fresh box has none yet; ideas_model reads only member, kpi and links from it
            raise FileNotFoundError(r)
        return body

    def git(_repo: str, *args: str) -> str:
        args = list(args)
        if args and args[0] == "log":
            args.insert(1, tree.sha)          # the history up to the ref, never the checkout's HEAD
        elif args[:2] == ["rev-parse", "HEAD"]:
            args[1] = tree.sha
        return tree.git(*args)

    saved = [(m.model, "_text", m.model._text), (m.model, "os", m.model.os), (m.hist, "git", m.hist.git),
             (m.roadmap, "_text", m.roadmap._text), (m.roadmap, "os", m.roadmap.os)]
    m.model._text, m.model.os, m.hist.git = text, shim, git
    m.roadmap._text, m.roadmap.os = text, shim
    m.roadmap.open = lambda path, *a, **k: io.StringIO(text(path))   # roadmap._ledger_rulers opens ledger.jsonl
    try:
        yield ROOT
    finally:
        for mod, name, value in saved:
            setattr(mod, name, value)
        del m.roadmap.open


def _at_sha(value, url: str | None, sha: str):
    """01 links ideas.md#L<n> and solutions/<id> on `main`; a past ref's line numbers differ there, so link the ref."""
    if not url or not isinstance(value, str):
        return value
    return value.replace(f"{url}/blob/main/", f"{url}/blob/{sha}/").replace(f"{url}/tree/main/", f"{url}/tree/{sha}/")


def _link(cell, url, sha):
    if isinstance(cell, dict):
        return {**cell, "value": _at_sha(cell.get("value"), url, sha)}
    return _at_sha(cell, url, sha)


def fold(facts: dict) -> list | None:
    t, state = facts["tree"], facts["state"]
    base = state.get("ideas")
    if "ideas.md" not in t.fileset or base is None:
        return None
    m = lane()
    objectives = t.text("OBJECTIVES.md") or ""
    text = t.text("ideas.md")
    with _at_ref(t, m) as repo:
        data = m.model.build(repo)
        backfill = m.roadmap.backfill(repo, data)
    ids = m.common.ids_by_index(text, data)
    # what the box's own file already says (a written line, or an inferred one it committed): never overridden
    own = m.fmt.read(m.parse.stamp_ids(text, ids), objectives)["ideas"]
    for iid, rec in backfill["ideas"].items():
        if (own.get(iid) or {}).get("rung"):
            rec["rung"] = None
        if (own.get(iid) or {}).get("needs"):
            rec["needs"] = []
    migrated = m.fmt.migrate(text, ids, backfill)
    assert m.fmt.strip(migrated) == m.fmt.strip(text), "01's migration is not undone exactly on this ideas.md"
    read = m.fmt.read(migrated, objectives)
    ladder = read["rungs"]
    lanes = m.common.lane_order(ladder)
    state_of = {r["id"]: r.get("state") or None for r in ladder}
    rows = {r["line"]: r for r in m.common.rows(data, read["ideas"], ladder)}
    url, sha = (data.get("repo_url") or "").rstrip("/") or None, t.sha
    out = []
    for b in base:
        r = rows.get(b["line"])
        assert r is not None, f"ideas.md:{b['line']} has no Lens board row"
        rung_id = (read["ideas"].get(r["id"]) or {}).get("rung")
        out.append({
            **b,
            "iid": r["id"], "whose": r["lane"],
            "board": r["board"], "board_rank": r["board_rank"], "outcome": r["outcome"], "done": r["done"],
            "solutions_md": _link(r["solutions"], url, sha), "solution_ids": r["solution_ids"],
            "solution": _link(r["solution"], url, sha), "score": r["score"], "delta": r["delta"], "bet": r["bet"], "expect_then": r["expect"],
            "rung": r["rung"], "rung_set": r["rung_set"], "rung_says": r["rung_says"], "rung_why": r["rung_why"],
            "rung_state": state_of.get(rung_id) if rung_id else None, "ladder": lanes,
            "needs": r["needs"], "needs_how": r["needs_how"], "needs_label": r["needs_label"], "needs_why": r["needs_why"],
            "unlocks": r["unlocks"], "horizon": r["horizon"], "waits_on": r["waits_on"],
            "built_on": r["built_on"], "answered_by": r["answered_by"], "order": r["order"],
            "words": r["words"], "result": r["result"], "queued": r["queued"], "closed": r["closed"],
            "queued_t": r["queued_t"], "closed_t": r["closed_t"], "source": _at_sha(r["source"], url, sha),
        })
    return out
