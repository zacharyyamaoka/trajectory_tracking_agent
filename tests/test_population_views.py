"""Lane V's tests of the population views (tools/population_views.py): lineage, gates and specialists, drawn from the
ledger's metrics out + provenance only, never from a solution's code."""

from __future__ import annotations

import builtins
import importlib.util
import io
import json
import math
import pathlib
import random
import re
import shutil
import xml.etree.ElementTree as ET

import pytest

from trajectory_tracking_agent import ledger
from trajectory_tracking_agent.ruler.dataset import REPO_ROOT

spec = importlib.util.spec_from_file_location("population_views", REPO_ROOT / "tools" / "population_views.py")
pv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pv)

needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz dot is not installed")

TASKS = [  # (task_id, kind): six dev tasks over four kinds, one holdout task the views must ignore
    ("workspace-dev-000", "a_to_b_joint"), ("workspace-dev-001", "a_to_b_joint"), ("workspace-dev-002", "a_to_b_joint"),
    ("workspace-dev-003", "a_to_b_line"), ("workspace-dev-004", "via_points"), ("workspace-dev-005", "iso9283_path"),
]  # fmt: skip
IDS = [t for t, _ in TASKS]


def _row(solution, objective, admissible, parent=None, failed=None, tasks=None, split="dev", t="2026-11-24T10:00:00-07:00"):
    return {
        "t": t, "solution": solution, "parent": parent, "split": split, "ruler": "v1", "objective": objective,
        "admissible": admissible, "gate_pass_rate": 1.0 if admissible else 0.5,
        "failed_gates": {g: (failed or {}).get(g, 0) for g in pv.GATES}, "diagnostics": {}, "wall_time_s": 1.0,
        "repo_commit": "abc", "proposed_by": {"agent": "pytest"}, "change": f"{solution}'s change",
        **({} if tasks is None else {"task_objectives": dict(zip(IDS, tasks))}),
    }  # fmt: skip


@pytest.fixture
def world(tmp_path):
    """A ledger with lineage (r1 → a → b, the best; r1 → c and a → d, dead ends), a NaN objective (r2), a row without
    task_objectives (e, backfilled from its scorecard), a parent never scored (ghost), a superseded row and a holdout
    row; every solution.py made unreadable."""
    rows = [
        _row("r1", 5.0, False, failed={"completed": 6}, tasks=[5] * 6, t="2026-11-24T09:00:00-07:00"),  # superseded
        _row("r1", 1.0, True, tasks=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
        _row("r2", float("nan"), False, failed={"completed": 6, "stop_error_max_mm": 2}, tasks=[None] * 6),
        _row("a", 0.8, True, parent="r1", tasks=[0.5, 0.9, 0.8, 0.8, 0.8, 0.8]),
        _row("b", 0.7, True, parent="a", tasks=[0.6, 0.7, 0.7, 0.7, 0.7, 0.7]),
        _row("c", 1.2, True, parent="r1", tasks=[1.2] * 6),
        _row("d", 0.5, False, parent="a", failed={"saturation_share_pct": 3}, tasks=[0.1] * 6),
        _row("e", 0.9, True, parent="r2"),  # no task_objectives: an older row
        _row("f", 0.95, True, parent="ghost", tasks=[0.95] * 6),
        _row("b", 0.75, True, split="holdout", tasks=[0.75] * 6),
    ]
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text("".join(json.dumps(r) + "\n" for r in rows))  # NaN as the JSON literal, as a raw writer would
    tasks_path = tmp_path / "tasks.jsonl"
    tasks_path.write_text("".join(json.dumps({"task_id": t, "kind": k, "split": "dev", "keyposes": []}) + "\n" for t, k in TASKS)
                          + json.dumps({"task_id": "workspace-holdout-000", "kind": "via_points", "split": "holdout"}) + "\n")
    solutions = tmp_path / "solutions"
    for k, solution in enumerate(["r1", "r2", "a", "b", "c", "d", "e", "f"]):
        folder = solutions / solution
        folder.mkdir(parents=True)
        (folder / "meta.json").write_text(json.dumps({"id": solution, "created": f"2026-11-24T08:{k:02d}:00-07:00"}))
        code = folder / "solution.py"
        code.write_text("raise SystemExit('a view read the inside of the black box')\n")
        code.chmod(0)
    (solutions / "e" / "scorecard.json").write_text(json.dumps({
        "ruler": "v1", "solution": "e", "split": "dev",
        "tasks": [{"task": t, "objective": v} for t, v in zip(IDS, [0.9, 0.9, 0.9, 0.9, 0.3, 0.9])]}))  # fmt: skip
    yield {"ledger": ledger_path, "tasks": tasks_path, "solutions": solutions, "out": tmp_path / "views"}
    for code in solutions.glob("*/solution.py"):
        code.chmod(0o644)


def _population(world):
    return pv.load(world["ledger"], world["tasks"], world["solutions"])


@pytest.fixture
def no_solution_code(monkeypatch):
    """Every way of opening a file raises on a solution.py (the views read metrics out and provenance only)."""
    attempts = []

    def guard(path):
        if str(path).endswith("solution.py"):
            attempts.append(str(path))
            raise PermissionError(f"a population view opened {path}")

    real_open, real_read_text, real_read_bytes, real_path_open = builtins.open, pathlib.Path.read_text, \
        pathlib.Path.read_bytes, pathlib.Path.open  # fmt: skip

    def open_(file, *args, **kwargs):
        guard(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_)
    monkeypatch.setattr(io, "open", open_)
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, *a, **k: (guard(self), real_read_text(self, *a, **k))[1])
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self, *a, **k: (guard(self), real_read_bytes(self, *a, **k))[1])
    monkeypatch.setattr(pathlib.Path, "open", lambda self, *a, **k: (guard(self), real_path_open(self, *a, **k))[1])
    return attempts


def test_newest_row_per_solution_split_and_ruler(world):
    population = _population(world)
    assert population.dev["r1"]["objective"] == 1.0 and population.admissible("r1")  # the superseded 5.0 is gone
    assert set(population.dev) == {"r1", "r2", "a", "b", "c", "d", "e", "f"}  # the holdout row is not a dev row
    assert population.objective("r2") is None and not population.admissible("r2")  # NaN fails closed
    assert population.best() == "b"  # d's 0.5 is not admissible
    assert population.order[:3] == ["r1", "r2", "a"] and population.number("b") == 4
    assert [t for t, _ in population.tasks] == IDS


def test_lineage_path_to_best_dead_ends_and_placeholders(world):
    model = pv.lineage_model(_population(world))
    assert model["best"] == "b"
    assert model["path_to_best"] == ["r1", "a", "b"]
    assert model["dead_ends"] == ["c", "d"]  # c is worse than r1, d is not admissible; neither has children
    assert model["placeholders"] == ["ghost"]
    assert model["roots"] == ["r1", "r2", "ghost"]  # creation order of each tree's first member
    assert model["children"]["r1"] == ["a", "c"] and model["children"]["r2"] == ["e"]


def test_the_path_follows_the_current_best(world):
    """A better solution in another tree moves the thick path there."""
    with open(world["ledger"], "a") as handle:
        handle.write(json.dumps(_row("e2", 0.6, True, parent="e", tasks=[0.6] * 6)) + "\n")
    model = pv.lineage_model(_population(world))
    assert model["best"] == "e2" and model["path_to_best"] == ["r2", "e", "e2"]


@needs_dot
def test_lineage_svg_marks_the_path_deltas_and_rejects(world):
    svg = pv.render_lineage(_population(world))
    ET.fromstring(svg)
    assert svg.count('class="edge path"') == 2  # r1 → a → b
    assert 'class="node best path"' in svg and 'class="node path"' in svg
    assert "−0.200" in svg and "−0.100" in svg  # Δ on r1 → a and a → b
    assert 'stroke="#d62728"' in svg  # the not-admissible outlines
    assert "not scored" in svg and "dead end" in svg
    assert re.search(r">r2</text>\s*<text[^>]*>— ✗CS</text>", svg)  # NaN: no number, the failed gates' initials


def test_gates_view_counts_and_nan(world):
    population = _population(world)
    rows = {r["solution"]: r for r in pv.gates_model(population)}
    assert rows["r2"]["counts"]["completed"] == 6 and rows["r2"]["counts"]["stop_error_max_mm"] == 2
    assert rows["r2"]["objective"] is None and rows["d"]["counts"]["saturation_share_pct"] == 3
    svg = pv.render_gates(population)
    ET.fromstring(svg)
    assert "Gates on dev" in svg and "no objective" in svg and "6 dev tasks" in svg
    assert "r2: completed fails on 6 of 6 dev tasks" in svg


def test_specialists_backfill_winners_and_ratios(world):
    population = _population(world)
    assert population.backfilled == ["e"]  # from solutions/e/scorecard.json, never from code
    model = pv.specialists_model(population)
    assert "d" not in model["pool"] and "r2" not in model["pool"]  # admissible only
    assert model["winner"]["workspace-dev-004"] == "e"  # the backfilled niche winner
    assert model["winner"]["workspace-dev-000"] == "a" and model["winner"]["workspace-dev-001"] == "b"
    assert model["ratios"]["b"]["workspace-dev-004"] == pytest.approx(0.7 / 0.3)
    assert model["wins"] == {"a": 1, "b": 4, "e": 1} and model["distinct_winners"] == 3
    assert model["rows"][0] == "b" and set(model["rows"]) >= {"a", "b", "e"}
    svg = pv.render_specialists(population)
    ET.fromstring(svg)
    assert "3 distinct per-task winners among 6 admissible" in svg
    assert "joint A→B" in svg and "ISO" in svg


def test_specialists_cap_keeps_every_winner(world):
    population = _population(world)
    model = pv.specialists_model(population, k=2)
    assert model["rows"] == ["b", "a"]  # k=2 keeps the two biggest winners, in objective order


def test_views_never_read_solution_code(world, no_solution_code):
    written, summary = pv.write_views(world["out"], world["ledger"], world["tasks"], world["solutions"])
    assert not no_solution_code
    names = {p.name for p in written}
    assert {"gates.svg", "specialists.svg"} <= names
    assert ("lineage.svg" in names) == (shutil.which("dot") is not None)
    for path in written:
        ET.parse(path)
        assert path.stat().st_size < pv.SIZE_LIMIT_BYTES
        assert "/home/" not in path.read_text()
    assert summary["best"] == "b" and summary["distinct_winners"] == 3 and summary["niche_winners"][0] == ("b", 4)


def test_the_real_ledger_builds_without_reading_code(tmp_path, no_solution_code):
    written, summary = pv.write_views(tmp_path)
    assert not no_solution_code and written
    for path in written:
        ET.parse(path)
        assert path.stat().st_size < pv.SIZE_LIMIT_BYTES


@needs_dot
def test_lineage_stays_under_the_size_limit_at_150_solutions(tmp_path):
    rng = random.Random(3)
    rows, objective = [], {}
    for n in range(150):
        solution = f"s{n}"
        parent = None if n < 16 else (min(objective, key=objective.get) if rng.random() < 0.5 else rng.choice(list(objective)))
        value = (objective[parent] if parent else rng.uniform(0.8, 2.0)) * rng.lognormvariate(0.02, 0.1)
        objective[solution] = value
        row = _row(solution, value, rng.random() > 0.15, parent=parent, tasks=[value] * 6, t=f"2026-11-24T{n // 60 + 10}:{n % 60:02d}:00Z")
        row["change"] = "x" * 200  # a long claim: cut at 140 in the tooltip
        rows.append(row)
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    population = pv.load(path, tmp_path / "missing.jsonl", tmp_path / "none", order=[r["solution"] for r in rows])
    svg = pv.render_lineage(population)
    ET.fromstring(svg)
    width = float(re.search(r'width="([\d.]+)"', svg).group(1))
    assert len(svg.encode()) < pv.SIZE_LIMIT_BYTES and width <= 1600
    assert "x" * 139 + "…" in svg and "x" * 141 not in svg


def test_progress_markdown_embeds_the_population(world):
    order = ["r1", "r2", "a", "b", "c", "d", "e", "f"]
    _, summary = pv.write_views(world["out"], world["ledger"], world["tasks"], world["solutions"])
    text = ledger.progress_markdown(order, world["ledger"], population=summary)
    assert "## Population" in text
    for name in ("lineage", "gates", "specialists"):
        assert f"](site/views/{name}.svg)" in text
    assert "`b` 4" in text and "3 distinct" in text
    plain = ledger.progress_markdown(order, world["ledger"])  # without numbers: the images alone
    assert "## Population" in plain and "](site/views/gates.svg)" in plain


def test_colour_scales_are_monotone():
    blues = [pv._luminance(pv.ratio_colour(r)) for r in (1.0, 1.2, 1.5, 2.0, 3.0, 5.0)]
    assert blues == sorted(blues) and blues[-1] == blues[-2]  # capped at 3x
    assert pv.ink_on(pv.BLUES[0]) == "#ffffff" and pv.ink_on(pv.BLUES[-1]) == "#111111"
    assert math.isclose(pv._luminance("#ffffff"), 1.0)

