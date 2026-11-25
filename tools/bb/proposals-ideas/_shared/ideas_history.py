"""The queue over time: every committed version of ideas.md, each idea followed across versions. Stdlib only.

git already holds the queue's history ("a dashboard tied to the commit"), so nothing new is written to keep it.
An idea is followed by its ^id when it has one; otherwise by its words: the closed form of an idea usually keeps the
words of its open form ("Identify per-joint Coulomb + viscous from dev run records (residual …)" becomes
"~~Identify per-joint Coulomb + viscous from dev run records~~ → …"), so a word-containment match follows it, and a
stamped ^id (ideas_parse.stamp_ids) makes the match exact from then on.

Events per version:
  queued   first seen open                       (the idea was written before anyone tried it)
  logged   first seen already crossed off        (tried first, written down after: no prediction on record)
  closed   open in the last version, crossed now
  edited   still open, words changed
  removed  gone from the file (the file's own rule is "never delete")
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

from ideas_parse import Idea, IdeasDoc, parse

WORD = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
STOP = {"the", "a", "an", "of", "on", "at", "to", "in", "and", "or", "for", "from", "with", "its", "it", "is", "by"}


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


@dataclass
class Commit:
    sha: str
    t: str
    subject: str


@dataclass
class Track:
    """One idea followed through every version of the file it appears in."""

    key: int                                   # birth order (commit, then line)
    born: str                                  # sha of the first version that has it
    versions: dict[str, Idea] = field(default_factory=dict)   # sha -> the idea as written in that version
    events: list[tuple[str, str]] = field(default_factory=list)  # (sha, event)
    removed_at: str | None = None
    block_id: str | None = None

    def first(self) -> Idea:
        return next(iter(self.versions.values()))

    def last(self) -> Idea:
        return list(self.versions.values())[-1]

    def last_open(self) -> Idea | None:
        open_ = [i for i in self.versions.values() if not i.checked]
        return open_[-1] if open_ else None

    def event_sha(self, kind: str) -> str | None:
        return next((sha for sha, e in self.events if e == kind), None)


def _words(idea: Idea) -> set[str]:
    text = re.sub(r"[~*`]", "", idea.before_arrow or idea.text).lower()
    return {w for w in WORD.findall(text) if w not in STOP}


def _title_words(idea: Idea) -> set[str]:
    return {w for w in WORD.findall(re.sub(r"[~*`]", "", idea.title).lower()) if w not in STOP}


def similarity(old: Idea, new: Idea) -> float:
    if old.block_id and new.block_id:
        return 1.0 if old.block_id == new.block_id else 0.0
    a, b = _title_words(old), _title_words(new)
    if not a or not b:
        return 0.0
    # The shorter title's words found anywhere in the other idea's words: a crossed-off title is usually a
    # shortened open text. Exact words, so "Ruler v2: compliance …" and "Ruler v2: speeds …" stay apart.
    short, long_ = (a, _words(new) | b) if len(a) <= len(b) else (b, _words(old) | a)
    contained = len(short & long_) / len(short)
    jaccard = len(a & b) / len(a | b)
    return 0.7 * contained + 0.3 * jaccard


def commits_touching(repo: str, *paths: str) -> list[Commit]:
    out = git(repo, "log", "--reverse", "--format=%H%x09%aI%x09%s", "--", *paths)
    return [Commit(*line.split("\t", 2)) for line in out.splitlines() if line.strip()]


def versions(repo: str, path: str = "ideas.md") -> list[tuple[Commit, IdeasDoc]]:
    return [(c, parse(git(repo, "show", f"{c.sha}:{path}"))) for c in commits_touching(repo, path)]


def follow(history: list[tuple[Commit, IdeasDoc]], threshold: float = 0.55) -> list[Track]:
    tracks: list[Track] = []
    alive: list[Track] = []
    for commit, doc in history:
        previous = {id(t): t.last() for t in alive}
        pairs = []
        for t in alive:
            for idea in doc.ideas:
                score = similarity(previous[id(t)], idea)
                if score >= threshold:
                    pairs.append((score, -abs(previous[id(t)].index - idea.index), t, idea))
        pairs.sort(key=lambda p: (p[0], p[1]), reverse=True)
        taken_tracks: set[int] = set()
        taken_ideas: set[int] = set()
        matched: dict[int, Track] = {}
        for _, _, t, idea in pairs:
            if id(t) in taken_tracks or idea.index in taken_ideas:
                continue
            taken_tracks.add(id(t))
            taken_ideas.add(idea.index)
            matched[idea.index] = t
        next_alive = []
        for idea in doc.ideas:
            t = matched.get(idea.index)
            if t is None:
                t = Track(key=len(tracks), born=commit.sha)
                tracks.append(t)
                t.events.append((commit.sha, "logged" if idea.checked else "queued"))
            else:
                before = t.last()
                if idea.checked and not before.checked:
                    t.events.append((commit.sha, "closed"))
                elif not idea.checked and before.text != idea.text:
                    t.events.append((commit.sha, "edited"))
            t.versions[commit.sha] = idea
            t.block_id = idea.block_id or t.block_id
            next_alive.append(t)
        for t in alive:
            if id(t) not in taken_tracks:
                t.removed_at = commit.sha
                t.events.append((commit.sha, "removed"))
        alive = next_alive
    return tracks


def assign_ids(tracks: list[Track]) -> dict[int, str]:
    """Written ^ids win; every other idea gets I-NNN by birth order (the order it entered the queue)."""
    used = {t.block_id for t in tracks if t.block_id}
    out: dict[int, str] = {}
    n = 0
    for t in sorted(tracks, key=lambda t: t.key):
        if t.block_id:
            out[t.key] = t.block_id
            continue
        n += 1
        while f"I-{n:03d}" in used:
            n += 1
        out[t.key] = f"I-{n:03d}"
    return out


def solutions_added(repo: str) -> dict[str, str]:
    """solution id -> sha of the commit that added its meta.json."""
    out = git(repo, "log", "--reverse", "--diff-filter=A", "--format=C%x09%H", "--name-only", "--",
              "solutions/*/meta.json")
    added: dict[str, str] = {}
    sha = ""
    for line in out.splitlines():
        if line.startswith("C\t"):
            sha = line.split("\t", 1)[1]
        elif line.endswith("/meta.json"):
            added.setdefault(line.split("/")[1], sha)
    return added
