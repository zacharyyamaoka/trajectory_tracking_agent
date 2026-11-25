"""specs/ and feedback/: one Markdown note per requirement and per piece of Zach's feedback, folded by `notes.py`.

The parser's own tests first, then the repo's real notes: they parse, every test pattern names a real test, the
numbers and quotes in specs/ are OBJECTIVES.md's, and every `words: exact` note quotes Zach as the repo already does.
Each content check is also run on a deliberately wrong copy, so a check that can never fail would show here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trajectory_tracking_agent import cli, notes

REPO = Path(__file__).resolve().parents[1]
OBJECTIVES = REPO / "OBJECTIVES.md"


# ── the parser ──────────────────────────────────────────────────────────────────────────────────────────────

NOTE = """---
id: O4.3
section: 4
ratio: 0.5
kind: "shall"
note: 'it''s quoted'
flag: true
nothing:
empty: []
tests: ["tests/a.py::test_b*", 'tests/c.py::*', plain]
block:
  - "tests/d.py::test_e"
  - f   # a trailing comment
# a comment line
---

# O4.3 The title

Text before the first section.

## Requirement

> quoted

```python
## not a section
# not a title
```

### a sub-heading stays text

## Why

why text
"""


def test_front_matter_scalars_lists_and_comments():
    meta = notes.parse_note(NOTE)["meta"]
    assert meta == {
        "id": "O4.3", "section": 4, "ratio": 0.5, "kind": "shall", "note": "it's quoted", "flag": True,
        "nothing": None, "empty": [], "tests": ["tests/a.py::test_b*", "tests/c.py::*", "plain"],
        "block": ["tests/d.py::test_e", "f"],
    }


def test_title_intro_and_sections_skip_code_fences():
    note = notes.parse_note(NOTE)
    assert note["title"] == "O4.3 The title"
    assert note["intro"] == "Text before the first section."
    assert list(note["sections"]) == ["Requirement", "Why"]
    assert "## not a section" in note["sections"]["Requirement"]
    assert "# not a title" in note["sections"]["Requirement"]
    assert "### a sub-heading stays text" in note["sections"]["Requirement"]
    assert note["sections"]["Why"] == "why text"


def test_obsidians_block_lists_read_as_the_flow_lists():
    flow = notes.parse_note("---\nspecs: [O1.1, O4.1]\n---\n")["meta"]
    block = notes.parse_note("---\nspecs:\n  - O1.1\n  - O4.1\n---\n")["meta"]
    assert flow == block == {"specs": ["O1.1", "O4.1"]}


def test_a_note_without_front_matter_is_all_body():
    note = notes.parse_note("# Title\n\n## A\n\nx\n")
    assert note["meta"] == {} and note["title"] == "Title" and note["sections"] == {"A": "x"}


@pytest.mark.parametrize("front, why", [
    ("a:\n  b: 1", "not a `key: value`"),
    ("a: 1\na: 2", "given twice"),
    ('a: "open', "unterminated"),
    ("a: {b: 1}", "does not read"),
    ("a: [b, [c]]", "nested"),
    ("a: [b, c", "close on the same line"),
    ("- loose item", "not a `key: value`"),
])
def test_yaml_it_does_not_read_is_refused_with_its_line(front, why):
    with pytest.raises(notes.NoteError, match=why):
        notes.parse_note(f"---\n{front}\n---\n", "x.md")


def test_an_unclosed_front_matter_and_a_repeated_section_are_refused():
    with pytest.raises(notes.NoteError, match="never closed"):
        notes.parse_note("---\na: 1\n")
    with pytest.raises(notes.NoteError, match="twice"):
        notes.parse_note("# T\n## A\n## A\n")


# ── the status is derived, never typed ──────────────────────────────────────────────────────────────────────

RUN = {"tests/t.py::test_a[1]": True, "tests/t.py::test_a[2]": True, "tests/t.py::test_b": False}


@pytest.mark.parametrize("meta, outcomes, status", [
    ({"kind": "deferred", "tests": []}, RUN, "deferred"),
    ({"kind": "shall", "tests": []}, RUN, "unverified"),
    ({"kind": "shall", "tests": ["tests/t.py::test_zzz"]}, RUN, "unverified"),
    ({"kind": "shall", "tests": ["tests/t.py::test_a"]}, None, "not run"),
    ({"kind": "shall", "tests": ["tests/t.py::test_a"]}, RUN, "pass"),
    ({"kind": "shall", "tests": ["tests/t.py::*"]}, RUN, "fail"),
])
def test_spec_status_is_derived_from_a_test_run(meta, outcomes, status):
    assert notes.spec_status({"meta": meta}, outcomes) == status
    assert status in notes.STATUSES


def test_a_typed_status_is_a_problem(tmp_path):
    root = _copy_notes(tmp_path)
    path = root / "specs" / "O4.3-gate-stop-error.md"
    path.write_text(path.read_text().replace("ruler: v1\n", "ruler: v1\nstatus: pass\n", 1))
    assert any("status" in p and "derived" in p for p in notes.check(root))


# ── the real notes ──────────────────────────────────────────────────────────────────────────────────────────

SPEC_IDS = ["O1.1", "O1.2", "O1.3", "O2.1", "O3.1", *(f"O4.{n}" for n in range(1, 11)), *(f"O5.{n}" for n in range(1, 8))]


def test_specs_and_feedback_parse_and_say_what_they_must():
    assert notes.check() == []


def test_the_specs_are_the_spec_maps_ids_and_kinds():
    specs = notes.load_specs()
    assert [s["meta"]["id"] for s in specs] == SPEC_IDS
    kinds = {s["meta"]["id"]: s["meta"]["kind"] for s in specs}
    assert [i for i, k in kinds.items() if k == "should"] == ["O4.10"]
    assert [i for i, k in kinds.items() if k == "deferred"] == [f"O5.{n}" for n in range(1, 8)]
    assert sum(k == "shall" for k in kinds.values()) == 14


def test_the_two_untested_shalls_say_so():
    specs = {s["meta"]["id"]: s for s in notes.load_specs()}
    untested = [i for i, s in specs.items() if s["meta"]["kind"] == "shall" and not s["meta"]["tests"]]
    assert untested == ["O1.1", "O1.3"]
    for spec_id in untested:
        assert specs[spec_id]["sections"]["How it is checked"].startswith("**No test proves it yet**")
        assert notes.spec_status(specs[spec_id], {}) == "unverified"


@pytest.fixture(scope="module")
def collected() -> list[str]:
    """Every test pytest collects in this repo (a fresh collection, whichever tests this run selected)."""
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
                         cwd=REPO, capture_output=True, text=True, timeout=300)
    nodes = [line.strip() for line in out.stdout.splitlines() if "::" in line]
    assert out.returncode == 0 and nodes, out.stdout[-2000:] + out.stderr[-2000:]
    return nodes


def test_every_test_pattern_names_a_collected_test(collected):
    stale = [f"{s['path']}: {pattern}" for s in notes.load_specs() for pattern in s["meta"]["tests"]
             if not notes.match_tests([pattern], collected)]
    assert not stale, "patterns that match no collected test:\n" + "\n".join(stale)


def test_a_stale_pattern_matches_nothing(collected):
    assert notes.match_tests(["tests/test_ruler_acceptance.py::test_gate_completed"], collected)
    assert not notes.match_tests(["tests/test_ruler_acceptance.py::test_gate_completed_renamed"], collected)
    assert notes.match_tests(["tests/test_solutions_provenance.py::test_proposer_is_recorded"], collected)  # [params]


# ── numbers and quotes come from OBJECTIVES.md ──────────────────────────────────────────────────────────────

UNITS = r"mm/s|°/s|mm|ms|Hz|N·m|%|tasks|s|m"
QUANTITY = re.compile(rf"(?<![\w.§/-])(\d+(?:\.\d+)?)(?:\s?(×)|\s?({UNITS})(?![\w/·]))")
SETTING = re.compile(r"\b(seed|speed)\s+(\d+(?:\.\d+)?)", re.I)


def quantities(text: str) -> set[tuple[float, str]]:
    """Every number with a unit (1.0 mm, 2 %, 0.06 °/s, 1.05 ×, 42 tasks) and every seed / speed, as (value, unit)."""
    found = {(float(m.group(1)), m.group(2) or m.group(3)) for m in QUANTITY.finditer(text)}
    return found | {(float(m.group(2)), m.group(1).lower()) for m in SETTING.finditer(text)}


def _body(path: Path) -> str:
    return path.read_text().split("\n---\n", 1)[1]


def stray_numbers(text: str) -> list[tuple[float, str]]:
    return sorted(quantities(text) - quantities(OBJECTIVES.read_text()))


def test_every_number_in_specs_is_an_objectives_number():
    strays = {path.name: stray_numbers(_body(path)) for path in sorted((REPO / "specs").glob("*.md"))}
    strays = {name: found for name, found in strays.items() if found}
    assert not strays, f"numbers OBJECTIVES.md does not state: {strays}"


def test_a_restated_threshold_is_caught():
    text = _body(REPO / "specs" / "O4.3-gate-stop-error.md")
    assert (1.0, "mm") in quantities(text) and not stray_numbers(text)
    assert stray_numbers(text.replace("≤ 1.0 mm", "≤ 0.5 mm")) == [(0.5, "mm")]
    assert stray_numbers("the host ticks at 100 Hz; seed 1002") == [(100.0, "Hz"), (1002.0, "seed")]
    assert stray_numbers("1.10 × a velocity limit") == [(1.1, "×")]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def blockquotes(section_text: str) -> list[str]:
    """The `>` paragraphs of a section (an Obsidian `[!ai]` callout is the agent's own words, so it is skipped)."""
    paragraphs, current = [], []
    for line in section_text.splitlines() + [""]:
        if line.startswith(">") and line[1:].strip():
            current.append(line[1:].strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    return [p for p in paragraphs if not p.startswith("[!")]


def unquoted(fragment_source: str, haystack: str) -> list[str]:
    """The fragments (split at an ellipsis) of `fragment_source` that are not verbatim in `haystack`."""
    hay = _squash(haystack)
    return [f for f in (_squash(part) for part in fragment_source.split("…")) if f and f not in hay]


def test_every_quote_in_specs_is_objectives_verbatim():
    objectives = OBJECTIVES.read_text()
    missing = []
    for spec in notes.load_specs():
        quotes = [q for section in spec["sections"].values() for q in blockquotes(section)]
        assert blockquotes(spec["sections"]["Requirement"]), f"{spec['path']}: ## Requirement quotes nothing"
        missing += [f"{spec['path']}: {f!r}" for q in quotes for f in unquoted(q, objectives)]
    assert not missing, "\n".join(missing)


def test_a_reworded_quote_is_caught():
    objectives = OBJECTIVES.read_text()
    spec = {s["meta"]["id"]: s for s in notes.load_specs()}["O4.8"]
    quote = blockquotes(spec["sections"]["Requirement"])[0]
    assert not unquoted(quote, objectives)
    assert unquoted(quote.replace("is a bug", "is discouraged"), objectives)


# ── feedback quotes Zach only as the repo already does ──────────────────────────────────────────────────────


def his_words(note: dict) -> list[str]:
    """Observed and Desired, paragraph by paragraph, without `>` callouts: under `words: exact` all of it is his."""
    out = []
    for name in ("Observed", "Desired"):
        text = "\n".join(line for line in note["sections"][name].splitlines() if not line.startswith(">"))
        out += [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    return out


def test_exact_words_are_verbatim_in_the_public_file_they_cite():
    problems = []
    for note in notes.load_feedback():
        meta = note["meta"]
        if meta["words"] != "exact":
            continue
        sources = meta.get("source") or []
        assert sources, f"{note['path']}: words: exact needs a source"
        haystack = "\n".join((REPO / s).read_text() for s in sources)
        words = his_words(note)
        assert words, f"{note['path']}: words: exact but Observed and Desired are empty"
        problems += [f"{note['path']}: {f!r}" for w in words for f in unquoted(w, haystack)]
    assert not problems, "\n".join(problems)


def test_a_paraphrase_filed_as_exact_is_caught():
    note = next(n for n in notes.load_feedback() if n["path"].endswith("just-the-ur.md"))
    haystack = (REPO / note["meta"]["source"][0]).read_text()
    assert not unquoted(his_words(note)[0], haystack)
    assert unquoted("only the UR … UR with nothing around it", haystack) == ["only the UR"]


def test_every_spec_a_feedback_note_amends_links_back_to_it():
    specs = {s["meta"]["id"]: s for s in notes.load_specs()}
    missing = [f"{sid} does not link {Path(n['path']).name}" for n in notes.load_feedback() for sid in n["meta"]["specs"]
               if f"../feedback/{Path(n['path']).name}" not in "\n".join(specs[sid]["sections"].values())]
    assert not missing, "\n".join(missing)


def test_feedback_is_filed_by_this_lane_and_names_its_model():
    for note in notes.load_feedback():
        assert note["meta"]["from"] == "Zach"
        assert note["meta"]["filed_by"] and note["meta"]["model"], note["path"]


def test_no_private_paths_or_personal_data_in_notes():
    """The repo is public: no home directories, private repos, vault paths, daily notes or e-mail addresses."""
    forbidden = re.compile(r"/home/|bam_ws|zach_brain|\.claude|Daily Note|Sources/|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
    hits = [f"{path.relative_to(REPO)}: {m.group(0)}" for folder in ("specs", "feedback")
            for path in sorted((REPO / folder).glob("*.md")) for m in forbidden.finditer(path.read_text())]
    assert not hits, "\n".join(hits)


# ── the check catches broken notes, and `tta verify` runs it ────────────────────────────────────────────────


def _copy_notes(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for folder in ("specs", "feedback"):
        shutil.copytree(REPO / folder, root / folder)
    shutil.copy(OBJECTIVES, root / "OBJECTIVES.md")
    return root


@pytest.mark.parametrize("path, old, new, problem", [
    ("specs/O4.4-gate-saturation.md", "kind: shall", "kind: must", "kind 'must'"),
    ("specs/O4.4-gate-saturation.md", "## Why", "## Reasons", "missing section(s) ## Why"),
    ("specs/O4.4-gate-saturation.md", "OBJECTIVES.md#4-the-score", "OBJECTIVES.md#4-score", "must link its section"),
    ("specs/O4.4-gate-saturation.md", "id: O4.4", "id: O4.40", "file name must start with its id"),
    ("specs/O4.4-gate-saturation.md", "section: 4", "section: 3", "not in section 3"),
    ("specs/O5.1-speeds-below-1.md", "tests: []", 'tests: ["tests/x.py::y"]', "deferred requirement has no tests"),
    ("feedback/2026-11-23-just-the-ur.md", "specs: [O2.1]", "specs: [O2.9]", "O2.9 not in specs/"),
    ("feedback/2026-11-23-just-the-ur.md", "words: exact", "words: verbatim", "words 'verbatim'"),
    ("feedback/2026-11-23-just-the-ur.md", "polarity: negative", "polarity: meh", "polarity 'meh'"),
    ("feedback/2026-11-23-just-the-ur.md", "added: 2026-11-23", "added: 2026-11-22", "must start with its date"),
    ("feedback/2026-11-23-just-the-ur.md", "## Desired", "## Wanted", "missing section(s) ## Desired"),
    ("feedback/2026-11-23-just-the-ur.md", "became:", "turned_into:", "unknown property turned_into"),
])
def test_check_names_each_broken_note(tmp_path, path, old, new, problem):
    root = _copy_notes(tmp_path)
    target = root / path
    assert old in target.read_text()
    target.write_text(target.read_text().replace(old, new, 1))
    problems = notes.check(root)
    assert any(problem in p and Path(path).name in p for p in problems), problems


def test_check_reports_a_note_that_does_not_parse(tmp_path):
    root = _copy_notes(tmp_path)
    (root / "feedback" / "2026-11-24-broken.md").write_text("---\nid: fb-00000000\nmap:\n  nested: 1\n---\n")
    problems = notes.check(root)
    assert [p for p in problems if "2026-11-24-broken.md:4" in p] and len(problems) == 1, problems  # the rest still clean


def test_verify_runs_the_notes_check(monkeypatch, capsys):
    assert cli.main(["verify"]) == 0
    assert "OK: specs/: 22 requirements (14 shall, 1 should, 7 deferred" in capsys.readouterr().out
    monkeypatch.setattr(notes, "check", lambda root=None: ["specs/O9.9-x.md: a planted problem"])
    assert cli.main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "FAIL: 1 problem(s) in specs/ and feedback/" in out and "a planted problem" in out


def test_a_commit_sha_in_front_matter_is_quoted() -> None:
    """A bare sha like 013e521 is a YAML 1.2 float (13e521 = infinity) to Obsidian and data-ui, though notes.py keeps it
    as text; quoting every sha makes all three readers agree (lane TABS found data-ui writing it as null, 2026-11-24)."""
    sha = re.compile(r'^(\w+):\s*([0-9a-f]{7,40})\s*$')
    for path in sorted((REPO / "feedback").glob("*.md")) + sorted((REPO / "specs").glob("*.md")):
        head = path.read_text().split("\n---", 1)[0]
        bare = [line for line in head.splitlines() if sha.match(line)]
        assert not bare, f"{path.name}: quote the sha: {bare}"
