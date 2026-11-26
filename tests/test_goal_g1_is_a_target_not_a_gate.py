"""Goal G1 states performance targets with Zach's three-hour deadline, never gate language (Zach, /rate bad
2026-11-25 7:27 PM, Settings/Feedback/rate/rate - Nov 25 2026, 7.27.33PM.md).

Asked to set 0.5 mm worst-stop and 1.0 mm full-trajectory RMS as UR5e goals and pursue them for three hours, Codex
wrote them as "strict per-run requirements" ("must", "One failing run leaves the goal open") with a provisional
date nine days out. A goal is the outcome to reach. The frozen ruler alone decides admissibility. Red on 2103826,
green from bb5ff52.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

GOAL = Path(__file__).resolve().parent.parent / "goals" / "G1-ur5e-tracking-at-every-speed.md"


def _split() -> tuple[str, str]:
    _, front, body = GOAL.read_text().split("---", 2)
    return front, " ".join(body.split())


def _field(front: str, key: str) -> str:
    return re.search(rf"^{key}:\s*(.+)$", front, re.M).group(1).strip()


def test_the_targets_are_his_two_numbers():
    front, _ = _split()
    assert "kpi:ur5e_worst_stop_error_mm < 0.5" in front
    assert "kpi:ur5e_worst_full_trajectory_rms_mm < 1.0" in front


def test_the_deadline_is_three_hours_after_it_was_set():
    front, body = _split()
    target = datetime.fromisoformat(_field(front, "vibe-target"))
    set_at = datetime.fromisoformat(_field(front, "set"))
    assert target - set_at == timedelta(hours=3), (set_at, target)
    assert "provisional" not in body.lower()


def test_targets_are_framed_as_goals_and_the_ruler_keeps_admissibility():
    _, body = _split()
    lowered = body.lower()
    assert "performance targets" in lowered
    assert "ruler determines admissibility" in lowered
    for gate_word in ("must have", "strict", "requirement", "one failing run"):
        assert gate_word not in lowered, f"gate language in the goal: {gate_word!r}"
