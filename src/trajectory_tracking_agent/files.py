"""Writing a file the next step reads, so a run killed part-way never leaves half of one.

    files.write_text(path, text)    # the old file or the new one, never a torn mix

WHY (Zach, 2026-11-24: the search should run through the night unattended; feedback/2026-11-24-runs-overnight.md):
a scorecard, run record, PROGRESS.md or status.json cut off half-way by a crash, the OOM killer or a power cut is
read by the next step (the leaderboard, the site build) and stops it. The text goes to a temporary file beside the
target, is flushed to disk, then renamed over it; a rename is atomic on one filesystem. The ledger is appended, not
replaced, so it has its own guard (`ledger.append`).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

__all__ = ["write_text"]


def write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise
