"""No tracked file names a private path, the vault or a person's email (this repo is public).

WHY every tracked file and not only site/ (2026-11-25): the site scans (test_site_static, test_dropins,
test_coverage_pages) only read what Pages serves, so ablations/study.py's docstring carried a home path into public
history from a5d5982 until this test. The guards' own patterns are the one allowed mention: a line that compiles the
pattern is skipped, nothing else is.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIVATE = re.compile(r"/home/[A-Za-z]|/Users/[A-Za-z]|zach_brain|bam_ws|\.claude/|[A-Za-z0-9._%+-]+@(?:gmail|dfuture|ambienceppe)\.")
# a guard line: it defines or tests for the pattern, it does not leak one
GUARD = re.compile(r"re\.compile\(|forbidden|PRIVATE|LEAK|not in|for local in|planted")
SKIP_SUFFIXES = {".rrd", ".png", ".jpg", ".gif", ".mp4", ".webm", ".npz", ".gz", ".svg", ".ico", ".woff", ".woff2"}


def tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    return [REPO / name for name in out.decode().split("\0") if name and Path(name).suffix not in SKIP_SUFFIXES]


def test_no_tracked_file_names_a_private_path():
    leaks = []
    for path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if PRIVATE.search(line) and not GUARD.search(line):
                leaks.append(f"{path.relative_to(REPO)}:{number}: {line.strip()[:120]}")
    assert leaks == [], "private paths in tracked files (the repo is public):\n" + "\n".join(leaks)


def test_the_check_finds_a_planted_home_path(tmp_path):
    planted = "see /home/someone/lab/proposals for the format"
    assert PRIVATE.search(planted) and not GUARD.search(planted)
