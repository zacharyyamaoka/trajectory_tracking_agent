"""The `tabs` slice (viewer/CONTRACT.md §17): a box's own tabs, any number, each one file.

Zach, 2026-11-24: "like in vibe tracks we can support adding any number of other custom tabs". Vibe Tracks declares a
tab in the track's note (`vibe-tabs: [{title, path}]`); here the box adds a tab by adding a file, and the file's kind is
the tab's kind, each one a `page.json` the site renders after the built-in tabs:

    site/tabs/<order>-<slug>.<ext>      order: digits (optional), the tabs' order; slug: [a-z0-9-], the page id

- `.json`: a page template (`bb-page/1`), used as written; `page` is set to the slug, and a `bb-nav` section is put
  first when it has none.
- `.md`: a Markdown page: `bb-markdown` in the Obsidian-parity viewer (`viewer: obsidian`), the file's whole text.
- `.base`: a rows tab: `bb-data-page` over the state slice its `data:` key names (`data: iterations`), the file its
  presets, hosted unchanged.
- `.html`: self-contained HTML in a sandboxed iframe (`custom-html`, `mode: iframe`): Vibe Tracks' custom tab.

The label: a `.json`'s `name`, a `.md`'s `title:` or first `# ` heading, an `.html`'s `<title>`, else the slug in words.
A slug that is a built-in page id is refused (`why`); so is a `.json` that is not JSON. Other files in site/tabs/
(pictures a tab shows) are not tabs. No site/tabs/: the slice is absent.

Row: `{slug, order, label, kind: page|markdown|rows|html, path, template, why?}`, in order (numbered first), then slug.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _notes  # noqa: E402

DIR = "site/tabs/"
NAME = re.compile(r"^(?:(\d+)-)?([a-z0-9][a-z0-9-]*)\.(json|md|base|html)$")
KIND = {"json": "page", "md": "markdown", "base": "rows", "html": "html"}
# the built-in page ids and the names the site keeps (src/core/slices.js PAGES + PAGE_ALIASES; tests/tabs.test.mjs holds
# this list to that one)
BUILTIN = {"overview", "spec", "feedback", "iterations", "ablation", "agents", "activity", "audits", "analysis", "ideas",
           "references", "notes", "reports", "solution", "tab"}


def words(slug: str) -> str:
    w = slug.replace("-", " ").strip()
    return w[:1].upper() + w[1:]


def nav_first(template: dict) -> dict:
    secs = template.get("sections") if isinstance(template.get("sections"), dict) else {}
    if any(isinstance(s, dict) and s.get("type") == "bb-nav" for s in secs.values()):
        return template
    key = "tabs" if "tabs" not in secs else "bb_tabs"
    order = template.get("order") if isinstance(template.get("order"), list) else []
    return {**template, "sections": {key: {"type": "bb-nav"}, **secs}, "order": [key, *order]}


def page(slug: str, label: str, body: dict) -> dict:
    return {"schema": "bb-page/1", "name": label, "page": slug,
            "sections": {"tabs": {"type": "bb-nav"}, "body": body}, "order": ["tabs", "body"]}


def one(tree, path: str) -> dict:
    m = NAME.match(path[len(DIR):])
    order, slug, ext = (int(m.group(1)) if m.group(1) else None), m.group(2), m.group(3)
    text = tree.text(path) or ""
    row = {"slug": slug, "order": order, "label": words(slug), "kind": KIND[ext], "path": path, "template": None}
    if slug in BUILTIN:
        row["why"] = f'"{slug}" is a built-in page id: name the file something else (site/tabs/<order>-<slug>.{ext})'
        return row
    if ext == "json":
        try:
            t = json.loads(text)
        except ValueError as e:
            row["why"] = f"{path} is not JSON: {e}"
            return row
        if not isinstance(t, dict):
            row["why"] = f"{path} is not a page template (a JSON object)"
            return row
        if isinstance(t.get("name"), str) and t["name"].strip():
            row["label"] = t["name"].strip()
        row["template"] = nav_first({**t, "page": slug})
    elif ext == "md":
        entries, body = _notes.front_matter(text)
        title = dict(entries).get("title")
        row["label"] = (title if isinstance(title, str) and title.strip() else None) or _notes.first_heading(body) or row["label"]
        # the inline title only when the file has no heading of its own (it would say its heading twice)
        row["template"] = page(slug, row["label"], {"type": "bb-markdown", "settings": {
            "markdown": text, "viewer": "obsidian", "title": "" if _notes.first_heading(body) else row["label"]}})
    elif ext == "base":
        m2 = re.search(r"^data:[ \t]*['\"]?([^'\"\s#]+)", text, re.M)
        data = m2.group(1) if m2 else ""
        if not data:
            row["why"] = f"{path} names no rows: add `data: <slice>` (iterations, analysis, references, …)"
        row["slice"] = data or None
        row["template"] = page(slug, row["label"], {"type": "bb-data-page", "settings": {"slice": data, "base_text": text}})
    else:
        t = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        if t and t.group(1).strip():
            row["label"] = re.sub(r"\s+", " ", t.group(1)).strip()
        row["template"] = page(slug, row["label"], {"type": "custom-html", "settings": {"html": text, "mode": "iframe", "height": 720}})
    return row


def fold(facts: dict):
    t = facts["tree"]
    paths = [p for p in t.files if p.startswith(DIR) and "/" not in p[len(DIR):] and NAME.match(p[len(DIR):])]
    if not paths:
        return None
    rows = [one(t, p) for p in paths]
    rows.sort(key=lambda r: (r["order"] is None, r["order"] or 0, r["slug"], r["path"]))
    seen = set()
    for r in rows:  # one page per slug: a second file with the same slug is refused, never silently dropped
        if r["slug"] in seen and "why" not in r:
            r["why"], r["template"] = f'a second tab named "{r["slug"]}": slugs are page ids, so each is one file', None
        seen.add(r["slug"])
    return rows
