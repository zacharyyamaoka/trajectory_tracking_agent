"""Lane E's tests of the ledger, the ranking, PROGRESS.md, status.json, the population and the progress chart."""

from __future__ import annotations

import importlib.util
import json

import pytest

from trajectory_tracking_agent import ledger, population
from trajectory_tracking_agent.ruler.dataset import REPO_ROOT


def _row(solution, objective, admissible, rate=1.0, split="dev", failed=None, t="2026-11-24T10:00:00-07:00"):
    return {
        "t": t, "solution": solution, "parent": None, "split": split, "ruler": "v1", "objective": objective,
        "admissible": admissible, "gate_pass_rate": rate, "failed_gates": failed or {}, "diagnostics": {},
        "wall_time_s": 1.0, "repo_commit": "abc", "proposed_by": {"agent": "pytest"}, "change": "x",
        "task_objectives": {},
    }  # fmt: skip


@pytest.fixture
def ledger_path(tmp_path):
    path = tmp_path / "ledger.jsonl"
    for row in (
        _row("a", 0.9, True),
        _row("b", 0.5, False, rate=0.9, failed={"completed": 2}),
        _row("c", 0.7, True),
        _row("d", None, False, rate=0.0, failed={g: 42 for g in ("completed", "stop_error_max_mm")}),
        _row("e", 3.0, False, rate=0.95),
        _row("a", 0.6, True, t="2026-11-24T11:00:00-07:00"),  # a's newer dev row wins
        _row("a", 0.65, True, split="holdout"),
    ):
        ledger.append(row, path)
    return path


def test_append_requires_every_contract_key(tmp_path):
    with pytest.raises(ValueError):
        ledger.append({"solution": "x"}, tmp_path / "l.jsonl")
    with pytest.raises(ValueError):  # NaN is not JSON; the evaluator writes null
        ledger.append({**_row("x", float("nan"), False)}, tmp_path / "l.jsonl")


def test_ranking_is_objectives_section_4(ledger_path):
    # admissible by objective (a 0.6 newest, c 0.7); then the rest by pass rate (e 0.95, b 0.9, d 0.0)
    assert [row["solution"] for row in ledger.ranking(ledger_path)] == ["a", "c", "e", "b", "d"]
    assert ledger.best(ledger_path)["solution"] == "a"
    board = ledger.leaderboard_rows(ledger_path)
    assert board[0]["objective_holdout"] == 0.65 and board[0]["holdout_minus_dev"] == pytest.approx(0.05)
    assert board[1]["objective_holdout"] is None


def test_progress_markdown_and_status(ledger_path, monkeypatch, tmp_path):
    text = ledger.progress_markdown(["a", "b", "c", "d", "e"], ledger_path)
    assert "**Best: `a`**" in text and "0.600 mm" in text and "Gate failure matrix" in text
    assert text.count("\n| ") >= 7 + 5  # 7 ledger rows + the matrix
    monkeypatch.setattr(ledger, "STATUS_PATH", tmp_path / "status.json")
    record = ledger.status_record(now_s=1.0, path=ledger_path)
    assert record["schema"] == "ai-team-status/1" and record["kpi"]["value"] == 0.6
    assert record["kpi"]["direction"] == "down" and record["counter_kpi"]["value"] == pytest.approx(0.05)
    json.dumps(record, allow_nan=False)


def test_no_admissible_solution_is_said_plainly(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append(_row("b", 0.5, False, rate=0.9, failed={"completed": 2}), path)
    assert ledger.best(path) is None
    assert "No admissible solution yet" in ledger.progress_markdown(["b"], path)


def test_gen0_population_is_robot_controllers_population():
    from robot_controllers.bench.population import POPULATION

    ids = population.ids_in_creation_order()
    assert sorted(ids) == sorted(cid.lower() for cid in POPULATION) or set(cid.lower() for cid in POPULATION) <= set(ids)
    for cid in POPULATION:
        meta = population.meta(cid.lower())
        assert meta["parent"] is None and meta["proposed_by"]["agent"] == "robot_controllers population (hand-written)"
        assert population.check_source(population.solution_dir(cid.lower()) / "solution.py") == []
    gen0 = [i for i in ids if i in {cid.lower() for cid in POPULATION}]
    assert gen0[0] == "p2"  # the JTC (2026-11-12) is the oldest config


def test_new_copies_the_parent_and_never_reuses_an_id(tmp_path, monkeypatch):
    monkeypatch.setattr(population, "SOLUTIONS_DIR", tmp_path)
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "solution.py").write_text("def build(trajectory, deployment):\n    return None\n")
    (tmp_path / "base" / "scorecard.json").write_text("{}")
    (tmp_path / "base" / "meta.json").write_text(json.dumps({
        "id": "base", "parent": None, "change": "c", "proposed_by": {}, "created": "2026-11-24T00:00:00Z", "tags": []}))
    folder = population.new("base+x", parent="base", change="one change", proposed_by={"agent": "pytest"})
    assert (folder / "solution.py").exists() and not (folder / "scorecard.json").exists()
    assert population.meta("base+x")["parent"] == "base"
    with pytest.raises(FileExistsError):
        population.new("base+x", parent="base", change="again")
    with pytest.raises(ValueError):
        population.new("Bad Id", parent="base", change="x")


def _chart():
    spec = importlib.util.spec_from_file_location("progress_chart", REPO_ROOT / "tools" / "progress_chart.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_progress_chart_marks_bests_failures_and_holdout():
    chart = _chart()
    points = [
        {"solution": "p2", "x": 1, "y": 1.3, "admissible": True, "new_best": True, "best_so_far": 1.3, "failed": {}},
        {"solution": "p8", "x": 2, "y": 40.0, "admissible": False, "new_best": False, "best_so_far": 1.3,
         "failed": {"completed": 3, "saturation_share_pct": 2}},
        {"solution": "p3", "x": 3, "y": 1.5, "admissible": True, "new_best": False, "best_so_far": 1.3, "failed": {}},
        {"solution": "p4", "x": 4, "y": 0.8, "admissible": True, "new_best": True, "best_so_far": 0.8, "failed": {}},
        {"solution": "p9", "x": 5, "y": None, "admissible": False, "new_best": False, "best_so_far": 0.8,
         "failed": {"completed": 42}},
    ]  # fmt: skip
    svg = chart.render_svg(points, {"solution": "p4", "dev": 0.8, "holdout": 0.9, "x": 4})
    assert svg.startswith("<svg") and len(svg.encode()) < 60_000
    assert "log" in svg  # 40 / 0.8 > 20: a log axis
    assert svg.count(f'fill="{chart.GREEN}"') >= 2 and svg.count(f'stroke="{chart.RED}"') >= 2
    assert "2 gates failed (completed on 3 tasks, saturation_share_pct on 2 tasks)" in svg
    assert "holdout" in svg and chart.ORANGE in svg and "@import" not in svg and "<script" not in svg
    empty = chart.render_svg([], None)
    assert "No solutions scored yet" in empty
