"""The honest backfill: what a box's own files say about each idea's rung, order and edges, with how and why.

    python3 roadmap.py <box repo>          # prints the backfill as JSON

Ideas carry no rung, order or dependency today. All five proposals store the same backfill in their own markdown
format; this module is the one place it is worked out, so the five differ in format and views, never in what they
claim. Stdlib only.

The three edges, and who owns them (Zach's rule: define what an edge means and who owns it; never invent one;
PICKS.md 2026-11-24: needs edges come only from an idea's own `Needs: I-0xx` line):

    needs        A cannot start until B is done. Only from A's `Needs:` line (written by Zach or the agent); the one
                 the migration writes here is read from A's own words "Needs … (see Suggestions for Zach)".
    built on     A's solution's `parent` in meta.json is a solution idea B made. Recorded (meta.json), a past fact:
                 drawn by the lineage zoom-in only, never as a needs edge of the roadmap.
    answered by  A's line names B's solution after the arrow (crossed off by B's run). Recorded (ideas.md).

A rung is a gate the ideas climb, never an idea (PICKS.md 2026-11-24): the ladder comes from the box's frozen ruler
file (OBJECTIVES.md), and each idea carries the rung it serves.

Every value written by the migration is "inferred by lane I2", of one of two kinds:

    records   read off the ledger, meta.json or the ideas.md arrow (data-ui basis `derived`, ~)
    words     read from the idea's own words (data-ui basis `claimed`, ": an agent's reading, not a record)

Anything neither can settle stays unassigned. Nothing here is typed in per idea: each rule below is generic and
says which file it read.
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V1_SHARED = os.path.join(os.path.dirname(os.path.dirname(HERE)), "proposals-ideas", "_shared")
sys.path.insert(0, V1_SHARED)

import ideas_model  # noqa: E402  (the earlier round's stdlib model: ideas.md + git + ledger + meta.json)

BY = "lane I2"


def _text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _split_top(text: str) -> list[str]:
    """Split a sentence list on commas outside brackets ("a (b, c), d" -> ["a (b, c)", "d"])."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return [re.sub(r"\.$", "", s).strip() for s in out if s.strip()]


def rungs(repo: str) -> list[dict]:
    path = os.path.join(repo, "OBJECTIVES.md")
    return rungs_from_text(_text(path) if os.path.exists(path) else "")


def rungs_from_text(text: str) -> list[dict]:
    """The ladder, read from a box's frozen ruler file (OBJECTIVES.md): the ruler in force, the ruler its 'Deferred to
    ruler vN' section names, and any deferred item that calls itself a separate stage. An explicit '## Rungs' numbered
    list ("1. Name: what it is") wins when a box writes one. None of the rung names is typed in here."""
    explicit = re.search(r"^## (?:\d+\.\s*)?Rungs\b[^\n]*\n+(.*?)(?=\n## |\Z)", text, re.M | re.S)
    if explicit:
        out = []
        for m in re.finditer(r"^(\d+)\.\s+([^:\n]+):\s*(.*)$", explicit.group(1), re.M):
            out.append({"id": m.group(1), "name": m.group(2).strip(), "short": m.group(2).strip().lower(),
                        "state": "", "source": "OBJECTIVES.md \u00a7 Rungs", "says": m.group(3).strip(), "items": []})
        if out:
            return out
    title = re.search(r"^#\s.*\((ruler (v\d+)[^)]*)\)", text, re.M)
    now = title.group(2) if title else "v1"
    out = [{"id": "1", "name": f"Ruler {now}", "short": now, "state": "current",
            "source": "OBJECTIVES.md title" if title else "assumed",
            "says": (title.group(1) if title else "the ruler in force") + ": the frozen ruler every solution is scored on today",
            "items": []}]
    deferred = re.search(r"^## \d+\. Deferred to ruler (v\d+)[^\n]*\n+(.*?)(?=\n## |\Z)", text, re.M | re.S)
    if deferred:
        nxt = deferred.group(1)
        items = _split_top(" ".join(deferred.group(2).split()))
        stage = [i for i in items if re.search(r"separate stage", i)]
        out.append({"id": "2", "name": f"Ruler {nxt}", "short": nxt, "state": "not started",
                    "source": f"OBJECTIVES.md § \"Deferred to ruler {nxt}\"",
                    "says": f"the next ruler: what OBJECTIVES.md defers to ruler {nxt}",
                    "items": [i[0].upper() + i[1:] for i in items if i not in stage]})
        for k, item in enumerate(stage, start=3):
            name = re.sub(r"\s*\(.*\)$", "", item)
            name = re.sub(r"^the\s+", "", name)
            out.append({"id": str(k), "name": name[0].upper() + name[1:], "short": name, "state": "not started",
                        "source": f"OBJECTIVES.md § \"Deferred to ruler {nxt}\"",
                        "says": item[0].upper() + item[1:], "items": []})
    return out


def _ledger_rulers(repo: str) -> dict[str, str]:
    out = {}
    with open(os.path.join(repo, "ledger.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                if row.get("split") == "dev" and row.get("ruler"):
                    out[row["solution"]] = row["ruler"]
    return out


def _shared_phrases(a: str, b: str) -> list[str]:
    """Backticked tokens and 3-word phrases two texts share (lower case), longest first."""
    ticks = set(re.findall(r"`([^`]+)`", a)) & set(re.findall(r"`([^`]+)`", b))
    words = lambda s: re.findall(r"[a-z][a-z.()_-]+", s.lower())
    wa, wb = words(a), words(b)
    grams = lambda w: {" ".join(w[i:i + 3]) for i in range(len(w) - 2)}
    common = grams(wa) & grams(wb)
    stop = {"the", "a", "of", "to", "and", "on", "in", "it", "is", "for", "from"}
    common = {g for g in common if sum(t not in stop for t in g.split()) >= 2}
    return sorted([f"`{t}`" for t in ticks] + sorted(common), key=len, reverse=True)


def backfill(repo: str, data: dict | None = None) -> dict:
    data = data or ideas_model.build(repo)
    ladder = rungs(repo)
    by_short = {r["short"]: r for r in ladder}
    ruler_of = _ledger_rulers(repo)
    sols = {s["id"]: s for s in data["solutions"]}
    ideas = [i for i in data["ideas"] if i["status"] != "removed"]
    idea_of_solution = {sid: s["idea"] for sid, s in sols.items() if s.get("idea")}
    order_commits = [r["sha"] for r in data["timeline"]]
    out: dict[str, dict] = {}

    for i in ideas:
        rec: dict = {"rung": None, "built_on": [], "needs": [], "answered_by": [], "closed_order": None}
        text = i["text"]
        own = i["solutions"]
        tried = own + i["answered_by"]
        # ---- rung -------------------------------------------------------------------------------------------
        rulers = sorted({ruler_of.get(s) for s in tried if ruler_of.get(s)})
        if tried and len(rulers) == 1 and rulers[0] in by_short:
            r = by_short[rulers[0]]
            rec["rung"] = {"value": r["id"], "how": "records",
                           "why": f"{'its solution' if own else 'the solution that answered it'} `{tried[0]}` was scored on ruler {rulers[0]} (ledger.jsonl \"ruler\")"}
        else:
            named = re.match(r"\s*~*Ruler (v\d+)\s*:", text)
            if named and named.group(1) in by_short:
                r = by_short[named.group(1)]
                rec["rung"] = {"value": r["id"], "how": "words", "why": f"its words start \"Ruler {named.group(1)}:\""}
            else:
                stage = next((r for r in ladder[2:] if r["short"].lower() in text.lower()), None)
                needs_zach = re.search(r"\bNeeds\b.*?\(see Suggestions", text)
                either = re.match(r"\s*Ruler or tooling\b", text)
                if stage:
                    rec["rung"] = {"value": stage["id"], "how": "words",
                                   "why": f"its words name \"{stage['short']}\" ({stage['source']}: \"{stage['says']}\")"}
                elif i["lane"] == "agent" and not i["checked"] and not needs_zach:
                    rec["rung"] = {"value": ladder[0]["id"], "how": "words",
                                   "why": f"an \"I'll try\" idea that asks for no ruler change runs on the frozen {ladder[0]['name'].lower()} ({ladder[0]['source']})"}
                elif needs_zach:
                    rec["rung_why_unassigned"] = "it needs a change from Zach's list first, which may be a ruler or only tooling"
                elif either:
                    rec["rung_why_unassigned"] = "its words say \"Ruler or tooling\": either a ruler v2 change or tooling on ruler v1"
                else:
                    rec["rung_why_unassigned"] = "nothing in its words or records names a ruler (tooling, not a rung)"
        # ---- built on: meta.json parent chain ---------------------------------------------------------------
        for sid in own:
            parent = sols[sid]["parent"]
            pidea = idea_of_solution.get(parent)
            if pidea and pidea != i["id"]:
                rec["built_on"].append({"to": pidea, "how": "records",
                                        "why": f"`{sid}`'s parent is `{parent}` (meta.json), which {pidea} made"})
        # ---- answered by: the arrow names another idea's solution --------------------------------------------
        for sid in ([] if own else i["answered_by"]):   # a named rival in a tried idea's result is a comparison
            other = idea_of_solution.get(sid)
            if other and other != i["id"] and other not in [e["to"] for e in rec["answered_by"]]:
                rec["answered_by"].append({"to": other, "how": "records",
                                           "why": f"its line names `{sid}` after the arrow; {other} made it"})
        # ---- needs: an open idea's own "Needs … (see Suggestions for Zach)" ----------------------------------
        clause = re.search(r"\bNeeds\b(.*?\(see Suggestions[^)]*\))", text)
        if clause and not i["checked"]:
            cands = []
            for h in ideas:
                if h["lane"] == "human" and not h["checked"]:
                    shared = _shared_phrases(clause.group(1), h["text"])
                    if shared:
                        cands.append((len(shared), h["id"], shared))
            cands.sort(reverse=True)
            if cands and (len(cands) == 1 or cands[0][0] > cands[1][0]):
                n, hid, shared = cands[0]
                rec["needs"].append({"to": hid, "how": "words",
                                     "why": f"its words say \"Needs{clause.group(1)}\"; {hid} is the suggestion sharing "
                                            + ", ".join(f"\"{s}\"" for s in shared[:2])})
        # ---- order: the commit that crossed it off, in history order ----------------------------------------
        if i["checked"] and i["closed"] in order_commits:
            rec["closed_order"] = order_commits.index(i["closed"])
        out[i["id"]] = rec

    # closed order as a rank 1..n among closed ideas (ties keep file order)
    closed = sorted([k for k, v in out.items() if v["closed_order"] is not None],
                    key=lambda k: (out[k]["closed_order"], [i["id"] for i in ideas].index(k)))
    for n, k in enumerate(closed, start=1):
        out[k]["closed_rank"] = n
    counts = {
        "rung": {"records": sum(1 for v in out.values() if v["rung"] and v["rung"]["how"] == "records"),
                 "words": sum(1 for v in out.values() if v["rung"] and v["rung"]["how"] == "words"),
                 "unassigned": sum(1 for v in out.values() if not v["rung"])},
        "built_on": sum(len(v["built_on"]) for v in out.values()),
        "needs": sum(len(v["needs"]) for v in out.values()),
        "answered_by": sum(len(v["answered_by"]) for v in out.values()),
        "ideas": len(out),
    }
    return {"by": BY, "rungs": ladder, "ideas": out, "counts": counts}


if __name__ == "__main__":
    print(json.dumps(backfill(sys.argv[1]), ensure_ascii=False, indent=1))
