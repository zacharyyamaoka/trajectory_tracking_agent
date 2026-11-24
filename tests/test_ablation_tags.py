"""Ablation variants (meta.json tag `ablation`) are never read as search progress: the progress chart and the three
population views leave them out and say how many they left out (Zach, 2026-11-24: an ablation study measures what a
finished line's parts were worth; its variants are not search steps)."""

from __future__ import annotations

import importlib.util
import json
import shutil

import pytest

from trajectory_tracking_agent import ledger, population
from trajectory_tracking_agent.ruler.dataset import REPO_ROOT


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(f"ablation_test_{name}", REPO_ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(solution, objective, parent=None, split="dev"):
    return {"t": "2026-11-24T10:00:00-07:00", "solution": solution, "parent": parent, "split": split, "ruler": "v1",
            "objective": objective, "admissible": True, "gate_pass_rate": 1.0, "failed_gates": {}, "diagnostics": {},
            "wall_time_s": 1.0, "repo_commit": "abc", "proposed_by": {}, "change": f"{solution}'s change",
            "task_objectives": {"workspace-dev-000": objective}}  # fmt: skip


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """root (1.0) -> line (0.5, the search's best); line -> abl-no-x (0.9) and abl-lucky (0.2, better than the best),
    both tagged ablation; then later (0.4), a real search step created after the ablations."""
    plan = [("root", 1.0, None, []), ("line", 0.5, "root", []),
            ("abl-no-x", 0.9, "line", ["ablation", "study:demo"]), ("abl-lucky", 0.2, "line", ["ablation", "study:demo"]),
            ("later", 0.4, "line", [])]  # fmt: skip
    solutions = tmp_path / "solutions"
    rows = []
    for k, (solution, objective, parent, tags) in enumerate(plan):
        folder = solutions / solution
        folder.mkdir(parents=True)
        (folder / "meta.json").write_text(json.dumps({
            "id": solution, "parent": parent, "change": "c", "proposed_by": {}, "tags": tags,
            "created": f"2026-11-24T08:{k:02d}:00-07:00"}))  # fmt: skip
        rows.append(_row(solution, objective, parent))
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(population, "SOLUTIONS_DIR", solutions)
    real_latest = ledger.latest  # ranking() and best() read through latest(): one patch moves all three
    monkeypatch.setattr(ledger, "latest", lambda split="dev", path=None: real_latest(split, ledger_path))
    return {"solutions": solutions, "ledger": ledger_path, "tasks": tmp_path / "no-tasks.jsonl"}


def test_progress_chart_leaves_ablations_out_and_counts_them(repo):
    chart = _tool("progress_chart")
    assert chart.ablation_ids() == ["abl-no-x", "abl-lucky"]
    points, pair = chart.chart_points()
    assert [p["solution"] for p in points] == ["root", "line", "later"]
    assert [p["x"] for p in points] == [1, 2, 3]  # numbered without gaps: an ablation takes no search number
    assert points[-1]["new_best"] and points[-1]["best_so_far"] == 0.4  # abl-lucky's 0.2 is not the best so far
    assert pair is None  # no holdout rows here, and never an ablation's
    svg = chart.render_svg(points, pair, ablations=len(chart.ablation_ids()))
    assert "+2 ablation variants not shown" in svg and "abl-lucky" not in svg
    assert "ablation" not in chart.render_svg(points, pair)  # no ablations: nothing said


def test_population_views_leave_ablations_out_of_every_view(repo):
    views = _tool("population_views")
    pop = views.load(repo["ledger"], repo["tasks"], repo["solutions"])
    assert set(pop.dev) == {"root", "line", "later"} and pop.order == ["root", "line", "later"]
    assert pop.ablations == ["abl-lucky", "abl-no-x"]
    assert pop.best() == "later"
    model = views.lineage_model(pop)
    assert model["children"]["line"] == ["later"] and model["path_to_best"] == ["root", "line", "later"]
    gates = views.render_gates(pop)
    assert "abl-" not in gates
    if shutil.which("dot"):
        lineage = views.render_lineage(pop)
        assert "2 ablation variants not shown" in lineage and "abl-lucky" not in lineage
