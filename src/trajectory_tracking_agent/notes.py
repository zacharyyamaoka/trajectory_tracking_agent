"""Plain-file notes: one Markdown file per requirement (`specs/`) and per piece of feedback (`feedback/`).

The folders are the database, as in Obsidian: each file is a note a person or an agent writes, with YAML front matter
(properties) and `##` sections, and this module folds a folder into plain dicts. Stdlib only.

    note = parse_note(text)        # {"meta": {...}, "title": "...", "intro": "...", "sections": {"Why": "...", ...}}
    specs = load_specs()           # one dict per specs/<id>-<slug>.md, sorted by id
    notes = load_feedback()        # one dict per feedback/<date>-<slug>.md, sorted by date
    problems = check()             # [] when both folders parse and say what they must (`tta verify` runs this)
    spec_status(spec, outcomes)    # pass | fail | unverified | deferred | not run, from a test run

**A spec** (`specs/O4.3-stop-error-gate.md`): properties `id`, `section` (OBJECTIVES.md's §), `kind` (shall, should,
deferred), `tests` (pytest node-id patterns that prove it; `[]` when nothing does yet), `ruler` (v1); sections
`Requirement` (OBJECTIVES.md's own words, quoted), `What it means`, `Why`, `How it is checked`. OBJECTIVES.md stays
the frozen ruler and the one source of every threshold. WHY no `status` property: a status is computed from a test
run (`spec_status`), never typed, so a note can't claim a pass nobody ran (Vibe Tracks PEP 0023: computed values are
never written to a note).

**A feedback note** (`feedback/2026-11-24-play-back-saved-runs.md`), the shape of Vibe Tracks' feedback notes:
properties `id`, `polarity` (positive, negative), `added`, `from`, `filed_by`, `words` (exact: Observed and Desired
are the person's own words, verbatim; paraphrase: someone else's), `tracks`, `specs` (the spec ids it amends), and
optionally `source` (where the words are quoted), `reacting_to`, `became`, `model`, `withdrawn`; sections `Observed`,
`Desired`, `Why`. An agent's own reading goes in an `> [!ai]` callout under Why, never into his words.

Front matter is the YAML that Obsidian writes for properties: `key: value` scalars, `[a, b]` lists and `- item`
block lists. Anything else (nested maps, multi-line strings) is refused with its line number rather than guessed.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = "specs"
FEEDBACK_DIR = "feedback"

SPEC_KINDS = ("shall", "should", "deferred")
SPEC_SECTIONS = ("Requirement", "What it means", "Why", "How it is checked")
SPEC_REQUIRED = ("id", "section", "kind", "tests", "ruler")
SPEC_ID = re.compile(r"^O(\d+)\.(\d+)$")

FEEDBACK_SECTIONS = ("Observed", "Desired", "Why")
FEEDBACK_REQUIRED = ("id", "polarity", "added", "from", "filed_by", "words", "tracks", "specs")
FEEDBACK_OPTIONAL = ("source", "reacting_to", "became", "model", "withdrawn")
POLARITIES = ("positive", "negative")
WORDS = ("exact", "paraphrase")
FEEDBACK_ID = re.compile(r"^fb-[0-9a-f]{8}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?")

STATUSES = ("pass", "fail", "unverified", "deferred", "not run")


class NoteError(ValueError):
    """A note whose front matter this parser cannot read."""


# ── parsing ─────────────────────────────────────────────────────────────────────────────────────────────────


def _scalar(raw: str, where: str) -> Any:
    """One YAML scalar as Obsidian writes it: quoted string, int, float, bool, null, else the plain string."""
    text = raw.strip()
    if not text:
        return None
    if text[0] == '"':
        if len(text) < 2 or not text.endswith('"'):
            raise NoteError(f"{where}: unterminated double-quoted string")
        return re.sub(r'\\(["\\])', r"\1", text[1:-1])
    if text[0] == "'":
        if len(text) < 2 or not text.endswith("'"):
            raise NoteError(f"{where}: unterminated single-quoted string")
        return text[1:-1].replace("''", "'")
    text = re.sub(r"\s+#.*$", "", text)  # a plain scalar's trailing comment
    if text in ("null", "~", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"[-+]?\d+", text):
        return int(text)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?", text):
        return float(text)
    if text[0] in "{|>&*!%@`":
        raise NoteError(f"{where}: {text[0]!r} starts YAML this parser does not read; quote the value")
    return text


def _flow_list(raw: str, where: str) -> list[Any]:
    """`[a, "b, c", 'd']`: split on commas outside quotes."""
    inner = raw.strip()[1:-1]
    items, current, quote = [], "", None
    for char in inner:
        if quote:
            current += char
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current += char
        elif char == ",":
            items.append(current)
            current = ""
        elif char in "[]{}":
            raise NoteError(f"{where}: nested collections are not read; quote the item")
        else:
            current += char
    if quote:
        raise NoteError(f"{where}: unterminated quote in a list")
    if current.strip() or items:
        items.append(current)
    return [_scalar(item, where) for item in items]


def parse_front_matter(block: str, origin: str = "<note>") -> dict[str, Any]:
    """The lines between the two `---` fences, as a dict (insertion order kept)."""
    meta: dict[str, Any] = {}
    last_key: str | None = None
    for number, line in enumerate(block.splitlines(), start=2):  # line 1 is the opening fence
        where = f"{origin}:{number}"
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s*(.*)$", line)
        if item and last_key is not None and (meta[last_key] is None or isinstance(meta[last_key], list)):
            if meta[last_key] is None:
                meta[last_key] = []
            meta[last_key].append(_scalar(item.group(1), where))
            continue
        pair = re.match(r"^([A-Za-z_][\w-]*):(?:\s+(.*)|\s*)$", line)
        if not pair or line[0].isspace():
            raise NoteError(f"{where}: not a `key: value` property or a `- item` of a list: {line!r}")
        key, raw = pair.group(1), (pair.group(2) or "").strip()
        if key in meta:
            raise NoteError(f"{where}: property {key!r} given twice")
        if raw.startswith("["):
            if not raw.endswith("]"):
                raise NoteError(f"{where}: a `[` list must close on the same line")
            meta[key] = _flow_list(raw, where)
        else:
            meta[key] = _scalar(raw, where)
        last_key = key
    return meta


def parse_note(text: str, origin: str = "<note>") -> dict[str, Any]:
    """A Markdown note → `{"meta", "title", "intro", "sections"}`.

    `title` is the first `# ` heading; `sections` maps each `## ` heading to the text under it (stripped), in order;
    `intro` is the text between the title and the first `##`. Headings inside fenced code blocks are text.
    """
    meta: dict[str, Any] = {}
    body = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        except StopIteration:
            raise NoteError(f"{origin}: front matter opened with --- and never closed") from None
        meta = parse_front_matter("\n".join(lines[1:end]), origin)
        body = "\n".join(lines[end + 1:])
    title: str | None = None
    intro: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    fence: str | None = None
    for line in body.splitlines():
        marker = re.match(r"^\s*(```+|~~~+)", line)
        if marker:
            fence = None if fence and marker.group(1).startswith(fence) else (fence or marker.group(1))
        heading = None if fence or marker else re.match(r"^(#{1,2})\s+(.*?)(?:\s+#+)?\s*$", line)
        if heading and heading.group(1) == "#" and title is None and not sections:
            title = heading.group(2)
            current = intro
            continue
        if heading and heading.group(1) == "##":
            name = heading.group(2)
            if name in sections:
                raise NoteError(f"{origin}: section ## {name} given twice")
            sections[name] = current = []
            continue
        (intro if current is None else current).append(line)
    return {
        "meta": meta,
        "title": title,
        "intro": "\n".join(intro).strip(),
        "sections": {name: "\n".join(text_lines).strip() for name, text_lines in sections.items()},
    }


def read_note(path: Path, root: Path = REPO_ROOT) -> dict[str, Any]:
    """`parse_note` of a file, with its repo-relative `path`."""
    path = Path(path)
    try:
        origin = str(path.relative_to(root))
    except ValueError:
        origin = str(path)
    note = parse_note(path.read_text(encoding="utf-8"), origin)
    note["path"] = origin
    return note


def load_folder(folder: str, root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """Every `*.md` directly in `root/folder`, parsed, in file-name order."""
    directory = Path(root) / folder
    if not directory.is_dir():
        return []
    return [read_note(path, root) for path in sorted(directory.glob("*.md"))]


# ── specs ───────────────────────────────────────────────────────────────────────────────────────────────────


def _spec_order(note: Mapping[str, Any]) -> tuple[int, int, str]:
    match = SPEC_ID.match(str(note["meta"].get("id", "")))
    return (int(match.group(1)), int(match.group(2)), "") if match else (10**6, 0, str(note.get("path")))


def load_specs(root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """`specs/*.md`, sorted by id (O1.1, O1.2, …, O4.10 after O4.9)."""
    return sorted(load_folder(SPECS_DIR, root), key=_spec_order)


def load_feedback(root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """`feedback/*.md`, sorted by `added`, then file name."""
    return sorted(load_folder(FEEDBACK_DIR, root), key=lambda n: (str(n["meta"].get("added", "")), n["path"]))


def match_tests(patterns: Iterable[str], node_ids: Iterable[str]) -> list[str]:
    """The node ids (`tests/test_x.py::test_y[p]`) that any pattern matches (fnmatch, `*` = anything). A pattern naming
    a parametrized test without its `[...]` matches every case of it."""
    patterns = list(patterns)

    def hit(node: str) -> bool:
        bare = re.sub(r"\[.*\]$", "", node)
        return any(fnmatch.fnmatchcase(node, p) or fnmatch.fnmatchcase(bare, p) for p in patterns)

    return [node for node in node_ids if hit(node)]


def spec_status(spec: Mapping[str, Any], outcomes: Mapping[str, bool] | None) -> str:
    """A spec's status, derived from a test run: `outcomes` maps node id → passed (None: no run to read).

    deferred: the kind says so · unverified: no test pattern, or none matches a test in the run · not run: no run ·
    fail: any matched test failed · pass: every matched test passed. The same words as the viewer's spec rows.
    """
    meta = spec.get("meta", spec)
    if meta.get("kind") == "deferred":
        return "deferred"
    patterns = meta.get("tests") or []
    if not patterns:
        return "unverified"
    if outcomes is None:
        return "not run"
    matched = match_tests(patterns, outcomes)
    if not matched:
        return "unverified"
    return "pass" if all(outcomes[node] for node in matched) else "fail"


def objectives_sections(root: Path = REPO_ROOT) -> dict[int, str]:
    """OBJECTIVES.md's numbered `## N. Title` headings: {N: title}."""
    path = Path(root) / "OBJECTIVES.md"
    if not path.exists():
        return {}
    found = re.findall(r"^## (\d+)\. (.+?)\s*$", path.read_text(encoding="utf-8"), re.M)
    return {int(number): title for number, title in found}


def github_anchor(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def check_specs(specs: list[dict[str, Any]], root: Path = REPO_ROOT) -> list[str]:
    problems: list[str] = []
    sections = objectives_sections(root)
    seen: dict[str, str] = {}
    for note in specs:
        meta, where = note["meta"], note["path"]
        missing = [key for key in SPEC_REQUIRED if key not in meta]
        if missing:
            problems.append(f"{where}: missing propert{'y' if len(missing) == 1 else 'ies'} {', '.join(missing)}")
            continue
        if "status" in meta:
            problems.append(f"{where}: `status` is derived from the tests (spec_status), never typed in the note")
        spec_id = str(meta["id"])
        if not SPEC_ID.match(spec_id):
            problems.append(f"{where}: id {spec_id!r} is not O<section>.<n>")
        elif int(SPEC_ID.match(spec_id).group(1)) != meta["section"]:
            problems.append(f"{where}: id {spec_id} is not in section {meta['section']}")
        if spec_id in seen:
            problems.append(f"{where}: id {spec_id} is also {seen[spec_id]}")
        seen[spec_id] = where
        if not Path(where).name.startswith(f"{spec_id}-"):
            problems.append(f"{where}: the file name must start with its id, {spec_id}-")
        if meta["kind"] not in SPEC_KINDS:
            problems.append(f"{where}: kind {meta['kind']!r} is not one of {', '.join(SPEC_KINDS)}")
        if meta["ruler"] != "v1":
            problems.append(f"{where}: ruler {meta['ruler']!r}; OBJECTIVES.md is ruler v1")
        tests = meta["tests"]
        if not isinstance(tests, list) or not all(isinstance(t, str) and t.startswith("tests/") for t in tests):
            problems.append(f"{where}: tests must be a list of pytest node patterns under tests/ ([] when none)")
        elif meta["kind"] == "deferred" and tests:
            problems.append(f"{where}: a deferred requirement has no tests in ruler v1")
        if sections and meta["section"] not in sections:
            problems.append(f"{where}: OBJECTIVES.md has no section {meta['section']}")
        if not note["title"]:
            problems.append(f"{where}: no `# ` title")
        absent = [name for name in SPEC_SECTIONS if name not in note["sections"]]
        if absent:
            problems.append(f"{where}: missing section(s) {', '.join('## ' + a for a in absent)}")
        elif meta["section"] in sections:
            anchor = "OBJECTIVES.md#" + github_anchor(f"{meta['section']}. {sections[meta['section']]}")
            if anchor not in note["sections"]["Requirement"]:
                problems.append(f"{where}: ## Requirement must link its section, {anchor}")
    return problems


def check_feedback(notes: list[dict[str, Any]], spec_ids: Iterable[str]) -> list[str]:
    problems: list[str] = []
    known = set(spec_ids)
    seen: dict[str, str] = {}
    for note in notes:
        meta, where = note["meta"], note["path"]
        missing = [key for key in FEEDBACK_REQUIRED if key not in meta]
        if missing:
            problems.append(f"{where}: missing propert{'y' if len(missing) == 1 else 'ies'} {', '.join(missing)}")
            continue
        unknown = [key for key in meta if key not in FEEDBACK_REQUIRED + FEEDBACK_OPTIONAL]
        if unknown:
            problems.append(f"{where}: unknown propert{'y' if len(unknown) == 1 else 'ies'} {', '.join(unknown)}")
        if not FEEDBACK_ID.match(str(meta["id"])):
            problems.append(f"{where}: id {meta['id']!r} is not fb-<8 hex>")
        if meta["id"] in seen:
            problems.append(f"{where}: id {meta['id']} is also {seen[meta['id']]}")
        seen[meta["id"]] = where
        if meta["polarity"] not in POLARITIES:
            problems.append(f"{where}: polarity {meta['polarity']!r} is not one of {', '.join(POLARITIES)}")
        if meta["words"] not in WORDS:
            problems.append(f"{where}: words {meta['words']!r} is not one of {', '.join(WORDS)}")
        added = str(meta["added"])
        if not ISO_DATE.match(added):
            problems.append(f"{where}: added {added!r} is not an ISO date")
        elif not Path(where).name.startswith(added[:10] + "-"):
            problems.append(f"{where}: the file name must start with its date, {added[:10]}-")
        for key in ("tracks", "specs"):
            if not isinstance(meta[key], list):
                problems.append(f"{where}: {key} must be a list ([] when none)")
        if isinstance(meta["specs"], list):
            stray = [s for s in meta["specs"] if s not in known]
            if stray:
                problems.append(f"{where}: specs {', '.join(map(str, stray))} not in specs/")
        if not note["title"]:
            problems.append(f"{where}: no `# ` title")
        absent = [name for name in FEEDBACK_SECTIONS if name not in note["sections"]]
        if absent:
            problems.append(f"{where}: missing section(s) {', '.join('## ' + a for a in absent)}")
    return problems


def _parse_each(folder: str, root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Every note in `root/folder` that parses, and one problem per note that does not (one bad file hides no other)."""
    directory = Path(root) / folder
    parsed, problems = [], []
    for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        try:
            parsed.append(read_note(path, root))
        except NoteError as error:
            problems.append(str(error))
        except UnicodeDecodeError as error:
            problems.append(f"{folder}/{path.name}: not UTF-8 ({error.reason})")
    return parsed, problems


def check(root: Path = REPO_ROOT) -> list[str]:
    """Every problem in `specs/` and `feedback/` (each file parses and says what it must); [] when clean."""
    specs, problems = _parse_each(SPECS_DIR, root)
    feedback, feedback_problems = _parse_each(FEEDBACK_DIR, root)
    problems += feedback_problems
    if not specs and not problems:
        problems.append(f"{SPECS_DIR}/: no requirement files")
    problems += check_specs(sorted(specs, key=_spec_order), root)
    problems += check_feedback(feedback, (n["meta"].get("id") for n in specs))
    return problems


def summary(root: Path = REPO_ROOT) -> str:
    """One line for `tta verify`: how many specs of each kind and how many feedback notes."""
    specs, feedback = load_specs(root), load_feedback(root)
    kinds = {kind: sum(1 for s in specs if s["meta"].get("kind") == kind) for kind in SPEC_KINDS}
    untested = [s["meta"]["id"] for s in specs if s["meta"].get("kind") != "deferred" and not s["meta"].get("tests")]
    return (f"{SPECS_DIR}/: {len(specs)} requirements ({', '.join(f'{n} {k}' for k, n in kinds.items())}; no test yet: "
            f"{', '.join(untested) or 'none'}); {FEEDBACK_DIR}/: {len(feedback)} notes")
