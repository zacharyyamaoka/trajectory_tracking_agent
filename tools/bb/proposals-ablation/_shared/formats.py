"""Five backend formats for an ablation study: each a markdown file the agent writes and Zach edits, each with a
writer (canonical study -> markdown) and a parser (markdown -> canonical study). Stdlib only.

    python3 formats.py write <canonical.json> <proposals-ablation dir>     # each proposal's study.md
    python3 formats.py parse <format> <study.md>                           # the canonical JSON on stdout
    python3 formats.py roundtrip <canonical.json>                          # parse(write(x)) == x, per format

The canonical study (what every parser returns; a format may leave out what its view does not need):
    meta        {study, title, base, target, objective, split, removal, date, method}
    components  [{key, name, introduced_by: [solution], idea: quoted text of its ideas.md line or None}]
    variants    [{solution, kind, keeps: [component key], removal: frozen|refit, step: int|None}]
                kind: base | target | lineage | leave-one-out | add-one-in | path | pair | remix-request
    history     [solution]: the search's own path to the target (the lineage, in order)
    costs       {solution: {code_lines, identified_params}}: measured by the agent (ablations/costs.py); the
                objective and the scorecard's diagnostics are never copied here, the views join them from the ledger
    notes       {solution or component key: text}; findings: free markdown

A solution is always written as a link `[id](<solutions>/id/)`, so the file reads on GitHub and the parser needs only
the link text. An idea is a quote of its ideas.md line; the builder finds the line and links `ideas.md#L<n>`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SOLUTIONS_HREF = "../solutions"
FORMATS = ("waterfall", "importance", "remix", "frontier", "changelog")
FOLDERS = {"waterfall": "01-waterfall", "importance": "02-importance", "remix": "03-remix",
           "frontier": "04-frontier", "changelog": "05-changelog"}
LINK = re.compile(r"\[([a-z0-9][a-z0-9+._-]*)\]\([^)]*\)")
META_KEYS = ("study", "title", "base", "target", "objective", "split", "removal", "date", "method")


# ── shared pieces ───────────────────────────────────────────────────────────────────────────────────────────


def link(solution: str) -> str:
    return f"[{solution}]({SOLUTIONS_HREF}/{solution}/)"


def links(text: str) -> list[str]:
    return LINK.findall(text)


def front_matter(meta: dict, extra: dict | None = None) -> list[str]:
    lines = ["---"] + [f"{k}: {meta[k]}" for k in META_KEYS if meta.get(k) is not None]
    lines += [f"{k}: {v}" for k, v in (extra or {}).items()]
    return lines + ["---", ""]


def read_front_matter(text: str) -> tuple[dict, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise ValueError("a study file starts with a --- front matter block ---")
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def sections(body: str) -> dict[str, str]:
    """`## Heading` -> its text (up to the next ## heading)."""
    out, current, buffer = {}, None, []
    for line in body.splitlines():
        if line.startswith("## "):
            if current is not None:
                out[current] = "\n".join(buffer).strip()
            current, buffer = line[3:].strip(), []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        out[current] = "\n".join(buffer).strip()
    return out


def section(parts: dict[str, str], prefix: str) -> str:
    for name, text in parts.items():
        if name.lower().startswith(prefix.lower()):
            return text
    return ""


def table(text: str) -> list[dict[str, str]]:
    rows = [line for line in text.splitlines() if line.strip().startswith("|")]
    if len(rows) < 2:
        return []
    cells = lambda line: [c.strip() for c in line.strip().strip("|").split("|")]  # noqa: E731
    header = cells(rows[0])
    return [dict(zip(header, cells(line), strict=False)) for line in rows[2:]]


def md_table(header: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"] + \
        ["| " + " | ".join(r) + " |" for r in rows] + [""]


def keeps_text(keeps: list[str], order: list[str]) -> str:
    """The shortest of: `base` / `all` / `all −a −b` / `base +a +b`."""
    kept = [k for k in order if k in keeps]
    missing = [k for k in order if k not in keeps]
    if not kept:
        return "base"
    if not missing:
        return "all"
    return "all " + " ".join(f"−{k}" for k in missing) if len(missing) < len(kept) else "base " + " ".join(f"+{k}" for k in kept)


def read_keeps(text: str, order: list[str]) -> list[str]:
    text = text.replace("`", "").strip()
    words = text.split()
    if not words:
        raise ValueError("empty keeps")
    if words[0] == "base":
        keep = {w[1:] for w in words[1:] if w.startswith("+")}
    elif words[0] == "all":
        keep = set(order) - {w.lstrip("−-") for w in words[1:] if w[0] in "−-"}
    else:
        keep = set(words)
    unknown = keep - set(order)
    if unknown:
        raise ValueError(f"unknown components {sorted(unknown)} in {text!r}")
    return [k for k in order if k in keep]


def costs_table(costs: dict, solutions: list[str]) -> list[str]:
    rows = [[link(s), str(costs[s]["code_lines"]), str(costs[s]["identified_params"])] for s in solutions if s in costs]
    return md_table(["solution", "code lines", "identified params"], rows)


def read_costs(text: str) -> dict:
    out = {}
    for row in table(text):
        ids = links(row.get("solution", ""))
        if ids:
            out[ids[0]] = {"code_lines": int(row["code lines"]), "identified_params": int(row["identified params"])}
    return out


def idea_text(text: str) -> str | None:
    match = re.search(r'"([^"]+)"', text)
    return match.group(1) if match else None


def _variant(solution, kind, keeps, removal="frozen", step=None) -> dict:
    return {"solution": solution, "kind": kind, "keeps": keeps, "removal": removal, "step": step}


def _plain(study: dict) -> dict:
    """The fields every format carries, for the round trip."""
    return {"meta": {k: study["meta"].get(k) for k in META_KEYS if study["meta"].get(k) is not None},
            "components": [{k: c.get(k) for k in ("key", "name", "introduced_by", "idea")} for c in study["components"]],
            "variants": sorted(({k: v.get(k) for k in ("solution", "kind", "keeps", "removal", "step")}
                                for v in study["variants"]), key=lambda v: v["solution"] or "~"),
            "history": list(study.get("history") or []), "costs": dict(study.get("costs") or {})}


def _component_rows(study: dict) -> list[str]:
    return [f"- `{c['key']}` {c['name']} · introduced by {', '.join(link(s) for s in c['introduced_by'])}"
            + (f' · idea: "{c["idea"]}"' if c.get("idea") else "") for c in study["components"]]


def _read_component_rows(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        match = re.match(r"- `([a-z0-9_+-]+)` (.*?) · introduced by (.*?)(?: · idea: (.*))?$", line.strip())
        if match:
            out.append({"key": match.group(1), "name": match.group(2).strip(), "introduced_by": links(match.group(3)),
                        "idea": idea_text(match.group(4) or "")})
    return out


def _findings(study: dict) -> list[str]:
    return ["## Findings", "", study.get("findings") or "_The agent writes what the numbers say here._", ""]


def _used(study: dict) -> list[str]:
    """Every solution the study names, for its costs table."""
    seen = []
    for s in [v["solution"] for v in study["variants"]] + list(study.get("history") or []):
        if s and s not in seen:
            seen.append(s)
    return seen


# ── 1 · waterfall: the story file (the path, as a numbered list) ────────────────────────────────────────────


def write_waterfall(study: dict) -> str:
    order = [c["key"] for c in study["components"]]
    by_id = {v["solution"]: v for v in study["variants"]}
    path = sorted((v for v in study["variants"] if v.get("step")), key=lambda v: v["step"])
    lines = front_matter(study["meta"]) + [f"# {study['meta']['title']}", "",
             "The path from the base to the target, one component at a time: read it as \"adding this took it from A to "
             "B\". The numbers come from ledger.jsonl when the page is built; this file only says which solution is "
             "which step.", "", "## Components", ""] + _component_rows(study) + ["", "## Path: what helps most first", ""]
    previous = []
    for v in path:
        added = [k for k in v["keeps"] if k not in previous]
        lines.append(f"{v['step']}. + `{' + '.join(added)}` → {link(v['solution'])}")
        previous = v["keeps"]
    lines += ["", "## Path: as searched", ""]
    previous = []
    for k, s in enumerate(study.get("history") or [], 1):
        keeps = by_id[s]["keeps"] if s in by_id else None
        added = [c for c in (keeps or []) if c not in previous]
        what = f"+ `{' + '.join(added)}`" if added else ("= `refactor`" if keeps == previous or keeps is None else "")
        lines.append(f"{k}. {what} → {link(s)}" + ("" if keeps is not None else " (no component change)"))
        previous = keeps if keeps is not None else previous
    lines += ["", "## Also measured", ""]
    rest = [v for v in study["variants"] if not v.get("step") and v["solution"] not in (study.get("history") or [])]
    lines += md_table(["solution", "keeps", "kind", "removal"],
                      [[link(v["solution"]), keeps_text(v["keeps"], order), v["kind"], v["removal"]] for v in rest])
    lines += ["## Costs (measured by ablations/costs.py)", ""] + costs_table(study["costs"], _used(study)) + _findings(study)
    return "\n".join(lines)


def parse_waterfall(text: str) -> dict:
    meta, body = read_front_matter(text)
    parts = sections(body)
    components = _read_component_rows(section(parts, "Components"))
    order = [c["key"] for c in components]
    variants, history = {}, []
    for line in section(parts, "Path: what helps most").splitlines():
        match = re.match(r"(\d+)\. \+ `([^`]+)` → (.*)", line.strip())
        if match:
            added = [k.strip() for k in match.group(2).split("+")]
            prev = variants[max(variants, key=lambda s: variants[s]["step"])]["keeps"] if variants else []
            solution = links(match.group(3))[0]
            variants[solution] = _variant(solution, "path", [k for k in order if k in set(prev) | set(added)],
                                          step=int(match.group(1)))
    keeps_so_far: list[str] = []
    for line in section(parts, "Path: as searched").splitlines():
        match = re.match(r"(\d+)\. (?:\+ `([^`]+)`|= `refactor`)? ?→ (.*)", line.strip())
        if match:
            solution = links(match.group(3))[0]
            history.append(solution)
            if "(no component change)" in line:
                continue
            if match.group(2):
                keeps_so_far = [k for k in order if k in set(keeps_so_far) | {x.strip() for x in match.group(2).split("+")}]
            if solution not in variants:
                variants[solution] = _variant(solution, "lineage", keeps_so_far)
    for row in table(section(parts, "Also measured")):
        solution = links(row["solution"])[0]
        variants[solution] = _variant(solution, row["kind"], read_keeps(row["keeps"], order), row["removal"])
    return {"meta": meta, "components": components, "variants": list(variants.values()), "history": history,
            "costs": read_costs(section(parts, "Costs")), "findings": section(parts, "Findings")}


# ── 2 · importance: one row per component (without it / without it, refit / it alone) ──────────────────────


def write_importance(study: dict) -> str:
    order = [c["key"] for c in study["components"]]
    full, none = set(order), set()
    variants = study["variants"]

    def find(keeps: set, removal="frozen", kinds=None):
        hits = [v for v in variants if set(v["keeps"]) == keeps and v["removal"] == removal
                and (kinds is None or v["kind"] in kinds)]
        return hits[0]["solution"] if hits else None

    rows = []
    for c in study["components"]:
        k = c["key"]
        cell = lambda s: link(s) if s else "—"  # noqa: E731
        rows.append([f"`{k}`", c["name"], " ".join(link(s) for s in c["introduced_by"]), cell(find(full - {k})),
                     cell(find(full - {k}, "refit")), cell(find({k})), f'"{c["idea"]}"' if c.get("idea") else "—"])
    lines = front_matter(study["meta"]) + [f"# {study['meta']['title']}", "",
             "One row per component of the target. *Without it* = the target with that component removed (leave-one-out); "
             "*refit* = the same, then one identification pass on its own runs; *alone* = the base plus only that component "
             "(add-one-in). Cells are solution ids; the builder reads their objective from the ledger.", "",
             "## Components", ""]
    lines += md_table(["key", "component", "introduced by", "without it", "without it, refit", "it alone", "idea"], rows)
    singles = {s for s in (find(full - {k}) for k in order) if s} | {s for s in (find(full - {k}, "refit") for k in order) if s} | \
        {s for s in (find({k}) for k in order) if s}
    pairs = [v for v in variants if v["kind"] == "pair" or (v["solution"] not in singles and len(v["keeps"]) in (2, len(order) - 2)
                                                            and v["kind"] not in ("path",))]
    lines += ["## Pairs", ""]
    lines += md_table(["solution", "keeps", "removal"], [[link(v["solution"]), keeps_text(v["keeps"], order), v["removal"]]
                                                          for v in pairs])
    lines += ["## Greedy path (Fawcett & Hoos)", ""]
    for v in sorted((v for v in variants if v.get("step")), key=lambda v: v["step"]):
        lines.append(f"{v['step']}. {keeps_text(v['keeps'], order)} → {link(v['solution'])}")
    lines += ["", "## Ends", "", f"- base: {link(study['meta']['base'])}", f"- target: {link(study['meta']['target'])}",
              "- history: " + " → ".join(link(s) for s in study.get("history") or []), ""]
    rest = [v for v in variants if v["solution"] not in singles | {p["solution"] for p in pairs} and not v.get("step")
            and v["kind"] not in ("base", "target")]
    if rest:
        lines += ["## Other variants", ""] + md_table(["solution", "keeps", "kind", "removal"],
                                                     [[link(v["solution"]), keeps_text(v["keeps"], order), v["kind"], v["removal"]] for v in rest])
    lines += ["## Costs (measured by ablations/costs.py)", ""] + costs_table(study["costs"], _used(study)) + _findings(study)
    return "\n".join(lines)


def parse_importance(text: str) -> dict:
    meta, body = read_front_matter(text)
    parts = sections(body)
    rows = table(section(parts, "Components"))
    components = [{"key": r["key"].strip("`"), "name": r["component"], "introduced_by": links(r["introduced by"]),
                   "idea": idea_text(r["idea"])} for r in rows]
    order = [c["key"] for c in components]
    variants: dict[str, dict] = {}

    def put(v):
        old = variants.get(v["solution"])
        variants[v["solution"]] = v if old is None or old.get("step") is None and v.get("step") else old

    for r in rows:
        k = r["key"].strip("`")
        for column, kind, removal, keeps in (("without it", "leave-one-out", "frozen", [x for x in order if x != k]),
                                             ("without it, refit", "leave-one-out", "refit", [x for x in order if x != k]),
                                             ("it alone", "add-one-in", "frozen", [k])):
            for s in links(r[column]):
                put(_variant(s, kind, keeps, removal))
    for r in table(section(parts, "Pairs")):
        put(_variant(links(r["solution"])[0], "pair", read_keeps(r["keeps"], order), r["removal"]))
    for line in section(parts, "Greedy path").splitlines():
        match = re.match(r"(\d+)\. (.*?) → (.*)", line.strip())
        if match:
            s = links(match.group(3))[0]
            v = _variant(s, "path", read_keeps(match.group(2), order), step=int(match.group(1)))
            if s in variants:
                variants[s]["step"] = v["step"]
            else:
                variants[s] = v
    ends = section(parts, "Ends")
    history = []
    for line in ends.splitlines():
        if line.startswith("- base:"):
            meta["base"] = links(line)[0]
        elif line.startswith("- target:"):
            meta["target"] = links(line)[0]
        elif line.startswith("- history:"):
            history = links(line)
    for r in table(section(parts, "Other variants")):
        put(_variant(links(r["solution"])[0], r["kind"], read_keeps(r["keeps"], order), r["removal"]))
    for s, kind, keeps in ((meta["base"], "base", []), (meta["target"], "target", order)):
        if s not in variants:
            variants[s] = _variant(s, kind, keeps)
    return {"meta": meta, "components": components, "variants": list(variants.values()), "history": history,
            "costs": read_costs(section(parts, "Costs")), "findings": section(parts, "Findings")}


# ── 3 · remix: the incidence matrix (one row per variant, one column per component) ─────────────────────────


def write_remix(study: dict) -> str:
    order = [c["key"] for c in study["components"]]
    lines = front_matter(study["meta"]) + [f"# {study['meta']['title']}", "",
             "One row per measured combination: ● = the component is in, blank = out. A row whose solution is `?` is a "
             "remix request: the agent runs it next (`tta new` + `tta evaluate`) and writes the id in.", "",
             "## Components", ""] + _component_rows(study) + ["", "## Variants", ""]
    rank = {"base": 0, "target": 1, "lineage": 2, "leave-one-out": 3, "add-one-in": 4, "pair": 5, "path": 6}
    ordered = sorted(study["variants"], key=lambda v: (rank.get(v["kind"], 9), v.get("step") or 0, v["solution"] or "~"))
    rows = [[link(v["solution"]) if v["solution"] else "?"] + ["●" if k in v["keeps"] else "" for k in order]
            + [v["kind"], v["removal"], str(v.get("step") or ""), str(study["costs"].get(v["solution"], {}).get("code_lines", "")),
               str(study["costs"].get(v["solution"], {}).get("identified_params", ""))] for v in ordered]
    lines += md_table(["solution"] + [f"`{k}`" for k in order] + ["kind", "removal", "step", "code lines", "identified params"], rows)
    lines += ["## History", "", " → ".join(link(s) for s in study.get("history") or []), ""]
    extra = [s for s in study["costs"] if s not in {v["solution"] for v in study["variants"]} and s in (study.get("history") or [])]
    if extra:
        lines += ["## Costs of history steps not in the matrix", ""] + costs_table(study["costs"], extra)
    lines += _findings(study)
    return "\n".join(lines)


def parse_remix(text: str) -> dict:
    meta, body = read_front_matter(text)
    parts = sections(body)
    components = _read_component_rows(section(parts, "Components"))
    order = [c["key"] for c in components]
    variants, costs = [], {}
    for r in table(section(parts, "Variants")):
        ids = links(r["solution"])
        solution = ids[0] if ids else None
        keeps = [k for k in order if r.get(f"`{k}`", "").strip() in ("●", "x", "X", "1", "y")]
        variants.append(_variant(solution, r["kind"] if solution else "remix-request", keeps, r.get("removal") or "frozen",
                                 int(r["step"]) if r.get("step") else None))
        if solution and r.get("code lines"):
            costs[solution] = {"code_lines": int(r["code lines"]), "identified_params": int(r["identified params"])}
    costs.update(read_costs(section(parts, "Costs of history")))
    return {"meta": meta, "components": components, "variants": variants, "history": links(section(parts, "History")),
            "costs": costs, "findings": section(parts, "Findings")}


# ── 4 · frontier: declared cost axes, then one line per point ───────────────────────────────────────────────

AXES = ("objective: tool_track_rms_mm (ledger, mm, lower) | code_lines (study, lines, lower) | identified_params (study, "
        "numbers, lower) | host_compute_ms_p95 (ledger, ms, lower) | energy_j (ledger, J, lower) | saturation_share_pct "
        "(ledger, %, lower)")


def write_frontier(study: dict) -> str:
    order = [c["key"] for c in study["components"]]
    lines = front_matter(study["meta"], {"axes": AXES}) + [f"# {study['meta']['title']}", "",
             "Every point is a solution. `axes` in the front matter says which numbers are plotted, where each comes from "
             "(`ledger` = the ledger row's objective or diagnostics, `study` = written below by the agent, measured by "
             "ablations/costs.py) and which way is better.", "", "## Components", ""] + _component_rows(study)
    lines += ["", "## Points", ""]
    for v in study["variants"]:
        c = study["costs"].get(v["solution"], {})
        step = f" · step {v['step']}" if v.get("step") else ""
        lines.append(f"- {link(v['solution'])} — {keeps_text(v['keeps'], order)} — {v['kind']}, {v['removal']}{step} — "
                     f"code_lines {c.get('code_lines', '?')} · identified_params {c.get('identified_params', '?')}")
    lines += ["", "## History (drawn as a path through the cost space)", ""]
    for s in study.get("history") or []:
        c = study["costs"].get(s, {})
        lines.append(f"- {link(s)} — code_lines {c.get('code_lines', '?')} · identified_params {c.get('identified_params', '?')}")
    lines += [""] + _findings(study)
    return "\n".join(lines)


def parse_frontier(text: str) -> dict:
    meta, body = read_front_matter(text)
    parts = sections(body)
    components = _read_component_rows(section(parts, "Components"))
    order = [c["key"] for c in components]
    variants, costs = [], {}

    def read_costs_tail(tail: str, solution: str):
        numbers = dict(re.findall(r"(code_lines|identified_params) (\d+)", tail))
        if numbers:
            costs[solution] = {"code_lines": int(numbers["code_lines"]), "identified_params": int(numbers["identified_params"])}

    for line in section(parts, "Points").splitlines():
        match = re.match(r"- (\[[^\]]+\]\([^)]*\)) — (.*?) — ([a-z-]+), (frozen|refit)(?: · step (\d+))? — (.*)", line.strip())
        if match:
            solution = links(match.group(1))[0]
            variants.append(_variant(solution, match.group(3), read_keeps(match.group(2), order), match.group(4),
                                     int(match.group(5)) if match.group(5) else None))
            read_costs_tail(match.group(6), solution)
    history = []
    for line in section(parts, "History").splitlines():
        ids = links(line)
        if ids:
            history.append(ids[0])
            read_costs_tail(line, ids[0])
    axes = []
    for item in meta.get("axes", "").split("|"):
        match = re.match(r"\s*(?:objective: )?([a-z0-9_]+) \((ledger|study), ([^,]+), (lower|higher)\)", item)
        if match:
            axes.append({"key": match.group(1), "source": match.group(2), "unit": match.group(3), "better": match.group(4)})
    meta["axes"] = axes
    return {"meta": meta, "components": components, "variants": variants, "history": history, "costs": costs,
            "findings": section(parts, "Findings")}


# ── 5 · changelog: one section per kept step of the search, then what was not kept ──────────────────────────


def write_changelog(study: dict) -> str:
    order = [c["key"] for c in study["components"]]
    full = set(order)
    variants = study["variants"]
    owner = {s: c for c in study["components"] for s in c["introduced_by"]}

    def find(keeps: set, removal="frozen"):
        hits = [v["solution"] for v in variants if set(v["keeps"]) == keeps and v["removal"] == removal]
        return hits[0] if hits else None

    lines = front_matter(study["meta"]) + [f"# {study['meta']['title']}", "",
             "The search condensed: one section per step of the target's lineage that changed a component, in the order "
             "the search took them, with what removing it from the end costs and what it does alone. Steps that changed "
             "no component are listed under *Not a component*. The builder adds every number from the ledger.", ""]
    done = set()
    for s in study.get("history") or []:
        c = owner.get(s)
        if c is None or c["key"] in done:
            continue
        done.add(c["key"])
        k = c["key"]
        lines += [f"## + {c['name']} — " + ", ".join(link(x) for x in c["introduced_by"]), "", f"- key: `{k}`"]
        if c.get("idea"):
            lines.append(f'- idea: "{c["idea"]}"')
        out = [x for x in (find(full - {k}), find(full - {k}, "refit")) if x]
        lines.append("- without it at the end: " + (" · ".join(f"{link(x)} ({'refit' if find(full - {k}, 'refit') == x else 'frozen'})"
                                                                for x in out) or "—"))
        alone = find({k})
        lines.append(f"- alone on the base: {link(alone) if alone else '—'}")
        note = (study.get("notes") or {}).get(k)
        lines += ["", note, ""] if note else [""]
    others = [s for s in study.get("history") or [] if s not in owner and s not in (study["meta"]["base"], study["meta"]["target"])]
    lines += ["## Not a component", ""] + [f"- {link(s)} — {(study.get('notes') or {}).get(s, 'no component change')}" for s in others]
    lines += ["", "## Ends", "", f"- base: {link(study['meta']['base'])}", f"- target: {link(study['meta']['target'])}",
              "- history: " + " → ".join(link(s) for s in study.get("history") or []),
              "- greedy path: " + " · ".join(f"{v['step']} {link(v['solution'])}" for v in
                                              sorted((v for v in variants if v.get("step")), key=lambda v: v["step"])), ""]
    named = {v["solution"] for v in variants if set(v["keeps"]) in [full - {k} for k in order] + [{k} for k in order]}
    rest = [v for v in variants if v["solution"] not in named and v["kind"] not in ("base", "target", "lineage")]
    lines += ["## Other ablation variants", ""] + md_table(["solution", "keeps", "kind", "removal", "step"],
                                                         [[link(v["solution"]), keeps_text(v["keeps"], order), v["kind"],
                                                           v["removal"], str(v.get("step") or "")] for v in rest])
    lines += ["## Costs (measured by ablations/costs.py)", ""] + costs_table(study["costs"], _used(study)) + _findings(study)
    return "\n".join(lines)


def parse_changelog(text: str) -> dict:
    meta, body = read_front_matter(text)
    parts = sections(body)
    components, variants = [], {}
    for name, text_ in parts.items():
        match = re.match(r"\+ (.*?) — (.*)", name)
        if not match:
            continue
        key = re.search(r"- key: `([^`]+)`", text_).group(1)
        idea = re.search(r"- idea: (.*)", text_)
        components.append({"key": key, "name": match.group(1).strip(), "introduced_by": links(match.group(2)),
                           "idea": idea_text(idea.group(1)) if idea else None})
    order = [c["key"] for c in components]
    notes = {}
    for c in components:
        text_ = section(parts, f"+ {c['name']}")
        prose = [line for line in text_.splitlines() if line.strip() and not line.lstrip().startswith("- ")]
        if prose:
            notes[c["key"]] = " ".join(line.strip() for line in prose)
        without = re.search(r"- without it at the end: (.*)", text_)
        for s, removal in re.findall(r"\[([^\]]+)\]\([^)]*\) \((frozen|refit)\)", without.group(1) if without else ""):
            variants[s] = _variant(s, "leave-one-out", [k for k in order if k != c["key"]], removal)
        alone = re.search(r"- alone on the base: (.*)", text_)
        for s in links(alone.group(1) if alone else ""):
            variants.setdefault(s, _variant(s, "add-one-in", [c["key"]]))
    history, path_steps = [], {}
    for line in section(parts, "Ends").splitlines():
        if line.startswith("- base:"):
            meta["base"] = links(line)[0]
        elif line.startswith("- target:"):
            meta["target"] = links(line)[0]
        elif line.startswith("- history:"):
            history = links(line)
        elif line.startswith("- greedy path:"):
            path_steps = {s: int(n) for n, s in re.findall(r"(\d+) \[([^\]]+)\]", line)}
    for r in table(section(parts, "Other ablation variants")):
        s = links(r["solution"])[0]
        variants[s] = _variant(s, r["kind"], read_keeps(r["keeps"], order), r["removal"], int(r["step"]) if r.get("step") else None)
    keeps = []
    owner = {s: c["key"] for c in components for s in c["introduced_by"]}
    for s in history:
        if s in owner and owner[s] not in keeps:
            keeps = [k for k in order if k in set(keeps) | {owner[s]}]
        if s == meta["base"]:
            variants.setdefault(s, _variant(s, "base", []))
        elif s == meta["target"]:
            variants.setdefault(s, _variant(s, "target", order))
        elif s in owner and s == [c for c in components if c["key"] == owner[s]][0]["introduced_by"][-1]:
            variants.setdefault(s, _variant(s, "lineage", keeps))
    for s, step in path_steps.items():
        variants.setdefault(s, _variant(s, "path", []))["step"] = step
    for line in section(parts, "Not a component").splitlines():
        match = re.match(r"- \[([^\]]+)\]\([^)]*\) — (.*)", line.strip())
        if match:
            notes[match.group(1)] = match.group(2)
    return {"meta": meta, "components": components, "variants": list(variants.values()), "history": history,
            "costs": read_costs(section(parts, "Costs")), "findings": section(parts, "Findings"), "notes": notes}


WRITERS = {"waterfall": write_waterfall, "importance": write_importance, "remix": write_remix,
           "frontier": write_frontier, "changelog": write_changelog}
PARSERS = {"waterfall": parse_waterfall, "importance": parse_importance, "remix": parse_remix,
           "frontier": parse_frontier, "changelog": parse_changelog}


def main(argv: list[str]) -> None:
    if argv[0] == "write":
        study = json.loads(Path(argv[1]).read_text())
        for name, folder in FOLDERS.items():
            path = Path(argv[2]) / folder / "study.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(WRITERS[name](study))
            print(path, len(path.read_text().splitlines()), "lines")
    elif argv[0] == "parse":
        print(json.dumps(PARSERS[argv[1]](Path(argv[2]).read_text()), indent=1, ensure_ascii=False))
    elif argv[0] == "roundtrip":
        study = json.loads(Path(argv[1]).read_text())
        for name in FORMATS:
            back = PARSERS[name](WRITERS[name](study))
            print(name, roundtrip_report(study, back))


def roundtrip_report(study: dict, back: dict) -> str:
    a, b = _plain(study), _plain(back)
    problems = []
    if a["components"] != b["components"]:
        problems.append("components differ")
    va = {v["solution"]: v for v in a["variants"]}
    vb = {v["solution"]: v for v in b["variants"]}
    for s in sorted(set(va) | set(vb), key=str):
        x, y = va.get(s), vb.get(s)
        if x is None or y is None:
            problems.append(f"{s}: {'missing' if y is None else 'extra'}")
        elif x["keeps"] != y["keeps"] or x["removal"] != y["removal"] or x.get("step") != y.get("step"):
            problems.append(f"{s}: {x} != {y}")
    if a["history"] != b["history"]:
        problems.append("history differs")
    lost = [s for s in _used(study) if s in a["costs"] and b["costs"].get(s) != a["costs"][s]]
    if lost:
        problems.append(f"costs lost for {lost}")
    return "ok" if not problems else "; ".join(problems)


if __name__ == "__main__":
    main(sys.argv[1:])
