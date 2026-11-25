"""The `analysis` slice (viewer/CONTRACT.md §17): the Analysis tab's rows (the tab Reports became).

Zach, 2026-11-24: "Lets rename Reports to Analysis. And then within there we have reports as one type of analysis but I
can also just have like plain markdown files I write, etc."

One row per file that analyses the box, newest change first. Every `report_files` row (§3.2, the S0 fold's list: the
landing and proposal pages, `reports/*.html`, the site's charts, PROGRESS.md, decision records, `ablations/*.md`), plus
`analysis/**` (.md and .html) and the `.md` files beside the reports (`reports/*.md`). Each row adds:

- `type`: `report` (an HTML page or a chart), `study` (a study file, `ablations/*.md`), or `markdown` (any other .md: a
  note someone wrote, the progress digest, a decision record). The tab's facet.
- `_note`: a Markdown file's whole text (the side panel opens it in the Obsidian-parity viewer); `title` from its first
  `# ` heading when the row had only a file name.
- `url`: the file on the box's repo at the commit read (`about.url` + `/blob/<sha>/<path>`), when the box names its repo.

The `reports` count and `report_files` stay as they are (old pages read them). Absent never: a box with no such file
has `[]`, and the tab says how to add one.
"""

from __future__ import annotations

import math
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _notes  # noqa: E402


def type_of(path: str) -> str:
    if path.endswith(".md"):
        return "study" if re.match(r"^ablations/[^/]+\.md$", path) else "markdown"
    return "report"


def fold(facts: dict):
    t = facts["tree"]
    state = facts["state"]
    rows = [dict(r) for r in state.get("report_files") or []]
    have = {r["path"] for r in rows}
    extra = [p for p in t.files if (p.startswith("analysis/") and p.endswith((".md", ".html")) and "/." not in p
                                    and not PurePosixPath(p).name.startswith(".") and PurePosixPath(p).name != "README.md")
             or re.match(r"^reports/[^/]+\.md$", p)]
    for path in sorted(set(extra) - have):
        last = t.last_change(path) or {}
        first = t.git("log", t.sha, "--diff-filter=A", "--format=%cI", "--", path).split()
        rows.append({"path": path, "kind": "analysis note" if path.endswith(".md") else "report",
                     "title": PurePosixPath(path).name, "date": last.get("date"), "sha": last.get("sha"),
                     "format": PurePosixPath(path).suffix.lstrip(".") or None, "added": first[-1] if first else None})
    repo = (state.get("about") or {}).get("url")
    for r in rows:
        r["id"] = r["path"]
        r["type"] = type_of(r["path"])
        if r["path"].endswith(".md"):
            text = t.text(r["path"]) or ""
            heading = _notes.first_heading(_notes.front_matter(text)[1])
            if heading and r.get("title") in (None, PurePosixPath(r["path"]).name):
                r["title"] = heading
            r["_note"] = text
        r["url"] = f"{repo.rstrip('/')}/blob/{t.sha}/{r['path']}" if repo else None
    rows.sort(key=lambda r: (-when(r.get("date")), r["path"]))  # report_files' order: newest change first, then the path
    return rows


def when(iso: str | None) -> float:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else -math.inf
    except ValueError:
        return -math.inf
