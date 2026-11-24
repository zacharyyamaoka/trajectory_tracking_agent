"""Same solution, same task -> the same score, bit for bit, even with a cold calibration (2026-11-24).

WHY: a calibrated solution's score once moved ~2 % with the machine's load (robot_controllers' simulated bus
calibration added the host's CPU time; fixed upstream in robot_controllers f25f485). Noise that size is as big as the
gap between the top solutions, so a search would chase it. This test fails if any host-dependent noise comes back,
in the episode or in a solution's own build().
"""

from __future__ import annotations

import pytest

from trajectory_tracking_agent.evaluate import run_task

KEYS = ("tool_track_rms_mm", "stop_error_max_mm", "saturation_share_pct")


def _cold_run(solution_id: str) -> dict:
    from robot_controllers.bench import population

    population.scenario_calibration.cache_clear()
    row = run_task(solution_id, "workspace-dev-002")
    return {key: row["kpis"].get(key) for key in KEYS} | {"objective": row["objective"]}


@pytest.mark.parametrize("solution_id", ["p4s", "p6s"])
def test_two_cold_runs_score_identically(solution_id: str) -> None:
    first, second = _cold_run(solution_id), _cold_run(solution_id)
    assert all(value is not None for value in first.values()), first
    assert first == second
