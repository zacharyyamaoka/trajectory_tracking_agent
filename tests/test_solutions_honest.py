"""Every solution learns about the robot only through the boundary (OBJECTIVES §1, "What a solution may know").

A source check, not a proof: it catches the direct routes to the simulator's truth. The dispatcher also reads each
agent-written solution's diff.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# WHY every .py, not only solution.py (2026-11-24): gen-1 solutions identify models with helper scripts beside
# solution.py (identify_pass.py, merge_stack.py); a route to the truth there is the same leak.
SOLUTIONS = sorted(p for p in (Path(__file__).resolve().parents[1] / "solutions").glob("*/*.py"))

# WHY these: each one hands a solution the plant's truth or a model better than the deployment gives (2026-11-24).
FORBIDDEN = {
    "the plant's truth record": r"\bUR5E_TRUTH\b|\bUr5eTruth\b",
    "the truth plant itself": r"\.plant\(|\bUr5ePlant\b|\bur5e_plant\(",
    "the plant's MuJoCo model": r"\bload_model\(|\b_plant_model\(|\bMODEL_PATH\b|ur5e_bare\.xml",
    "a model with less error than given": r"ModelError\(\s*(0(\.0*)?\s*[,)]|scale\s*=\s*0(\.0*)?\b)",
    "the ruler (peeking at the scorer)": r"trajectory_tracking_agent\.ruler|from\s+\.\.?ruler|import\s+ruler\b",
    "the holdout split": r"holdout",
}


def test_there_are_solutions() -> None:
    assert SOLUTIONS, "no solutions/*/solution.py found"


@pytest.mark.parametrize("path", SOLUTIONS, ids=lambda p: f"{p.parent.name}/{p.name}")
@pytest.mark.parametrize("what", sorted(FORBIDDEN))
def test_solution_does_not_use(path: Path, what: str) -> None:
    source = path.read_text()
    hits = [m.group(0) for m in re.finditer(FORBIDDEN[what], source)]
    assert not hits, f"{path.parent.name}/{path.name} uses {what}: {hits}"
