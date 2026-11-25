"""The `notes` slice (viewer/CONTRACT.md §17): the box's free-form Markdown, for the Notes tab.

Zach, 2026-11-24: "another one for like Notes (which is just like a free form markdown section I think)".

- **`notes/`**, a folder of .md files: one row per note, data-ui's notes-folder rows (data-ui CONTRACT §54, read by
  tools/folds/_notes.py the way `data-ui notes build` reads them; no heading is a column) with `_note` (the file's whole
  text, which the side panel opens in the Obsidian-parity viewer). Each row also gets, when the note does not write
  them itself: `title` (its first `# ` heading, else the file's name), `path`, and `changed` / `sha` (the commit that last
  changed the file, from git log at the ref). The folder's own `.base` (data-ui's rule: `views.base`, else the first) is
  carried as `base`, and the tab hosts its presets unchanged.
- **`NOTES.md`** alone: one page, `{file, text, title (its first `# ` heading, else null), changed, sha}`; with a `notes/` folder as well, it is one more row.
- Neither: the slice is absent, and the Notes tab's empty state says how to add one.

Shape: `{folder, file, rows[], properties{}, base, base_path, text?, title?, changed?, sha?}`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _notes  # noqa: E402


def dated(tree, row: dict, path: str) -> dict:
    last = tree.last_change(path) or {}
    row.setdefault("path", path)
    row.setdefault("changed", last.get("date"))
    row.setdefault("sha", last.get("sha"))
    return row


def fold(facts: dict):
    t = facts["tree"]
    files = _notes.note_files(t, "notes")
    single = "NOTES.md" in t.fileset
    if not files and not single:
        return None
    out = {"folder": "notes/" if files else None, "file": "NOTES.md" if single else None, "rows": [], "properties": {},
           "base": None, "base_path": None}
    if files:
        got = _notes.read_notes(t, "notes/")
        for r in got["rows"]:
            r.setdefault("title", _notes.first_heading(r.get("page") or "") or r["name"])
            out["rows"].append(dated(t, r, f"notes/{r['id']}.md"))
        out["properties"], out["base"], out["base_path"] = got["properties"], got["base"], got["base_path"]
        if single:  # never dropped: NOTES.md beside a folder is one more note
            r = _notes.note_row("NOTES.md", "", t.text("NOTES.md") or "")
            r.pop("_keys")
            r.setdefault("title", _notes.first_heading(r.get("page") or "") or "NOTES")
            out["rows"].append(dated(t, r, "NOTES.md"))
    else:
        text = t.text("NOTES.md") or ""
        _, body = _notes.front_matter(text)
        last = t.last_change("NOTES.md") or {}
        out.update(text=text, title=_notes.first_heading(body), changed=last.get("date"), sha=last.get("sha"))
    return out
