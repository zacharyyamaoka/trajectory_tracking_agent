"""What the search found keeps holding on today's code: the secant velocity and the calibrated lookahead.

WHY (Zach, 2026-11-24; feedback/2026-11-24-the-secant-lookahead-find.md): the find he called out was the secant
lookahead. A find is a claim, so it is re-checked live, never read back from the ledger: each pair below is scored
again by the ruler now (dev, nothing written), and the find holds only if it still wins. A change in robot_controllers
or the deployment that quietly undid it turns this red. Each pair differs in that one ingredient only (meta.json's
tags, checked first), so the gap is the ingredient's own.

Ranked by the objective (OBJECTIVES §4: the median over the dev tasks of tool_track_rms_mm); no number is restated here.
"""

from __future__ import annotations

from functools import cache

import pytest

from trajectory_tracking_agent import population
from trajectory_tracking_agent.evaluate import evaluate

# Generation 0's twins: the same feed-forward, feedback and lookahead, tangent vs secant velocity (interp=).
SECANT_PAIRS = [("p2", "p2s"), ("p3", "p3s"), ("p4", "p4s"), ("p5", "p5s"), ("p6", "p6s"), ("p7", "p7s")]
# The same layout and secant velocity, the datasheet's lookahead vs the one calibrated from one run (lookahead=).
LOOKAHEAD_PAIR = ("p3s", "p4s")


def _tags(solution: str) -> dict[str, str]:
    return dict(tag.split("=", 1) for tag in population.meta(solution)["tags"] if "=" in tag)


@cache
def _objective(solution: str) -> float:
    # WHY one worker: four hold about 1.4 GB each, past the agent pool's memory ceiling on a busy night (2026-11-25:
    # the OOM killer ended them); one process scores the same, bit for bit, and only slower.
    scorecard = evaluate(solution, split="dev", workers=1, write=False, records=False)
    assert scorecard["admissible"] is True, f"{solution} is no longer admissible"
    return scorecard["objective"]


def _differ_only_in(left: str, right: str, key: str) -> None:
    a, b = _tags(left), _tags(right)
    assert a[key] != b[key], (left, right, key)
    assert {k: v for k, v in a.items() if k != key} == {k: v for k, v in b.items() if k != key}, (left, right)


@pytest.mark.parametrize(("tangent", "secant"), SECANT_PAIRS)
def test_the_secant_velocity_still_beats_the_tangent(tangent: str, secant: str) -> None:
    _differ_only_in(tangent, secant, "interp")
    assert _tags(secant)["interp"] == "secant_mid_ff"
    assert _objective(secant) < _objective(tangent), (secant, _objective(secant), tangent, _objective(tangent))


def test_the_calibrated_lookahead_still_beats_the_datasheets() -> None:
    nominal, calibrated = LOOKAHEAD_PAIR
    _differ_only_in(nominal, calibrated, "lookahead")
    assert (_tags(nominal)["lookahead"], _tags(calibrated)["lookahead"]) == ("nominal", "calibrated")
    assert _objective(calibrated) < _objective(nominal), (_objective(calibrated), _objective(nominal))
