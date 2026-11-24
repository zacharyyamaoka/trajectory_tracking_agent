"""A "new best" on the progress chart beats the previous best by more than float rounding (2026-11-24)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "progress_chart.py"


def _chart():
    spec = importlib.util.spec_from_file_location("tta_progress_chart_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_exact_merge_is_not_a_new_best(monkeypatch) -> None:
    from trajectory_tracking_agent import ledger, population

    rows = {
        "a": {"solution": "a", "objective": 1.0, "admissible": True},
        "b": {"solution": "b", "objective": 0.5, "admissible": True},
        "b-merged": {"solution": "b-merged", "objective": 0.5 - 1e-14, "admissible": True},  # same commands, re-expressed
        "c": {"solution": "c", "objective": 0.4, "admissible": True},
    }
    monkeypatch.setattr(ledger, "latest", lambda split, *a, **k: rows if split == "dev" else {})
    monkeypatch.setattr(ledger, "best", lambda *a, **k: rows["c"])
    monkeypatch.setattr(population, "ids_in_creation_order", lambda *a, **k: list(rows))
    chart = _chart()
    monkeypatch.setattr(chart, "ablation_ids", lambda *a, **k: [])
    points, _ = chart.chart_points()
    assert [p["solution"] for p in points if p["new_best"]] == ["a", "b", "c"]
