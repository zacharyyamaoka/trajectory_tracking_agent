"""What the five proposals share: the box's data, the idea rows every preset draws, the fuel-gauge header, the page.

Each proposal parses its OWN markdown format (its format.py) into one shape per idea,

    {"rung": "2" | None, "rung_how": "written" | "records" | "words" | None, "rung_why": str,
     "edges": [{"to": "I-005", "kind": "built on" | "needs" | "answered by" | "unlocks", "how": ..., "why": str}],
     "order": int | None}

and this module joins that with the metrics (ideas_model's ideas.json: the ledger, meta.json and git) into the rows
of one data-ui dataset. So what a page draws as rung, order and edges is what that proposal's markdown says, never
the backfill directly. Stdlib only; no solution code is read.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import roadmap  # noqa: E402

BOX = os.environ.get("BOX_REPO", os.path.expanduser("~/trajectory_tracking_agent"))
BASIS = {"written": "chosen", "records": "derived", "words": "claimed"}
HOW_WORDS = {"written": "written", "records": "inferred by lane I2 · from records", "words": "inferred by lane I2 · from words"}
BOARD = ["Up next", "Zach to decide", "Won", "No win", "Settled"]


def load(refresh: bool = False) -> tuple[dict, dict]:
    """ideas.json (the earlier round's model over ideas.md, git, the ledger and meta.json) and the backfill, cached in
    _shared/ so a page rebuild needs no box checkout; `refresh` re-reads the box."""
    ip, bp = os.path.join(HERE, "ideas.json"), os.path.join(HERE, "backfill.json")
    if refresh or not os.path.exists(ip):
        data = roadmap.ideas_model.build(BOX)
        text = json.dumps(data, ensure_ascii=False, indent=1)
        assert "/home/" not in text, "a local path would be published"
        open(ip, "w", encoding="utf-8").write(text + "\n")
        bf = roadmap.backfill(BOX, data)
        open(bp, "w", encoding="utf-8").write(json.dumps(bf, ensure_ascii=False, indent=1) + "\n")
    return json.load(open(ip, encoding="utf-8")), json.load(open(bp, encoding="utf-8"))


def ideas_md() -> str:
    """Today's ideas.md, verbatim, as committed in the box at the commit ideas.json was built from."""
    path = os.path.join(HERE, "fixtures", "ideas.md")
    return open(path, encoding="utf-8", newline="").read()


def objectives_md() -> str:
    return open(os.path.join(HERE, "fixtures", "OBJECTIVES.md"), encoding="utf-8", newline="").read()


# ---- formatting ------------------------------------------------------------------------------------------------

def mm(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.3f}" if v < 1 else f"{v:.3g}"


def bet_text(lo: float, hi: float) -> str:
    """A written bet as written: "−10…20 %", "−5 %", "±0 %"."""
    whole = lambda x: f"{abs(x):g}"
    if lo == hi:
        return "±0 %" if lo == 0 else f"{'−' if lo < 0 else '+'}{whole(lo)} %"
    return f"{'−' if lo < 0 else '+'}{whole(lo)}…{whole(hi)} %"


def pct(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) < 0.05:
        return "±0 %"
    return f"{v:+.1f} %".replace("-", "−")


def short(sha: str | None) -> str | None:
    return sha[:7] if sha else None


def iso(t) -> str | None:
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return str(t)


# ---- rows --------------------------------------------------------------------------------------------------------

def board_of(i: dict) -> str:
    s = i["status"]
    if s in ("open", "trying"):
        return "Up next"
    if s == "needs-human":
        return "Zach to decide"
    if s in ("new-best", "beat-parent"):
        return "Won"
    if s in ("worse", "flat", "tried"):
        return "No win"
    return "Settled"


OUTCOME = {"open": "open", "trying": "trying", "needs-human": "for Zach", "new-best": "new best", "beat-parent": "beat its parent",
           "flat": "no change", "worse": "worse", "tried": "tried", "answered": "answered by others", "decided": "decided",
           "closed-unlinked": "closed", "removed": "deleted"}


def solution_cell(data: dict, i: dict) -> tuple[str | None, list[str]]:
    """Markdown links to every solution that tried this idea (or answered it), each with its score and Δ."""
    sols = {s["id"]: s for s in data["solutions"]}
    url = (data.get("repo_url") or "").rstrip("/")
    unit = data["objective"]["unit"]
    parts, ids = [], []
    # WHY own solutions only when it has one: a rival named in a tried idea's result ("worse than `p5s-fric2-pass2`")
    # is a comparison, not a solution of this idea
    for sid in i["solutions"] + ([] if i["solutions"] else i["answered_by"]):
        s = sols.get(sid)
        if not s or sid in ids:
            continue
        ids.append(sid)
        link = f"[{sid}]({url}/tree/main/solutions/{sid})" if url else f"`{sid}`"
        star = " ★" if s.get("new_best") else ""
        prefix = "" if sid in i["solutions"] else "answered by "
        parts.append(f"{prefix}{link} {mm(s['objective'])} {unit} · {pct(s['delta_pct'])}{star}")
    return ("  \n".join(parts) if parts else None), ids


def horizon(rows_: list[dict]) -> dict[str, str]:
    """Now · Next · Later from Needs lines only (the Oct 3 lens board's buckets rule, graph.ts `buckets`): Done when
    crossed off; Ready now when every idea it needs is done; Next when each unmet need is itself ready; else Later.
    No estimates and no dates (Zach, Oct 3: waves need estimates)."""
    by = {r["id"]: r for r in rows_}
    done = {i for i, r in by.items() if r["done"]}
    unmet = {i: [n for n in r["needs"] if n in by and n not in done] for i, r in by.items()}
    out = {}
    for i in by:
        if i in done:
            out[i] = "Done"
        elif not unmet[i]:
            out[i] = "Ready now"
    for i in by:
        if i not in out:
            out[i] = "Next" if all(out.get(n) == "Ready now" for n in unmet[i]) else "Later"
    return out


def solution_link(data: dict, i: dict, ids: list[str]):
    """The first solution that tried (or answered) the idea as one link cell, for a table's one-click column; the
    record keeps all of them (`solutions`)."""
    if not ids:
        return {"value": None, "why": "not tried yet" if not i["checked"] else "no solution named"}
    sols = {s["id"]: s for s in data["solutions"]}
    s0 = sols[ids[0]]
    url = (data.get("repo_url") or "").rstrip("/")
    more = f" (+{len(ids) - 1} more)" if len(ids) > 1 else ""
    text = f"{ids[0]} · {mm(s0['objective'])} {data['objective']['unit']} · {pct(s0['delta_pct'])}{' ★' if s0.get('new_best') else ''}{more}"
    return {"value": f"{url}/tree/main/solutions/{ids[0]}" if url else ids[0], "text": text}


def rows(data: dict, fields: dict[str, dict], ladder: list[dict]) -> list[dict]:
    rung_name = {r["id"]: f"{r['id']} · {r['name']}" for r in ladder}
    rung_says = {r["id"]: r.get("says", "") for r in ladder}
    commits = data["commits"]
    url = (data.get("repo_url") or "").rstrip("/")
    sols = {s["id"]: s for s in data["solutions"]}
    idea_of = {sid: s["idea"] for sid, s in sols.items() if s.get("idea")}
    live = [i for i in data["ideas"] if i["status"] != "removed"]   # a deleted idea is counted in the header, not a row
    closed = sorted([i for i in live if i["checked"] and i["closed"]],
                    key=lambda i: (tl_index(data["timeline"], i["closed"]), i["line"]))
    order = {i["id"]: k for k, i in enumerate(closed, start=1)}
    needs_of = {i["id"]: [e["to"] for e in fields.get(i["id"], {}).get("needs", [])] for i in live}

    def depth(x: str, seen: tuple = ()) -> int:
        return 0 if x in seen else max([1 + depth(n, seen + (x,)) for n in needs_of.get(x, []) if n in needs_of] or [0])
    # WHY needs first: an open idea is placed after every open idea its Needs: line names (the only order an open idea
    # has besides the order it was written in); nothing else is invented
    for i in sorted([i for i in live if i["id"] not in order], key=lambda i: (depth(i["id"]), i["line"])):
        order[i["id"]] = len(order) + 1
    out = []
    for i in live:
        f = fields.get(i["id"], {})
        sol_md, sol_ids = solution_cell(data, i)
        rung, how = f.get("rung"), f.get("rung_how")
        if rung:
            rung_cell = {"value": rung_name.get(rung, rung), "basis": BASIS.get(how, "chosen"),
                         "note": f.get("rung_why") or HOW_WORDS.get(how, how)}
        else:
            rung_cell = {"value": "Unassigned", "note": "unassigned: " + (f.get("rung_why") or "no rung written")}
        needs = f.get("needs", [])
        primary = sols.get(i["primary"]) if i["primary"] else None
        expect = i["expect"]
        bet = None
        if expect["lo"] is not None:
            lo, hi = expect["lo"], expect["hi"]
            bet = bet_text(lo, hi)
        built_on = []
        for sid in i["solutions"]:
            p = sols[sid]["parent"] if sid in sols else None
            if p in idea_of and idea_of[p] != i["id"] and idea_of[p] not in built_on:
                built_on.append(idea_of[p])
        out.append({
            "id": i["id"], "file.name": i["id"], "title": i["title"],
            "lane": "Agent" if i["lane"] == "agent" else "Zach",
            "board": board_of(i), "board_rank": BOARD.index(board_of(i)) + 1, "outcome": OUTCOME.get(i["status"], i["status"]), "done": bool(i["checked"]),
            "solutions": sol_md if sol_md else {"value": None, "why": "not tried yet" if not i["checked"] else "no solution named"},
            "solution_ids": sol_ids,
            "solution": solution_link(data, i, sol_ids),
            "score": primary["objective"] if primary else None,
            "delta": round(primary["delta_pct"], 2) if primary and primary["delta_pct"] is not None else None,
            "bet": bet, "expect": expect["text"],
            "rung": rung_cell,
            "rung_set": HOW_WORDS.get(how, how or "written") if rung else "unassigned",
            "rung_says": rung_says.get(rung) if rung else "ideas with no rung written",
            "rung_why": f.get("rung_why"),
            "needs": [e["to"] for e in needs],
            "needs_how": ["written" if e["how"] == "written" else "inferred" for e in needs],
            "needs_label": ["needs" if e["how"] == "written" else "needs · inferred" for e in needs],
            "needs_why": "; ".join(f"{e['to']}: {e['why']}" for e in needs) or None,
            "built_on": built_on,
            "answered_by": [idea_of[s] for s in i["answered_by"] if s in idea_of and not i["solutions"]],
            "order": order[i["id"]],
            "words": i["text"], "result": i["result"] or None,
            "queued": short(i["queued"] or i["born"]), "closed": short(i["closed"]),
            "queued_t": iso(commits.get(i["queued"] or i["born"], {}).get("t")),
            "closed_t": iso(commits.get(i["closed"], {}).get("t")) if i["closed"] else None,
            "line": i["line"],
            "source": f"{url}/blob/main/ideas.md#L{i['line']}" if url and i["line"] else None,
        })
    by = {r["id"]: r for r in out}
    hz = horizon(out)
    for r in out:
        r["unlocks"] = [o["id"] for o in out if r["id"] in o["needs"]]
        r["horizon"] = hz[r["id"]]
        waits = [n for n in r["needs"] if n in by and not by[n]["done"] and by[n]["lane"] == "Zach"]
        r["waits_on"] = ("waits on Zach: " + ", ".join(waits)) if waits and not r["done"] else None
    return out


PROPERTIES = {
    "id": {"type": "text", "label": "Id", "width": 64},
    "file.name": {"type": "text", "label": "Note", "width": 70, "hidden": True},
    "title": {"type": "text", "label": "Idea", "width": 300},
    "lane": {"type": "text", "label": "Whose", "width": 70, "colors": {"Agent": 1, "Zach": 5}},
    "board": {"type": "text", "label": "Board", "width": 116,
              "colors": {"Up next": 1, "Zach to decide": 5, "Won": 3, "No win": 0, "Settled": 0}},
    "board_rank": {"type": "number", "label": "Board order", "hidden": True},
    "outcome": {"type": "text", "label": "Outcome", "width": 120},
    "done": {"type": "boolean", "label": "Crossed off", "width": 60},
    "solutions": {"type": "text", "label": "Solution(s)", "display": "markdown", "width": 300,
                  "note": "the solutions that tried it (the → in ideas.md, meta.json); each links to its folder"},
    "solution_ids": {"type": "list", "label": "Solution ids", "hidden": True},
    "solution": {"type": "text", "label": "Solution", "display": "link", "width": 260,
                 "note": "the solution that tried it, one click to its folder; the record lists every one"},
    "score": {"type": "number", "label": "Score", "unitText": "mm", "digits": 3, "better": "lower", "width": 80},
    "delta": {"type": "number", "label": "Δ vs parent", "unitText": "%", "decimals": 1, "better": "lower", "width": 90},
    "bet": {"type": "text", "label": "Bet", "width": 84, "note": "the % its Expect: named before the run"},
    "expect": {"type": "text", "label": "Expect", "width": 240},
    "rung": {"type": "text", "label": "Rung", "width": 140,
             "note": "the gate the idea serves; its mark says who set it: C written, ~ inferred from records, ” inferred from words"},
    "rung_set": {"type": "text", "label": "Rung set by", "width": 190,
                 "colors": {"written": 3, "inferred by lane I2 · from records": 1, "inferred by lane I2 · from words": 5, "unassigned": 0}},
    "rung_says": {"type": "text", "label": "The gate", "width": 260},
    "rung_why": {"type": "text", "label": "Rung, why", "width": 260},
    "needs": {"type": "list", "label": "Needs", "relation": True, "width": 90,
              "note": "only from the idea's own Needs: line: it cannot start until these are done"},
    "needs_how": {"type": "list", "label": "Needs set by", "width": 90},
    "needs_why": {"type": "text", "label": "Needs, why", "width": 300},
    "needs_label": {"type": "list", "label": "Edge", "hidden": True},
    "unlocks": {"type": "list", "label": "Unlocks", "relation": True, "width": 90, "derived": "the ideas whose Needs: line names this one"},
    "waits_on": {"type": "text", "label": "Blocker", "width": 150, "derived": "an open need owned by Zach"},
    "built_on": {"type": "list", "label": "Built on", "relation": True, "width": 90,
                 "note": "recorded: its solution's parent in meta.json was made by this idea (lineage, not a need)"},
    "answered_by": {"type": "list", "label": "Answered by", "relation": True, "width": 100},
    "order": {"type": "number", "label": "Order", "width": 60,
              "note": "implementation order: the order ideas were crossed off (git), then the open ones as written"},
    "horizon": {"type": "text", "label": "Now · Next · Later", "width": 110,
                "derived": "from Needs: lines only: Done, Ready now (needs met), Next (one step), Later",
                "colors": {"Done": 0, "Ready now": 3, "Next": 1, "Later": 5}},
    "words": {"type": "text", "label": "Words", "width": 420},
    "result": {"type": "text", "label": "Result", "width": 360},
    "queued": {"type": "text", "label": "Queued in", "width": 80},
    "closed": {"type": "text", "label": "Crossed off in", "width": 90},
    "queued_t": {"type": "date", "label": "Queued"},
    "closed_t": {"type": "date", "label": "Crossed off"},
    "line": {"type": "number", "label": "Line", "width": 50},
    "source": {"type": "text", "label": "In ideas.md", "width": 80},
}


def dataset(data: dict, fields: dict, ladder: list[dict], slug: str, extra_props: dict | None = None,
            extra_rows: dict | None = None) -> dict:
    rs = rows(data, fields, ladder)
    for r in rs:
        r.update((extra_rows or {}).get(r["id"], {}))
    props = dict(PROPERTIES)
    props.update(extra_props or {})
    return {"id": f"ideas-v2-{slug}", "title": f"{data['box']} ideas", "titleProperty": "title", "linkProperty": "source",
            "properties": props, "rows": rs}


# ---- the fuel gauge: one header above every preset ---------------------------------------------------------------

def fuel_cards(data: dict, fields: dict, ladder: list[dict], stored: str) -> list[dict]:
    h = data["health"]
    tl = data["timeline"]
    bets = [i for i in data["ideas"] if i["expect"]["lo"] is not None and i["actual_pct"] is not None]
    bets_line = " · ".join(f"{i['id']} bet {bet_text(i['expect']['lo'], i['expect']['hi'])}, got {pct(i['actual_pct'])}" for i in bets)
    words_only = sum(1 for i in data["ideas"] if i["expect"]["text"] and i["expect"]["lo"] is None and i["actual_pct"] is not None)
    n = len([i for i in data["ideas"] if i["status"] != "removed"])
    set_by = {"written": 0, "records": 0, "words": 0}
    for f in fields.values():
        if f.get("rung"):
            set_by[f.get("rung_how") or "written"] += 1
    unassigned = n - sum(set_by.values())
    needs_n = sum(len(f.get("needs", [])) for f in fields.values())
    needs_inf = sum(1 for f in fields.values() for e in f.get("needs", []) if e["how"] != "written")
    open_by_rung = {}
    for i in data["ideas"]:
        if i["status"] in ("open", "trying", "needs-human"):
            r = fields.get(i["id"], {}).get("rung") or "–"
            open_by_rung[r] = open_by_rung.get(r, 0) + 1
    rung_line = " · ".join(f"{v} on rung {k}" for k, v in sorted(open_by_rung.items()) if k != "–")
    if open_by_rung.get("–"):
        rung_line += f" · {open_by_rung['–']} unassigned"
    return [
        {"label": "Ideas left for the agent", "value": {"value": h["open_agent"], "unit": "open"},
         "delta": {"text": "none bets a number" if h["open_agent_with_number"] == 0 else f"{h['open_agent_with_number']} bet a number",
                   "tone": "bad" if h["open_agent"] <= 2 else "neutral"},
         "spark": [{"y": r["open_agent"]} for r in tl],
         "from": f"open in “I'll try” at each of {len(tl)} commits"},
        {"label": "For Zach to decide", "value": {"value": h["open_human"], "unit": "open"},
         "delta": {"text": f"{sum(1 for i in data['ideas'] if i['status'] == 'decided')} decided", "tone": "neutral"},
         "spark": [{"y": r["open_human"]} for r in tl],
         "from": "open in “Suggestions for Zach”"},
        {"label": "Hit rate", "value": {"value": round(100 * h["hit_rate"]), "unit": "%"},
         "delta": {"text": f"{h['new_bests']} new bests of {h['tried_own_solution']} tried", "tone": "neutral"},
         "spark": [{"y": sum(1 for s in data["solutions"] if s["new_best"] and tl_index(tl, s["added_in"]) <= k)} for k in range(len(tl))],
         "from": f"{h['tried']} crossed off · {h['answered_elsewhere']} answered by others' runs"},
        {"label": "Bets vs the ledger", "value": {"value": len(bets), "unit": "numeric bets"},
         "delta": {"text": f"{words_only} more in words only", "tone": "neutral"},
         "from": bets_line},
        {"label": "On the roadmap", "value": {"value": n - unassigned, "unit": f"of {n} on a rung"},
         "delta": {"text": f"{set_by['records'] + set_by['words']} inferred · {unassigned} unassigned", "tone": "neutral"},
         "from": f"{set_by['written'] or 'none'} written by hand yet · open: {rung_line} · {needs_n} Needs: edge{'s' if needs_n != 1 else ''} ({needs_inf} inferred)"},
    ]


def tl_index(tl: list[dict], sha: str | None) -> int:
    for k, r in enumerate(tl):
        if r["sha"] == sha:
            return k
    return 10 ** 9


def studies_line(data: dict) -> str:
    url = (data.get("repo_url") or "").rstrip("/")
    out = []
    for st in data["studies"]:
        kinds = ", ".join(f"{v} {k}" for k, v in st["kinds"].items())
        link = f'<a href="{url}/blob/main/{st["file"]}">{html.escape(st["id"])}</a>' if url and st["file"] else html.escape(st["id"])
        out.append(f"Ablation study {link}: {st['runs']} runs ({kinds}). Study runs, not ideas: counted nowhere above.")
    return " ".join(out)


# ---- the page ------------------------------------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ideas · {name}</title>
<meta name="description" content="Proposal {num} of 5 for the black-box agent's Ideas page: {thesis}">
<link rel="stylesheet" href="../_vendor/data-ui/data-ui.css">
<style>
{frame}
{css}
</style>
<script type="module" src="../_vendor/data-ui/data-ui.js"></script>
<script type="module" src="../_vendor/data-ui/views/kpi.js"></script>
{extra_head}
</head>
<body>
<header class="top"><div class="wrap"><span class="brand">{box}</span><nav>{nav}</nav></div></header>
<main class="wrap">
  <section class="block" id="ideas">
    <h1 class="ih">Ideas</h1>
    <p class="lede">{lede}</p>
    <div class="fuel" id="fuel">{fuel_fallback}</div>
    <p class="study">{studies}</p>
    {element}
  </section>
</main>
<footer class="wrap proposal">Proposal {num} · {name} · roadmap {stored} · rows from <code>{example}</code> (this proposal's format, written by its migration from ideas.md @ <code>{ideas_sha}</code>) joined with ledger.jsonl and meta.json @ <code>{head}</code> · never from solution code · data-ui <code>{dui}</code></footer>
<script type="application/json" id="fuel-data">{fuel_json}</script>
<script type="module">
await customElements.whenDefined('data-kpi');
const cards = JSON.parse(document.getElementById('fuel-data').textContent);
const box = document.getElementById('fuel');
box.textContent = '';
for (const c of cards) {{ const el = document.createElement('data-kpi'); box.append(el); el.card = c; }}
</script>
</body>
</html>
"""

STYLE = """
:root { --data-bg: var(--surface); --data-fg: var(--ink); --data-muted: var(--muted); --data-subtle: var(--surface-2);
  --data-border: var(--line); --data-rule: var(--line); --data-hover: var(--surface-2); --data-accent: var(--accent);
  --data-on-accent: var(--on-accent); --data-warn: var(--warn); --data-good: var(--pass); --data-bad: var(--warn);
  --data-radius: 8px; --data-font: var(--sans); --data-mono: var(--mono); --data-height: 660px; }
h1.ih { font-size: 26px; margin: 0 0 4px; letter-spacing: -0.01em; }
.block { padding-top: 22px; }
.fuel { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin: 4px 0 6px; }
.fuel data-kpi { min-width: 0; }
p.study { color: var(--faint); font-size: 12.5px; margin: 2px 0 14px; }
.fallback { color: var(--muted); font-size: 13px; }
@media (max-width: 1000px) { .fuel { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 640px) { .fuel { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; } :root { --data-height: 600px; } }
"""

NAV = ["Run", "How it's scored", "Joints", "The black box", "Population", "Ideas"]


def frame_css() -> str:
    return open(os.path.join(ROOT, "..", "proposals-ideas", "_shared", "frame.css"), encoding="utf-8").read()


def page(slug: str, num: int, name: str, thesis: str, lede: str, element: str, cards: list[dict], data: dict,
         example: str, css: str = "", extra_head: str = "", stored: str = "") -> str:
    vendor = json.load(open(os.path.join(ROOT, "_vendor", "data-ui", "VENDOR.json"), encoding="utf-8"))
    fallback = " · ".join(f"{c['label']}: {c['value']['value']} {c['value'].get('unit', '')}" for c in cards)
    return PAGE.format(
        name=html.escape(name), num=f"{num:02d}", thesis=html.escape(thesis), lede=lede, element=element,
        frame=frame_css(), css=STYLE + css, extra_head=extra_head,
        box=html.escape(data.get("box") or "Black-box agent"),
        nav="".join(f'<a href="#{"ideas" if n == "Ideas" else ""}" class="{"on" if n == "Ideas" else ""}">{n}</a>' for n in NAV),
        fuel_fallback=f'<span class="fallback">{html.escape(fallback)}</span>',
        studies=studies_line(data), example=html.escape(example), stored=html.escape(stored),
        ideas_sha=data["ideas_md_commit"][:7], head=data["head"][:7], dui=vendor["commit"][:7],
        fuel_json=json.dumps(cards, ensure_ascii=False).replace("</", "<\\/"),
    )


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def write_json(path: str, obj) -> None:
    write(path, json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


# ---- what every proposal's build does ------------------------------------------------------------------------------

V1_SHARED = os.path.join(ROOT, "..", "proposals-ideas", "_shared")
sys.path.insert(0, V1_SHARED)


def ids_by_index(text: str, data: dict) -> dict[int, str]:
    """Each idea's I-NNN (ideas.json, by its line in today's file) keyed by its index in `text` (the same file)."""
    from ideas_parse import parse
    by_line = {i["line"]: i["id"] for i in data["ideas"] if i["line"]}
    return {x.index: by_line[x.line_no] for x in parse(text).ideas if x.line_no in by_line}


def backfill_fields(bf: dict) -> dict:
    """The backfill in the one shape every format.read returns (for tests: read(migrate(x)) must give this back)."""
    out = {}
    for k, v in bf["ideas"].items():
        out[k] = {"rung": v["rung"]["value"] if v["rung"] else None,
                  "rung_how": v["rung"]["how"] if v["rung"] else None,
                  "needs": [(e["to"], e["how"]) for e in v["needs"]]}
    return out


def same_claims(read_fields: dict, bf: dict) -> list[str]:
    """Differences between what a format read back and the backfill it was migrated with (rung, how, needs)."""
    want = backfill_fields(bf)
    bad = []
    for k, w in want.items():
        got = read_fields.get(k, {})
        g = {"rung": got.get("rung"), "rung_how": got.get("rung_how") if got.get("rung") else None,
             "needs": [(e["to"], e["how"]) for e in got.get("needs", [])]}
        if g != w:
            bad.append(f"{k}: read {g}, wrote {w}")
    return bad


REGISTER_LANES = """<script type="module">
import { registerView } from '../_vendor/data-ui/data-ui.js';
// the lens board: a host view over the same rows (../_shared/lanes/lanes.js; its layout is the Oct 3 board's graph.js)
registerView('lanes', { name: 'Roadmap', icon: 'map', load: () => import('../_shared/lanes/lanes.js') });
for (const el of document.querySelectorAll('[data-src]')) el.setAttribute('src', el.dataset.src);
</script>"""

REGISTER_PLAIN = """<script type="module">
await import('../_vendor/data-ui/data-ui.js');
for (const el of document.querySelectorAll('[data-src]')) el.setAttribute('src', el.dataset.src);
</script>"""


def views_element(base: str = "ideas.base") -> str:
    return f'<data-views id="ideas-views" data-src="{base}" views="tabs" view-counts></data-views>'


def build(folder: str, num: int, name: str, thesis: str, lede: str, read_out: dict, example: str, base_text: str,
          element: str, extra_head: str, stored: str, css: str = "", extra_props: dict | None = None,
          extra_rows: dict | None = None, data_name: str = "ideas.json") -> dict:
    """Write one proposal: its data-ui dataset (from what ITS format read back), its .base, its page."""
    data, _ = load()
    ladder = read_out["rungs"]
    ds = dataset(data, read_out["ideas"], ladder, os.path.basename(folder), extra_props, extra_rows)
    write_json(os.path.join(folder, data_name), ds)
    write(os.path.join(folder, "ideas.base"), base_text)
    cards = fuel_cards(data, read_out["ideas"], ladder, stored)
    write(os.path.join(folder, "index.html"),
          page(os.path.basename(folder), num, name, thesis, lede, element, cards, data, example, css, extra_head, stored))
    return ds


def lane_order(ladder: list[dict]) -> list[str]:
    return [f"{r['id']} · {r['name']}" for r in ladder] + ["Unassigned"]


def yaml_list(items: list[str]) -> str:
    return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in items) + "]"


ZOOM = """    record:
      sections:
        - { name: Proof, properties: [outcome, solutions, bet, result] }
        - { name: On the roadmap, properties: [rung, rung_set, rung_why, horizon, needs, needs_why, unlocks, waits_on] }
        - { name: The idea, properties: [words, expect, lane, built_on, queued, closed, source] }"""
