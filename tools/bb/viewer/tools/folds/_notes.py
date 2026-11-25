"""A folder of .md notes at a git ref -> rows, read the way data-ui reads one (data-ui docs/CONTRACT.md §46, §54).

Shared by the notes, references, analysis and tabs folds (a leading `_`: fold_state.py's plug-in loader skips it). One row
per file, data-ui's rules: every `.md` under the folder but README.md, outside dot folders and `attachments/`, sorted by
path; its id the path without `.md`, `name` the file's name; its front matter keys typed from their values (number,
true/false, a list, else the text as written: an ISO date stays its text, as data-ui keeps it); a key named like the row's
own ids is `note_<key>`, a repeated one `<key>_2`; `page` the text after the front matter, blank lines around it left off.
No heading is a column (data-ui's `notes: {sections: false}`): a free-form note's headings are its own, and a row is what
the table needs while the note opens whole in the side panel.

`_note` carries the file's whole text, frontmatter included, for that side panel (the Obsidian-parity viewer draws it).
WHY a leading underscore: data-ui never makes a property of a `_` key (its inferProperties skips them) and a note's own
keys can never take one (their ids are slugs), so the text rides with the row and never becomes a column.

Oracle: tests/tabs.test.mjs runs data-ui's own `data-ui notes build` (its commit the vendored one) over the same files and
compares every row. Stdlib only; every file through the Tree (git show <ref>:<path>), never the working tree.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import PurePosixPath

NUMBER = re.compile(r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")
RESERVED = {"id", "name", "page"}


def plain_scalar(text: str):
    """data-ui base.js plainScalar: null, true/false, a number, else the text."""
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if NUMBER.match(text):
        x = float(text)
        # WHY the text when not finite: a commit sha like `013e521` matches the number pattern and reads as Infinity, which
        # data-ui's index.json then writes as null (a data-ui follow-up); the value as written is the truthful one
        if math.isfinite(x):
            return int(x) if x.is_integer() and not re.search(r"[.eE]", text) else x
    return text


def scalar(text: str):
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] == "'":
        return t[1:-1].replace("''", "'")
    if len(t) >= 2 and t[0] == t[-1] == '"':
        try:
            return json.loads(t)
        except ValueError:
            return t
    return plain_scalar(t)


def strip_comment(text: str) -> str:
    """A `#` after whitespace, outside quotes, starts a comment (data-ui base.js commentAt)."""
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c == "#" and (i == 0 or text[i - 1] == " "):
            return text[:i].rstrip()
        elif c in "\"'" and (i == 0 or text[i - 1] in " \t[{,:-"):
            quote = c
        i += 1
    return text


def flow_list(text: str) -> list:
    out, cur, quote = [], "", None
    for c in text[1:-1]:
        if quote:
            cur += c
            if c == quote:
                quote = None
        elif c in "\"'" and not cur.strip():
            quote = c
            cur += c
        elif c == ",":
            out.append(cur)
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur)
    return [scalar(x) for x in out]


def slug(words: str) -> str:
    """data-ui md-notes.js slug: runs of anything but letters and digits -> `_`, none at either end."""
    s = re.sub(r"[\W_]+", "_", str(words).strip().lower()).strip("_")
    return s or "heading"


def front_matter(text: str) -> tuple[list[tuple[str, object]], str]:
    """([(key, value)], the body after the block). Values typed as data-ui types them; a value the subset cannot read
    (a nested mapping) is kept as its text, as data-ui keeps it."""
    body = text[1:] if text.startswith("﻿") else text
    lines = body.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return [], body
    close = next((i for i in range(1, len(lines)) if re.match(r"^(---|\.\.\.)[ \t]*$", lines[i])), None)
    if close is None:
        return [], body
    entries: list[list] = []
    for line in lines[1:close]:
        m = re.match(r"^(\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*'|[^\s#:-][^:]*?|-[^\s:][^:]*?)[ \t]*:(?:[ \t]|$)", line)
        if m:
            entries.append([re.sub(r"^(['\"])(.*)\1$", r"\2", m.group(1)), line[m.end():], []])
        elif entries and (re.match(r"^\s+\S", line) or line.startswith("- ") or line == "-"):
            entries[-1][2].append(line)
        # a comment at the margin belongs to no key
    out = []
    for key, rest, more in entries:
        rest = strip_comment(rest.strip())
        items = [l for l in more if l.strip()]
        if rest == "" and items and all(re.match(r"^\s*-(\s|$)", l) for l in items):
            value = [scalar(strip_comment(re.sub(r"^\s*-\s?", "", l))) for l in items]
        elif rest == "" and items:
            value = "\n".join(l.rstrip() for l in [line for line in more]).strip("\n")  # a nested block: its text
        elif rest.startswith("[") and rest.endswith("]"):
            value = flow_list(rest)
        elif rest in ("|", "|-", ">", ">-"):
            ind = [l for l in more]
            pad = min((len(l) - len(l.lstrip()) for l in ind if l.strip()), default=0)
            joined = "\n".join(l[pad:] for l in ind)
            value = joined.rstrip("\n") if rest.endswith("-") else joined.rstrip("\n") + "\n"
            if rest.startswith(">"):
                value = re.sub(r"(?<!\n)\n(?!\n)", " ", value)
        else:
            value = scalar(rest)
        out.append((key, value))
    return out, "\n".join(lines[close + 1:])


def trimmed(text: str) -> str:
    """The text with LF line ends, without the blank lines around it (data-ui md-notes.js trimmed)."""
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip(" \t"):
        lines.pop(0)
    while lines and not lines[-1].strip(" \t"):
        lines.pop()
    return "\n".join(lines)


def first_heading(body: str) -> str | None:
    fence = None
    for line in body.split("\n"):
        f = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence):
                fence = None
            continue
        if f:
            fence = f.group(1)
            continue
        m = re.match(r"^#[ \t]+(.*?)[ \t]*(?:[ \t]#+[ \t]*)?$", line)
        if m and m.group(1):
            return m.group(1)
    return None


def note_row(path: str, folder: str, text: str, reserved=RESERVED) -> dict:
    """One file as data-ui's notes row (sections: false), plus `_note`."""
    rel = path[len(folder):] if folder and path.startswith(folder) else path
    nid = rel[:-3] if rel.endswith(".md") else rel
    entries, body = front_matter(text)
    row = {"id": nid, "name": PurePosixPath(nid).name}
    seen: dict[str, int] = {}
    keys = []
    for key, value in entries:
        k = slug(key)
        k = f"note_{k}" if k in reserved else k
        seen[k] = seen.get(k, 0) + 1
        k = k if seen[k] == 1 else f"{k}_{seen[k]}"
        row[k] = value
        keys.append((k, key))
    row["page"] = trimmed(body)
    row["_note"] = text
    row["_keys"] = keys  # the front matter keys as written, in order (popped by the caller: properties)
    return row


def note_files(tree, folder: str) -> list[str]:
    """data-ui notes-folder.js noteFiles: every .md under the folder but README.md, outside dot folders and attachments/."""
    folder = folder.rstrip("/") + "/"
    out = []
    for p in tree.files:
        if not p.startswith(folder) or not p.endswith(".md"):
            continue
        parts = p[len(folder):].split("/")
        if any(x.startswith(".") or x == "attachments" for x in parts[:-1]) or parts[-1].startswith("."):
            continue
        if parts[-1] == "README.md":
            continue
        out.append(p)
    return sorted(out)


def infer_type(values: list) -> str:
    seen = [v for v in values if v is not None and v != "" and v != []]
    if not seen:
        return "text"
    if any(isinstance(v, list) for v in seen):
        return "list"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in seen):
        return "number"
    if all(isinstance(v, bool) for v in seen):
        return "boolean"
    if all(isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$", v)
           for v in seen):
        return "date"
    return "text"


def read_notes(tree, folder: str, *, extra_reserved=()) -> dict:
    """{rows, properties, base}: the folder's notes as data-ui's rows (+ `_note`), the front matter keys' properties typed
    as data-ui types them (with `key`: the name as written, for the note's Properties block), and the folder's own .base
    text when it has one (data-ui ownBase: views.base, else the first .base)."""
    folder = folder.rstrip("/") + "/"
    reserved = RESERVED | set(extra_reserved)
    rows, labels, values = [], {}, {}
    for path in note_files(tree, folder):
        row = note_row(path, folder, tree.text(path) or "", reserved)
        for k, key in row.pop("_keys"):
            labels.setdefault(k, key)
            values.setdefault(k, []).append(row[k])
        rows.append(row)
    properties = {"name": {"type": "text", "label": "Name", "readOnly": True}}
    for k, key in labels.items():
        properties[k] = {"type": infer_type(values[k]), "label": key, "key": key}
    properties["page"] = {"type": "text", "label": "Page", "long": True, "display": "preview", "pageBody": True}
    bases = sorted(p for p in tree.files if p.startswith(folder) and "/" not in p[len(folder):] and p.endswith(".base"))
    own = (folder + "views.base") if (folder + "views.base") in bases else (bases[0] if bases else None)
    return {"rows": rows, "properties": properties, "base": tree.text(own) if own else None, "base_path": own}
