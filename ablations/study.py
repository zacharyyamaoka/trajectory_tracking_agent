"""Parse an ablation study file (the changelog format) into JSON, and check it against the repo (stdlib only).

    python3 ablations/study.py ablations/pass3-2026-11-24.md            # check: links, ideas, costs, ledger rows
    python3 ablations/study.py ablations/pass3-2026-11-24.md --json     # the parsed study, each solution's dev objective joined

The format (proposal 5 of /home/bam/blackbox_agent/proposals-ablation, the one picked by default): front matter (study,
base, target, objective, split, removal), then one `## + <component> — [solution](...)` section per step of the target's
lineage that added a component, each with `- key:`, `- idea: "<quote of its ideas.md line>"`, `- without it at the end:`
(leave-one-out ids, frozen and refit), `- alone on the base:` (add-one-in id) and free prose; `## Not a component`
(refactors), `## Ends` (base, target, history, the greedy path), `## Other ablation variants` (a table), `## Costs`
(code lines and identified parameters, measured by ablations/costs.py) and `## Findings`. A solution is always a link
`[id](../solutions/id/)`; the parser needs only the link text. Views join every objective from ledger.jsonl.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[([a-z0-9][a-z0-9+._-]*)\]\([^)]*\)")

def links(text: str) -> list[str]:
    return LINK.findall(text)


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


def check(study: dict) -> list[str]:
    """What does not resolve: a linked solution with no folder or no dev ledger row, an idea quote not in ideas.md, a
    named solution without its costs row."""
    problems = []
    dev = {}
    for line in (REPO / "ledger.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row.get("split") == "dev":
            dev[row["solution"]] = row
    named = {v["solution"] for v in study["variants"]} | set(study["history"])
    for solution in sorted(named):
        if not (REPO / "solutions" / solution / "meta.json").exists():
            problems.append(f"{solution}: no solutions/{solution}/meta.json")
        if solution not in dev:
            problems.append(f"{solution}: no dev row in ledger.jsonl")
        if solution not in study["costs"]:
            problems.append(f"{solution}: no row in ## Costs")
    ideas = (REPO / "ideas.md").read_text()
    for c in study["components"]:
        if c.get("idea") and c["idea"] not in ideas:
            problems.append(f"{c['key']}: idea quote not found in ideas.md: {c['idea']!r}")
    return problems


def main(argv: list[str]) -> int:
    study = parse_changelog(Path(argv[0]).read_text())
    if "--json" in argv:
        dev = {}
        for line in (REPO / "ledger.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row.get("split") == "dev":
                dev[row["solution"]] = row
        for v in study["variants"]:
            v["objective"] = (dev.get(v["solution"]) or {}).get("objective")
        print(json.dumps(study, indent=1, ensure_ascii=False))
        return 0
    problems = check(study)
    print(f"{len(study['components'])} components, {len(study['variants'])} variants, {len(study['history'])} history steps, "
          f"{len(study['costs'])} cost rows: " + ("ok" if not problems else f"{len(problems)} problems"))
    for problem in problems:
        print("-", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
