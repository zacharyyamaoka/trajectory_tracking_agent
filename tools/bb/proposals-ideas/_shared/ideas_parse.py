"""ideas.md, the queue: a lossless, stdlib-only reader (and a reversible id stamper) for any black-box agent repo.

The queue stays a plain markdown file that Zach (in Obsidian) and an agent both edit by hand. This module never
asks either of them to write anything new: it reads today's conventions, and it reads four optional ones if they
appear. WHY lossless: the file is the record, so a tool that rewrites it must hand back every byte it did not mean
to touch (`parse(text).render() == text`, pinned by test_ideas_parse.py on the real file).

Conventions read today (trajectory_tracking_agent/ideas.md, 2026-11-24):

    ## I'll try                                   -> lane "agent"   (the first list)
    ## Suggestions for Zach                       -> lane "human"   (any heading starting "Suggestions")
    - [ ] <idea>. Expect: <effect>.               -> open, with its expected effect in words
    - [x] ~~<idea>~~ → `<solution id>` <result>   -> closed, linked to the solution(s) named after the arrow

Optional conventions (all backward compatible, all plain markdown; GitHub shows them as text, Obsidian as links):

    ... ^I-007                     a trailing Obsidian block id: the idea's stable id ([[ideas#^I-007]] links to it)
    Expect: −10 % (conf 0.4)       a signed % change of the objective, and a 0-1 confidence
    from `p5s-pass3`               the solution the idea would branch from (before the arrow)
      - indented sub-bullets       continuation lines belong to the idea above them (a notebook-style entry)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
ITEM = re.compile(r"^[-*+] \[([ xX])\] (.*)$")
BLOCK_ID = re.compile(r"\s\^([A-Za-z0-9-]+)\s*$")
STRUCK = re.compile(r"~~(.+?)~~")
TICKED = re.compile(r"`([^`\n]+)`")
ARROW = re.compile(r"\s(?:→|->)\s")
EXPECT = re.compile(r"(\()?\bExpect(?:ed)?:?\s*", re.IGNORECASE)
PCT = re.compile(r"([+−-])?\s*~?\s*(\d+(?:\.\d+)?)(?:\s*[-–]\s*(\d+(?:\.\d+)?))?\s*%")
CONF = re.compile(r"\(conf(?:idence)?\s*[:=]?\s*([01](?:\.\d+)?)\)", re.IGNORECASE)
FROM = re.compile(r"\bfrom `([^`\n]+)`")
ID_LIKE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STAMPED_ID = re.compile(r"^I-\d{3,}$")


@dataclass
class Idea:
    """One list item in a lane. `raw` is its exact text (every line), so the document renders back unchanged."""

    index: int                    # order in the file, 0-based
    line_no: int                  # 1-based line of the checkbox
    lane: str                     # "agent" or "human"
    section: str                  # the heading text, verbatim
    checked: bool
    raw: str
    text: str                     # the item's words without the checkbox, the block id or line breaks
    title: str                    # the struck words if crossed off, else the first sentence
    before_arrow: str
    result: str                   # what follows the arrow ("" while open)
    ticked: list[str]             # every `backticked` token after the arrow, in order
    mentioned: list[str]          # every `backticked` token before the arrow
    block_id: str | None          # the trailing ^id, if written
    expect_text: str | None       # the words after "Expect:" (or "expected"), up to the sentence end
    expect_lo: float | None       # its % change of the objective, as written ("~10-20 %" -> 10, 20)
    expect_hi: float | None
    expect_signed: bool           # True when the % carried an explicit sign
    confidence: float | None
    from_parent: str | None

    def solution_ids(self, known: set[str] | None = None) -> list[str]:
        """Solution ids named after the arrow: the population's ids when `known` is given, else id-shaped tokens."""
        out: list[str] = []
        for token in self.ticked:
            ok = token in known if known is not None else bool(ID_LIKE.match(token))
            if ok and token not in out:
                out.append(token)
        return out


@dataclass
class IdeasDoc:
    lines: list[str]
    ideas: list[Idea] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)

    def render(self) -> str:
        return "".join(self.lines)


def _first_sentence(text: str) -> str:
    """A short name for an idea: its first sentence, cut to a 4+ word head before a colon, minus long asides.

    Only a label: the page always keeps the full text one step away (the title is never the record).
    """
    text = STRUCK.sub(r"\1", text).strip()
    end = re.search(r"(?<=[^\s.])[.?](?=\s|$)", text)
    head = (text[: end.start() + (1 if text[end.start()] == "?" else 0)] if end else text).strip()
    colon = re.search(r":\s", head)
    if colon and len(head[: colon.start()].split()) >= 4:
        head = head[: colon.start()].strip()
    if len(head) > 110:
        head = re.sub(r"\s\((?:[^()]|\([^()]*\))*\)", "", head).strip()
    return head or text


def _expectation(text: str) -> tuple[str | None, float | None, float | None, bool]:
    match = EXPECT.search(text)
    if not match:
        return None, None, None, False
    rest = text[match.end():]
    if match.group(1):                      # "(expected ~5 %)": the aside ends at its own bracket
        end = rest.find(")")
        clause = rest[: end] if end >= 0 else rest
    else:                                   # "Expect: ... ." : the sentence ends at a full stop before a new one
        end = re.search(r"\.(?=\s+[A-Z(*`~])|\.?~~|\.\s*$", rest)
        clause = rest[: end.start()] if end else rest
    clause = clause.replace("~~", "").strip().rstrip(".")
    # WHY: the % must be in the expectation itself, never borrowed from the result ("Got −60 %" is the outcome).
    clause = re.split(r"\bGot\b", clause)[0].strip().rstrip(".")
    pct = PCT.search(clause)
    if not pct:
        if re.search(r"\bno (?:score|objective) change\b", clause, re.IGNORECASE):
            return clause, 0.0, 0.0, True        # "Expect: no score change" is a prediction of 0 %
        return clause, None, None, False
    lo = float(pct.group(2))
    hi = float(pct.group(3)) if pct.group(3) else lo
    return clause, lo, hi, bool(pct.group(1))


def _idea(index: int, line_no: int, lane: str, section: str, raw_lines: list[str]) -> Idea:
    raw = "".join(raw_lines)
    first = ITEM.match(raw_lines[0].rstrip("\n"))
    assert first is not None
    checked = first.group(1) in "xX"
    head = first.group(2)
    block = BLOCK_ID.search(head)          # stamp_ids writes it on the checkbox line, even when sub-bullets follow
    if block:
        head = head[: block.start()].rstrip()
    body = " ".join([head] + [ln.strip() for ln in raw_lines[1:]]).strip()
    if not block:
        block = BLOCK_ID.search(body)      # or the item's last line, where Obsidian puts it on a multi-line item
        if block:
            body = body[: block.start()].rstrip()
    block_id = block.group(1) if block else None
    split = ARROW.search(body)
    before, result = (body[: split.start()], body[split.end():]) if split else (body, "")
    struck = STRUCK.match(before.strip())
    title = _first_sentence(struck.group(1)) if struck else _first_sentence(before)
    # The expectation belongs to the idea; a closed line may restate it after the arrow ("−27 % (expected ~5 %)").
    expect_text, lo, hi, signed = _expectation(before)
    if expect_text is None:
        expect_text, lo, hi, signed = _expectation(result)
    conf = CONF.search(body)
    origin = FROM.search(before)
    return Idea(
        index=index, line_no=line_no, lane=lane, section=section, checked=checked, raw=raw, text=body,
        title=title, before_arrow=before.strip(), result=result.strip(), ticked=TICKED.findall(result),
        mentioned=TICKED.findall(before), block_id=block_id, expect_text=expect_text, expect_lo=lo,
        expect_hi=hi, expect_signed=signed, confidence=float(conf.group(1)) if conf else None,
        from_parent=origin.group(1) if origin else None,
    )


def lane_of(heading: str) -> str:
    return "human" if heading.strip().lower().startswith("suggestion") else "agent"


def parse(text: str) -> IdeasDoc:
    lines = text.splitlines(keepends=True)
    doc = IdeasDoc(lines=lines)
    section, lane = "", "agent"
    i = 0
    while i < len(lines):
        bare = lines[i].rstrip("\n").rstrip("\r")
        heading = HEADING.match(bare)
        if heading and len(heading.group(1)) >= 2:
            section, lane = heading.group(2), lane_of(heading.group(2))
            doc.sections.append(section)
        if ITEM.match(bare):
            j = i + 1
            while j < len(lines) and lines[j].strip() and lines[j][:1] in (" ", "\t"):
                j += 1
            doc.ideas.append(_idea(len(doc.ideas), i + 1, lane, section, lines[i:j]))
            i = j
            continue
        i += 1
    return doc


# ---- the optional id convention: stamp and strip, each the other's exact inverse --------------------------------

def stamp_ids(text: str, ids_by_index: dict[int, str]) -> str:
    """Append ` ^<id>` to the first line of each idea that has none. Every other byte is kept."""
    doc = parse(text)
    for idea in doc.ideas:
        new_id = ids_by_index.get(idea.index)
        if not new_id or idea.block_id:
            continue
        k = idea.line_no - 1
        line = doc.lines[k]
        ending = line[len(line.rstrip("\r\n")):]
        doc.lines[k] = line.rstrip("\r\n") + f" ^{new_id}" + ending
    return doc.render()


def strip_ids(text: str) -> str:
    """Remove every stamped ` ^I-NNN` (and only those), undoing stamp_ids exactly."""
    out = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        match = BLOCK_ID.search(body)
        if ITEM.match(body) and match and STAMPED_ID.match(match.group(1)):
            body = body[: match.start()]
        out.append(body + ending)
    return "".join(out)


if __name__ == "__main__":
    import json
    import sys

    doc = parse(open(sys.argv[1], encoding="utf-8").read())
    for idea in doc.ideas:
        print(json.dumps({k: v for k, v in idea.__dict__.items() if k != "raw"}, ensure_ascii=False))
