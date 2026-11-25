"""ideas.md + ledger.jsonl + solutions/*/meta.json (+ git history) -> ideas.json, the one input of every queue view.

Generic black-box UI: it reads the queue, the ledger's metrics out and meta.json's provenance, never a solution's
code (Zach, 2026-11-24: "the blackbox viz is not related to the solution, only to the metrics out"). Stdlib only.

    python3 ideas_model.py <box repo> <out.json>

Every number in the output comes from those files; nothing is typed in. Paths under the user's home are never
written (the page is public).

Study runs (a meta.json tagged "ablation", or carrying an "ablation" block) come from a study file in ablations/,
not from an idea: they are kept out of the idea <-> solution links, the population the views chart and every queue
statistic, and reported once per study as "ablation study: N runs" with a link to its file.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import defaultdict

import ideas_history as hist
from ideas_parse import Idea, parse

SCHEMA = "blackbox/ideas-1"
FLAT = 1e-6          # relative change below this is float noise (scores repeat bit for bit in a frozen ruler)


def _text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _json(path: str):
    return json.loads(_text(path))


def _rows(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def newest(rows: list[dict], split: str) -> dict[str, dict]:
    """The newest row per solution on a split (file order; the ledger is append-only)."""
    out: dict[str, dict] = {}
    for r in rows:
        if r.get("split") == split:
            out[r["solution"]] = r
    return out


def best_of(rows: list[dict], direction: str) -> tuple[str | None, float | None]:
    dev = [r for r in newest(rows, "dev").values() if r.get("admissible") and _finite(r.get("objective"))]
    if not dev:
        return None, None
    pick = (min if direction == "down" else max)(dev, key=lambda r: r["objective"])
    return pick["solution"], pick["objective"]


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _improves(new: float, old: float, direction: str) -> bool:
    return (new < old * (1 - FLAT)) if direction == "down" else (new > old * (1 + FLAT))


def _pct(new: float, old: float) -> float:
    return 100.0 * (new - old) / old


def _clean(value):
    """Drop anything that names a local path; the page is public."""
    if isinstance(value, str):
        return re.sub(r"/home/[^\s`'\")]+", "<local path>", value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def is_study_run(meta: dict) -> bool:
    """An ablation (or other study) run: made by a study's script to measure one part, never from an idea."""
    return "ablation" in (meta.get("tags") or []) or isinstance(meta.get("ablation"), dict)


def study_of(meta: dict) -> str:
    block = meta.get("ablation") if isinstance(meta.get("ablation"), dict) else {}
    tag = next((t.split(":", 1)[1] for t in meta.get("tags") or [] if t.startswith("study:")), None)
    return block.get("study") or tag or "ablation"


def study_file(repo: str, study: str) -> str | None:
    """The study's own write-up, repo-relative: ablations/<study>.md, its folder's README.md / <study>.md, any
    ablations/*.md naming it, else its folder. None when nothing is on disk yet."""
    base = os.path.join(repo, "ablations")
    for rel in (f"{study}.md", os.path.join(study, "README.md"), os.path.join(study, f"{study}.md")):
        if os.path.isfile(os.path.join(base, rel)):
            return "ablations/" + rel.replace(os.sep, "/")
    if os.path.isdir(base):
        named = sorted(f for f in os.listdir(base) if f.endswith(".md") and study in f)
        if named:
            return "ablations/" + named[0]
    if os.path.isdir(os.path.join(base, study)):
        return f"ablations/{study}/"
    return "ablations/" if os.path.isdir(base) else None


def build(repo: str) -> dict:
    box_status = _json(os.path.join(repo, "status.json"))
    kpi = box_status.get("kpi", {})
    direction = kpi.get("direction", "down")
    objective = {"name": re.sub(r"\s*\(.*\)$", "", kpi.get("name", "objective")), "unit": kpi.get("unit", ""),
                 "direction": direction}
    repo_url = (box_status.get("links") or {}).get("repo")

    # ---- the population: metrics out + provenance --------------------------------------------------------------
    ledger = _rows(_text(os.path.join(repo, "ledger.jsonl")))
    dev, holdout = newest(ledger, "dev"), newest(ledger, "holdout")
    metas = {}
    for sid in sorted(os.listdir(os.path.join(repo, "solutions"))):
        path = os.path.join(repo, "solutions", sid, "meta.json")
        if os.path.exists(path):
            metas[sid] = _json(path)
    study_metas = {sid: m for sid, m in metas.items() if is_study_run(m)}
    metas = {sid: m for sid, m in metas.items() if sid not in study_metas}
    added = hist.solutions_added(repo)
    commit_order = {c.sha: k for k, c in enumerate(hist.commits_touching(repo, "solutions"))}
    order = sorted(metas, key=lambda s: (commit_order.get(added.get(s, ""), 1e9), metas[s].get("created") or ""))
    known = set(metas)            # idea links resolve to the population only, never to a study run

    solutions: dict[str, dict] = {}
    best_so_far: float | None = None
    gen0 = [s for s in order if metas[s].get("parent") is None]
    for sid in order:
        m, row = metas[sid], dev.get(sid)
        obj = row.get("objective") if row else None
        adm = bool(row and row.get("admissible"))
        parent = m.get("parent")
        prow = dev.get(parent) if parent else None
        delta = _pct(obj, prow["objective"]) if (row and prow and _finite(obj) and _finite(prow.get("objective"))) else None
        new_best = False
        if adm and _finite(obj):
            if parent is None:
                new_best = None        # the seeded population: the baseline every idea starts from
            elif best_so_far is None or _improves(obj, best_so_far, direction):
                new_best = True
        solutions[sid] = {
            "id": sid, "parent": parent, "change": m.get("change"), "created": m.get("created"),
            "added_in": added.get(sid), "objective": obj, "admissible": adm,
            "holdout": holdout[sid]["objective"] if sid in holdout else None,
            "delta_pct": delta, "new_best": new_best,
            "proposed_by": (m.get("proposed_by") or {}).get("agent"), "model": (m.get("proposed_by") or {}).get("model"),
            "tags": m.get("tags") or [], "idea": m.get("idea"), "idea_how": "meta.json" if m.get("idea") else None,
            "seeded": parent is None, "ablation": False,
        }
        if adm and _finite(obj) and (best_so_far is None or _improves(obj, best_so_far, direction)):
            # The seeded population sets the baseline together; each later solution is judged in commit order.
            best_so_far = obj
    # generation depth
    for sid, s in solutions.items():
        d, p, seen = 0, s["parent"], {sid}
        while p in solutions and p not in seen:
            d, seen, p = d + 1, seen | {p}, solutions[p]["parent"]
        s["gen"] = d

    # ---- study runs: reported per study, never linked to an idea or counted in the queue's health ----------------
    study_runs, studies = [], {}
    for sid in sorted(study_metas, key=lambda x: (study_metas[x].get("created") or "", x)):
        m, row = study_metas[sid], dev.get(sid)
        block = m.get("ablation") if isinstance(m.get("ablation"), dict) else {}
        kind = block.get("kind") or next((t.split(":", 1)[1] for t in m.get("tags") or []
                                          if t.startswith("ablation:")), None)
        study = study_of(m)
        study_runs.append({
            "id": sid, "study": study, "kind": kind, "component": m.get("component"), "parent": m.get("parent"),
            "change": m.get("change"), "objective": row.get("objective") if row else None,
            "admissible": bool(row and row.get("admissible")), "added_in": added.get(sid), "ablation": True,
        })
        st = studies.setdefault(study, {"id": study, "runs": 0, "scored": 0, "kinds": {}, "file": study_file(repo, study),
                                        "bases": []})
        st["runs"] += 1
        if block.get("base") and block["base"] not in st["bases"]:
            st["bases"].append(block["base"])
        st["scored"] += 1 if row else 0
        if kind:
            st["kinds"][kind] = st["kinds"].get(kind, 0) + 1

    # ---- the queue, now and through every committed version ----------------------------------------------------
    versions = hist.versions(repo)
    tracks = hist.follow(versions)
    ids = hist.assign_ids(tracks)
    today = parse(_text(os.path.join(repo, "ideas.md")))
    sha_t = {c.sha: c for c, _ in versions}

    # solution -> its origin idea: meta.json first, then the idea crossed off in the commit that added the
    # solution and naming it, then the idea that names it first.
    origin: dict[str, tuple[str, str]] = {}
    for sid, s in solutions.items():
        if s["idea"]:
            origin[sid] = (s["idea"], "meta.json")
    for t in tracks:
        for sha, event in t.events:
            if event not in ("closed", "logged"):
                continue
            named = t.versions[sha].solution_ids(known)
            for sid in named:
                if sid not in origin and solutions[sid]["added_in"] == sha:
                    origin[sid] = (ids[t.key], "same commit")
    for t in tracks:
        named = t.last().solution_ids(known)
        if named and named[0] not in origin and t.last().checked:
            origin[named[0]] = (ids[t.key], "named first")
    for sid, (iid, how) in origin.items():
        solutions[sid]["idea"], solutions[sid]["idea_how"] = iid, how

    ideas = []
    by_index = {}
    for t in tracks:
        if t.removed_at is None:
            by_index[t.last().index] = t
    for t in sorted(tracks, key=lambda t: (t.removed_at is not None, t.last().index if t.removed_at is None else t.key)):
        iid = ids[t.key]
        cur: Idea = t.last()
        named = cur.solution_ids(known)
        implemented = [s for s in named if origin.get(s, ("",))[0] == iid]
        implemented += [s for s, (i, _) in origin.items() if i == iid and s not in implemented]
        answered = [s for s in named if s not in implemented]
        trying = [s for s, sol in solutions.items() if sol["idea"] == iid and sol["idea_how"] == "meta.json"]
        pre = t.last_open()
        expect_from = pre if (pre and pre.expect_text) else cur
        lane = cur.lane
        if t.removed_at:
            status = "removed"
        elif lane == "human":
            status = "decided" if cur.checked else "needs-human"
        elif not cur.checked:
            status = "trying" if trying else "open"
        elif implemented:
            s0 = solutions[implemented[0]]
            if s0["new_best"]:
                status = "new-best"
            elif s0["delta_pct"] is None:
                status = "tried"
            elif abs(s0["delta_pct"]) < 100 * FLAT:
                status = "flat"
            elif (s0["delta_pct"] < 0) == (direction == "down"):
                status = "beat-parent"
            else:
                status = "worse"
        elif answered:
            status = "answered"
        else:
            status = "closed-unlinked"
        primary = implemented[0] if implemented else None
        lo, hi = expect_from.expect_lo, expect_from.expect_hi
        if lo is not None and not expect_from.expect_signed:
            # An unsigned "~10-20 %" in a queue means "better by": signed toward the objective's direction.
            lo, hi = (-lo, -hi) if direction == "down" else (lo, hi)
        ideas.append({
            "id": iid, "id_written": bool(t.block_id), "lane": lane, "section": cur.section, "status": status,
            "title": cur.title, "text": cur.before_arrow if cur.checked else cur.text, "result": cur.result,
            "line": cur.line_no if not t.removed_at else None, "checked": cur.checked,
            "solutions": implemented, "answered_by": answered, "mentions": [m for m in cur.mentioned if m in known],
            "primary": primary,
            "from_parent": cur.from_parent,
            "expect": {"text": expect_from.expect_text, "lo": lo, "hi": hi, "conf": expect_from.confidence,
                       "pre_registered": bool(pre and pre.expect_text and pre is expect_from)},
            "actual_pct": solutions[primary]["delta_pct"] if primary else None,
            "queued": t.events[0][0] if t.events[0][1] == "queued" else None,
            "born": t.born, "born_event": t.events[0][1],
            "closed": t.event_sha("closed") or (t.born if t.events[0][1] == "logged" else None),
            "removed": t.removed_at,
            "history": [{"sha": sha, "event": e} for sha, e in t.events],
        })

    # ---- one row per commit that touched the queue or the population -------------------------------------------
    timeline = []
    version_at = {c.sha: doc for c, doc in versions}
    events_at: dict[str, list] = defaultdict(list)
    for t in tracks:
        for sha, e in t.events:
            events_at[sha].append({"idea": ids[t.key], "event": e})
    # The queue as written at each version: [id, crossed off, lane, its title then (only when it differs today)]
    current_title = {ids[t.key]: t.last().title for t in tracks}
    queue_at: dict[str, list] = {}
    for c, vdoc in versions:
        rows_ = []
        for idea in vdoc.ideas:
            t = next(t for t in tracks if t.versions.get(c.sha) is idea)
            iid = ids[t.key]
            rows_.append([iid, int(idea.checked), idea.lane[0], idea.title if idea.title != current_title[iid] else None])
        queue_at[c.sha] = rows_
    doc = None
    version_sha = None
    for c in hist.commits_touching(repo, "ideas.md", "ledger.jsonl", "solutions"):
        doc = version_at.get(c.sha, doc)
        version_sha = c.sha if c.sha in version_at else version_sha
        try:
            rows = _rows(hist.git(repo, "show", f"{c.sha}:ledger.jsonl"))
        except Exception:
            rows = []
        bsid, bobj = best_of([r for r in rows if r.get("solution") not in study_metas], direction)
        open_agent = sum(1 for i in (doc.ideas if doc else []) if i.lane == "agent" and not i.checked)
        open_human = sum(1 for i in (doc.ideas if doc else []) if i.lane == "human" and not i.checked)
        closed = sum(1 for i in (doc.ideas if doc else []) if i.checked)
        timeline.append({
            "sha": c.sha, "t": c.t, "subject": c.subject, "touches_ideas": c.sha in version_at, "queue_version": version_sha,
            "open_agent": open_agent, "open_human": open_human, "closed": closed,
            "best": bobj, "best_solution": bsid, "ledger_rows": len(rows),
            "events": events_at.get(c.sha, []),
            "added": sorted([s for s, sol in solutions.items() if sol["added_in"] == c.sha],
                            key=lambda s: order.index(s)),
            "study_runs_added": sum(1 for r in study_runs if r["added_in"] == c.sha),
        })

    # ---- queue health: all counted, never estimated except where labelled ---------------------------------------
    agent_closed = [i for i in ideas if i["lane"] == "agent" and i["checked"] and i["status"] != "removed"]
    own = [i for i in agent_closed if i["solutions"]]
    hits = [i for i in own if i["status"] == "new-best"]
    beat = [i for i in own if i["status"] in ("new-best", "beat-parent")]
    open_agent = [i for i in ideas if i["status"] in ("open", "trying")]
    open_human = [i for i in ideas if i["status"] == "needs-human"]
    pre_reg = [i for i in agent_closed if i["queued"]]
    numeric = [i for i in ideas if i["expect"]["lo"] is not None and i["actual_pct"] is not None]
    last_solution = next((r for r in reversed(timeline) if r["added"]), None)
    last_queue_add = next((r for r in reversed(timeline) if any(e["event"] == "queued" for e in r["events"])), None)
    exp_commits = [r for r in timeline if r["added"]]
    oldest_open = min(open_agent, key=lambda i: [r["sha"] for r in timeline].index(i["born"]), default=None)
    best_sid, best_obj = best_of([r for r in ledger if r.get("solution") in solutions], direction)
    health = {
        "open_agent": len(open_agent), "open_human": len(open_human),
        "open_agent_with_number": sum(1 for i in open_agent if i["expect"]["lo"] is not None),
        "tried": len(agent_closed), "tried_own_solution": len(own), "answered_elsewhere": len(agent_closed) - len(own),
        "new_bests": len(hits), "beat_parent": len(beat),
        "hit_rate": len(hits) / len(own) if own else None,
        "tried_per_new_best": len(agent_closed) / len(hits) if hits else None,
        "pre_registered": len(pre_reg), "logged_after": len(agent_closed) - len(pre_reg),
        "predictions_with_number": len(numeric),
        "naive_expected_new_bests": (len(open_agent) * len(hits) / len(own)) if own else None,
        "last_solution_commit": last_solution["sha"] if last_solution else None,
        "last_queued_commit": last_queue_add["sha"] if last_queue_add else None,
        "experiment_commits": len(exp_commits),
        "commits_since_last_queued": (len(timeline) - 1 - timeline.index(last_queue_add)) if last_queue_add else None,
        "oldest_open": oldest_open["id"] if oldest_open else None,
        "oldest_open_commits": (len(timeline) - 1 - [r["sha"] for r in timeline].index(oldest_open["born"])) if oldest_open else None,
        "removed": sum(1 for i in ideas if i["status"] == "removed"),
        "best": best_obj, "best_solution": best_sid,
        "seeded": len(gen0),
    }

    head = hist.git(repo, "rev-parse", "HEAD").strip()
    return _clean({
        "schema": SCHEMA, "box": box_status.get("member"), "repo_url": repo_url, "head": head,
        "ideas_md_commit": versions[-1][0].sha if versions else None,
        "objective": objective, "ideas": ideas, "solutions": [solutions[s] for s in order],
        "timeline": timeline, "health": health, "queue_at": queue_at,
        "studies": list(studies.values()), "study_runs": study_runs,
        "commits": {c.sha: {"t": c.t, "subject": c.subject} for c in hist.commits_touching(repo, "ideas.md", "ledger.jsonl", "solutions")},
    })


if __name__ == "__main__":
    data = build(sys.argv[1])
    text = json.dumps(data, ensure_ascii=False, indent=1)
    assert "/home/" not in text, "a local path would be published"
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(text + "\n")
    h = data["health"]
    print(f"{len(data['ideas'])} ideas, {len(data['solutions'])} solutions, {len(data['timeline'])} commits; "
          f"open agent {h['open_agent']}, open human {h['open_human']}, tried {h['tried']}, new bests {h['new_bests']}")
