"""OBJECTIVES.md defines ruler v1 and is frozen: its bytes never change in place.

WHY (2026-11-25): blackbox check exempts a doc whose sha256 the box records in a tracked file, so the ruler's
definition gains no links and no edits; a change is a new ruler version and a new pin here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OBJECTIVES_SHA256 = "885bfb5693ba30313c4578adaf20670aef4e79a395ba01dc8f53ef878febb270"


def test_objectives_md_is_the_frozen_ruler_v1():
    assert hashlib.sha256((REPO / "OBJECTIVES.md").read_bytes()).hexdigest() == OBJECTIVES_SHA256
