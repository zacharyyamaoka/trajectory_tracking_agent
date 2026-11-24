"""Ablation variants never count as search progress in the ledger's best, PROGRESS.md or status.json (2026-11-24)."""

from __future__ import annotations

from trajectory_tracking_agent import ledger


def test_best_and_counts_leave_ablations_out(monkeypatch) -> None:
    rows = {
        "a": {"solution": "a", "objective": 1.0, "admissible": True, "gate_pass_rate": 100.0},
        "abl-x": {"solution": "abl-x", "objective": 0.1, "admissible": True, "gate_pass_rate": 100.0},
        "b": {"solution": "b", "objective": 0.5, "admissible": False, "gate_pass_rate": 90.0},
    }
    monkeypatch.setattr(ledger, "latest", lambda split, *a, **k: rows if split == "dev" else {})
    monkeypatch.setattr(ledger, "ablation_ids", lambda: {"abl-x"})
    assert ledger.best()["solution"] == "a"
    assert ledger.best(include_ablations=True)["solution"] == "abl-x"
    assert set(ledger.searched(rows)) == {"a", "b"}


def test_the_real_progress_counts_no_ablation() -> None:
    text = (ledger.PROGRESS_PATH).read_text()
    assert "of 64 scored" not in text and "61 of" not in text, "PROGRESS.md counts ablation variants"
