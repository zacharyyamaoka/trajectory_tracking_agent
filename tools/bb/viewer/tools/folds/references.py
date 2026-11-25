"""The `references` slice (viewer/CONTRACT.md §3.2, §17): one row per thing the box builds on, for the References tab.

Where the rows come from, first that exists at the ref:
1. **`references/`**, a folder of .md notes, one per reference (Zach, 2026-11-24: files in folders as the database). Each
   is data-ui's notes row (tools/folds/_notes.py) with `_note`, plus the fields the tab reads when the note does not
   write them itself: `title` (its first `# ` heading, else the file's name), `url` (`link:`/`href:`, else the first web
   link in the body), `why` (`description:`/`summary:`, else the body's first paragraph), `section` (`category:`, else its
   sub-folder), `host` and `kind`.
2. **`REFERENCES.md`**: each list item is a row; the `##` heading above it is its `section`. An item reads
   `[title](url): why`, `**title** (where): why` or `title: why` (the three forms the boxes write); a line indented under
   it continues it. trajectory_tracking_agent and claude_party_agent write it this way.
Neither: the slice is absent (the tab's empty state says how to add one). An empty REFERENCES.md: `[]`.

Row: `{id, n, title, url, host, kind: web|local|citation, why, where, section, source, line}`; a folder row also has the
note's own keys and `_note`. Never invents a field: what the file does not say is null.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _notes  # noqa: E402

LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
URL = re.compile(r"https?://[^\s)>\]]+")


def host_of(url: str | None) -> str | None:
    if not url:
        return None
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h or None


def plain(md: str) -> str:
    """Inline marks off a title: **x**, `x`, [x](url) -> x."""
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    while True:  # marks inside marks (**`x`**): until none is left
        u = re.sub(r"(\*\*|__|`)(.+?)\1", r"\2", t)
        if u == t:
            return t.strip()
        t = u


def item_row(text: str) -> dict:
    """One REFERENCES.md item -> {title, url, why, where}. `**title**` is the title whatever it holds; else the title runs
    to the first `: ` (a link's `https://` never matches: no space after its colon), or to a ` — ` after a leading link.
    A `(…)` closing the title (not a link's) is `where`."""
    t = text.strip()
    b = re.match(r"^(\*\*|__)(.+?)\1", t)
    if b:
        head, rest = t[:b.end()], t[b.end():]
        p = re.match(r"^\s*\(([^()]*)\)", rest)
        where = p.group(1).strip().strip("`") or None if p else None
        rest = re.sub(r"^\s*[:—–-]\s*", "", rest[p.end():] if p else rest)
    else:
        cut = re.search(r":\s", t) or (re.search(r"\s[—–-]\s", t) if re.match(r"^\[[^\]]+\]\([^)]+\)", t) else None)
        head, rest = (t[:cut.start()], t[cut.end():]) if cut else (t, "")
        p = re.search(r"(?<!\])\s*\(([^()]*)\)\s*$", head)
        where = None
        if p and plain(head[:p.start()]):
            where, head = p.group(1).strip().strip("`") or None, head[:p.start()]
    found = LINK.search(head) or LINK.search(t)
    url = found.group(2) if found else (URL.search(t).group(0) if URL.search(t) else None)
    return {"title": plain(head), "url": url, "why": rest.strip() or None, "where": where}


def from_list(text: str) -> list[dict]:
    rows, section, cur = [], None, None
    for i, line in enumerate(text.splitlines(), 1):
        h = re.match(r"^(#{2,6})\s+(.*?)\s*#*\s*$", line)
        item = re.match(r"^(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if h:
            section, cur = h.group(2), None
        elif item:
            cur = {"line": i, "section": section, "text": item.group(1)}
            rows.append(cur)
        elif cur is not None and re.match(r"^\s{2,}\S", line):
            cur["text"] += " " + line.strip()
        elif not line.strip():
            pass  # a blank line inside a list keeps the item open for its next indented line
        else:
            cur = None
    out, seen = [], {}
    for n, r in enumerate(rows, 1):
        f = item_row(r["text"])
        base = _notes.slug(f["title"])[:60] or f"ref-{n}"
        seen[base] = seen.get(base, 0) + 1
        out.append({"id": base if seen[base] == 1 else f"{base}-{seen[base]}", "n": n, "title": f["title"], "url": f["url"],
                    "host": host_of(f["url"]), "kind": "web" if f["url"] else "local" if f["where"] else "citation",
                    "why": f["why"], "where": f["where"], "section": r["section"], "source": "REFERENCES.md", "line": r["line"]})
    return out


def first_paragraph(page: str) -> str | None:
    para = []
    for line in page.split("\n"):
        if re.match(r"^#{1,6}\s", line):
            if para:
                break
            continue
        if not line.strip():
            if para:
                break
            continue
        para.append(line.strip())
    return " ".join(para) or None


def from_folder(tree) -> tuple[list[dict], dict]:
    got = _notes.read_notes(tree, "references/")
    rows = []
    for n, r in enumerate(got["rows"], 1):
        page = r.get("page") or ""
        r.setdefault("title", _notes.first_heading(page) or r["name"])
        link = r.get("link") or r.get("href")
        if "url" not in r:
            m = LINK.search(page) or URL.search(page)
            r["url"] = link if isinstance(link, str) else (m.group(2) if m and m.re is LINK else m.group(0) if m else None)
        r.setdefault("why", r.get("description") or r.get("summary") or first_paragraph(page))
        parent = str(PurePosixPath(r["id"]).parent)
        r.setdefault("section", r.get("category") or (parent if parent != "." else None))
        r.setdefault("host", host_of(r["url"] if isinstance(r["url"], str) else None))
        r.setdefault("kind", "web" if r.get("url") else "note")
        r.setdefault("n", n)
        r.setdefault("source", f"references/{r['id']}.md")
        rows.append(r)
    return rows, got["properties"]


def fold(facts: dict):
    t = facts["tree"]
    if _notes.note_files(t, "references"):
        rows, _ = from_folder(t)
        return rows
    text = t.text("REFERENCES.md")
    if text is None:
        return None
    return from_list(text)
