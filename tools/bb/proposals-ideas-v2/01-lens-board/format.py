"""Proposal 01 · Lens board: each idea in ideas.md carries its rung and needs as two optional sub-bullets.

    python3 format.py read  <ideas.md> [<OBJECTIVES.md>]   # what the page reads, as JSON
    python3 format.py strip <ideas.md> <out.md>            # the exact undo of the migration
    (the migration itself runs in build.py, which has the backfill)

The format, plain markdown (Obsidian draws the sub-bullets folded under their idea; GitHub as a nested list):

    - [ ] <idea words>. Expect: <effect>. ^I-021
        - Rung: 1
        - Needs: I-027 · inferred by lane I2 from its words

    - Rung: N        the gate the idea serves: a rung of the box's frozen ladder (OBJECTIVES.md); no line, no rung
    - Needs: I-A, …  it cannot start until those ideas are done; no line, no edge (PICKS.md 2026-11-24)
    · inferred by …  on either line: an agent placed it and Zach has not confirmed it; delete the tail to confirm

The ladder is never written here: rungs are read from the box's own OBJECTIVES.md (roadmap.rungs_from_text).
Ids are the round-1 convention (`^I-NNN` block ids, stamped by the migration). Stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_shared"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "proposals-ideas", "_shared"))

from ideas_parse import parse, stamp_ids, strip_ids  # noqa: E402
import roadmap  # noqa: E402

INDENT = "    "
SUB = re.compile(r"^\s+- (Rung|Needs):\s*(.*?)\s*$")
TAIL = re.compile(r"\s+·\s+inferred by\s+(.+?)\s+from\s+(.+)$")
SOURCE = {"records": "the ledger", "words": "its words"}


def migrate(text: str, ids_by_index: dict[int, str], backfill: dict) -> str:
    """Stamp ^I-NNN, then add a '- Rung:' and a '- Needs:' sub-bullet wherever the backfill has a value, each marked
    inferred with its source. Nothing is written where nothing could be derived."""
    text = stamp_ids(text, ids_by_index)
    doc = parse(text)
    for idea in reversed(doc.ideas):
        rec = backfill["ideas"].get(idea.block_id or "")
        if not rec:
            continue
        subs = []
        if rec["rung"]:
            subs.append(f"{INDENT}- Rung: {rec['rung']['value']} · inferred by {backfill['by']} from {SOURCE[rec['rung']['how']]}")
        if rec["needs"]:
            hows = sorted({SOURCE[e['how']] for e in rec["needs"]})
            subs.append(f"{INDENT}- Needs: {', '.join(e['to'] for e in rec['needs'])} · inferred by {backfill['by']} from {' and '.join(hows)}")
        if not subs:
            continue
        last = idea.line_no - 1 + len(idea.raw.splitlines(keepends=True)) - 1
        line = doc.lines[last]
        ending = line[len(line.rstrip("\r\n")):]
        assert ending, "an idea on the file's last line without a newline: the undo could not be exact"
        doc.lines[last + 1:last + 1] = [s + ending for s in subs]
    return doc.render()


def strip(text: str) -> str:
    """Remove every '- Rung:' / '- Needs:' sub-bullet under an idea and every stamped ^I-NNN: the migration's exact undo."""
    out = [line for line in text.splitlines(keepends=True) if not SUB.match(line.rstrip("\r\n"))]
    return strip_ids("".join(out))


def read(text: str, objectives: str) -> dict:
    ideas = {}
    for idea in parse(text).ideas:
        if not idea.block_id:
            continue
        rec = {"rung": None, "rung_how": None, "rung_why": "no '- Rung:' line under it", "needs": []}
        for line in idea.raw.splitlines()[1:]:
            m = SUB.match(line)
            if not m:
                continue
            key, value = m.groups()
            tail = TAIL.search(value)
            body = value[: tail.start()] if tail else value
            how = ("words" if "words" in tail.group(2) else "records") if tail else "written"
            why = f"its '- {key}:' line says inferred by {tail.group(1)} from {tail.group(2)}" if tail else f"its '- {key}:' line"
            if key == "Rung":
                rec.update(rung=body.split()[0].rstrip("·") if body.split() else None, rung_how=how, rung_why=why)
            else:
                rec["needs"] += [{"to": t, "how": how, "why": why} for t in re.findall(r"\bI-\d{3,}\b", body)]
        ideas[idea.block_id] = rec
    return {"rungs": roadmap.rungs_from_text(objectives), "ideas": ideas}


if __name__ == "__main__":
    cmd, src = sys.argv[1], sys.argv[2]
    text = open(src, encoding="utf-8", newline="").read()
    if cmd == "read":
        objectives = open(sys.argv[3], encoding="utf-8").read() if len(sys.argv) > 3 else ""
        print(json.dumps(read(text, objectives), ensure_ascii=False, indent=1))
    elif cmd == "strip":
        open(sys.argv[3], "w", encoding="utf-8", newline="").write(strip(text))
