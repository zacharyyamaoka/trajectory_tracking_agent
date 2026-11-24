"""Every agent-written solution says which agent and model proposed it (Zach's provenance rule, 2026-11-24)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SOLUTIONS = sorted(p.parent for p in (Path(__file__).resolve().parents[1] / "solutions").glob("*/meta.json"))


@pytest.mark.parametrize("folder", SOLUTIONS, ids=lambda p: p.name)
def test_proposer_is_recorded(folder: Path) -> None:
    meta = json.loads((folder / "meta.json").read_text())
    proposed_by = meta.get("proposed_by") or {}
    assert proposed_by.get("agent"), f"{folder.name}: meta.json proposed_by.agent is empty"
    if "gen-0" not in (meta.get("tags") or []):  # gen 0 is robot_controllers' hand-written population: no model
        assert proposed_by.get("model"), f"{folder.name}: meta.json proposed_by.model is empty"
