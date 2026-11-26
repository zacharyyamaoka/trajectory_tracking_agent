"""The Trajectory Comparison and Model × Dataset pages (site/comparison/, site/models-datasets/, site/nav.*), written by
tools/build_dropins.py. These read the committed files against their sources; the number checks recompute from the
scorecards and the ruler's own functions, never from the build's code. `tools/shoot_dropins.py` drives the pages in
headless Chromium.

The one relation that is not an equality, said exactly: traj_compare's tool error e(t) = |target − run| at each of the
run's samples (robot_msgs.compare) is the ruler's per-sample tool error (both are the distance between the target and the
measured tool point at the same instant). The ruler's per-task number is the RMS of e over the samples where the target
moves (`ruler.metrics.moving_mask`). The build hands traj_compare that mask (`Comparison(stats_mask=)`), so its own
position RMS (`error_metrics["position"]["rms"]`, the number its hovers and tables use) is taken over the same samples
and is the scorecard's number; its plots still draw every sample, rests included.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
COMPARISON = SITE / "comparison"
MXD = SITE / "models-datasets"
REBUILD = "uv run --all-extras python tools/build_dropins.py build"
# WHY 1e-3 mm: the saved record keeps the tool point to 1 um and traj_compare writes the error to 1 um, so the ruler's
# RMS re-taken on the report's series agrees to ~1e-5 mm; 1e-3 mm is far below the 3 digits a page shows (the same
# tolerance as tools/build_site.py's CHECK_TOLERANCE_MM)
TOLERANCE_MM = 1e-3

pytestmark = pytest.mark.skipif(not (COMPARISON / "index.html").exists(), reason="site/comparison not built")


def _build():
    spec = importlib.util.spec_from_file_location("build_dropins", REPO / "tools" / "build_dropins.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path):
    return json.loads(path.read_text())


def _payload(page: Path, element_id: str) -> dict:
    match = re.search(rf'id="{element_id}">(.*?)</script>', page.read_text(), re.S)
    return json.loads(match.group(1).replace("<\\/", "</"))


def _runs_index() -> dict:
    return _json(SITE / "data" / "runs" / "index.json")


def _full() -> list[str]:
    full = _runs_index()["rule"]["full"]
    return [sid for sid in dict.fromkeys([full["best"], full["gen0_best"]]) if sid]


def _card(sid: str) -> dict:
    return _json(REPO / "solutions" / sid / "scorecard.json")


def _rows(sid: str) -> dict:
    return {row["task"]: row for row in _card(sid)["tasks"]}


def _tasks() -> list[str]:
    return [task["id"] for task in _runs_index()["tasks"]]


SCORECARDS = {"dev": "scorecard.json", "holdout": "scorecard_holdout.json"}


def _mxd_rows() -> list[dict]:
    """site/models-datasets/models-datasets.csv, typed by its own sidecar the way data-ui types it (read here with the
    csv module, not the build's reader)."""
    schema = _json(MXD / "models-datasets.schema.json")
    kinds = {f["name"]: f["type"] for f in schema["schema"]["fields"]}
    cast = {"number": float, "integer": int, "boolean": lambda t: t == "true"}
    with (MXD / "models-datasets.csv").open(newline="", encoding="utf-8") as handle:
        return [{k: (None if v == "" else cast.get(kinds[k], str)(v)) for k, v in row.items()}
                for row in csv.DictReader(handle)]


RULER = "ruler v1"  # the ranked rows (solutions/*/scorecard*.json); every other row is off-ruler evidence


def _ruler_rows() -> list[dict]:
    return [row for row in _mxd_rows() if row["ruler"] == RULER]


def _split_card(sid: str, split: str) -> dict:
    return _json(REPO / "solutions" / sid / SCORECARDS[split])


def _views(base_text: str) -> list[tuple[str, str]]:
    """(type, name) of each view in a .base, in order."""
    return re.findall(r"^  - type: (\w+)\n    name: (.+)$", base_text, re.M)


def test_the_pages_are_current():
    """The committed pages are the build of today's sources: the solutions the landing page ships on every task, the 42
    dev tasks, and one Model × Dataset row per scored solution × task. A new best or a new scorecard makes this red."""
    build = _json(COMPARISON / "build.json")
    assert [s["id"] for s in build["solutions"]] == _full(), f"stale: {REBUILD}"
    assert build["tasks"] == _tasks(), f"stale: {REBUILD}"
    rows = _ruler_rows()
    for split, name in SCORECARDS.items():
        scored = sorted(p.parent.name for p in (REPO / "solutions").glob(f"*/{name}"))
        assert sorted({row["solution"] for row in rows if row["split"] == split}) == scored, f"stale: {REBUILD}"
        tasks = sum(len(_json(REPO / "solutions" / sid / name)["tasks"]) for sid in scored)
        assert sum(1 for row in rows if row["split"] == split) == tasks, f"stale: {REBUILD}"
    assert not (MXD / "cells.json").exists(), "the stock-pivot data file is retired"


@pytest.mark.parametrize("sid", ["best", "gen0_best"])
def test_report_tool_rms_is_the_scorecards(sid):
    """For every dev task, in the run report: the statistics table shows the scorecard's per-task tool_track_rms_mm;
    traj_compare's own tool error series, restricted to the ruler's moving samples, re-takes that number (the oracle:
    the ruler's moving_mask over the target tape and the deployment's tool point, both read here, not from the build);
    and traj_compare's own position RMS, the number its tables and hovers show, IS that number: its stats mask is the
    ruler's moving samples, sample for sample in count. Run for the best and the best of generation 0."""
    import trajectory_tracking_agent as tta
    from robot_msgs import load_npz
    from trajectory_tracking_agent.ruler.metrics import moving_mask

    solution = _runs_index()["rule"]["full"][sid]
    rows = _rows(solution)
    dep = tta.deployment("ur5e_alone")
    worst = 0.0
    for task in _tasks():
        payload = _payload(COMPARISON / "runs" / task / "report.html", "traj-compare-data")
        comparison = payload["comparisons"][0]
        scored = rows[task]["objective"]
        table = {row["cells"][0].split(" ")[0]: row["cells"] for row in comparison["statistics"]["rows"]}
        assert table[solution][1] == f"{scored:.4g} mm", (task, table[solution])
        tape = load_npz(REPO / "datasets" / "ur5e_alone" / "workspace" / "v2" / "tapes" / f"{task}.npz")
        moving = moving_mask(tape.t, dep.tool_position(tape.positions), tape.velocities)
        plot_t = np.asarray(comparison["plot_t"], dtype=float)
        assert np.allclose(plot_t, tape.t, rtol=0.0, atol=1e-9), "the report's grid is the target's"
        situation = next(s for s in comparison["situations"] if s["name"] == solution)
        error_m = np.asarray([np.nan if v is None else v for v in situation["plot"]["xyz_mag"]], dtype=float)
        assert np.isfinite(error_m).all(), task
        ruler_mm = math.sqrt(np.mean(error_m[moving] ** 2)) * 1e3
        assert abs(ruler_mm - scored) <= TOLERANCE_MM, (task, ruler_mm, scored)
        worst = max(worst, abs(ruler_mm - scored))
        assert comparison["stats_mask"] == {"label": "moving samples", "n": int(moving.sum()), "of": int(moving.size)}
        position = situation["error_metrics"]["position"]
        assert position["n"] == int(moving.sum()), (task, position["n"])
        own_mm = position["rms"] * 1e3
        assert abs(own_mm - scored) <= TOLERANCE_MM, (task, own_mm, scored)
        worst = max(worst, abs(own_mm - scored))
    assert worst < TOLERANCE_MM


def test_league_is_the_objective():
    """The dataset level's league: each solution's median over the 42 tasks is its scorecard objective, float for float;
    each task kind's median is the median of the scorecard's per-task numbers of that kind; the run tags the league
    scores are the scorecard rows' numbers, and their medians are the scorecard's diagnostics."""
    payload = _payload(COMPARISON / "index.html", "traj-compare-dataset")
    facets = {facet["value"]: {c["name"]: next(point for point in c["points"] if point["x"] == 1.0)
                               for c in facet["configs"]} for facet in payload["sweep"]["facets"]}
    kinds = {task["id"]: task["kind"] for task in _runs_index()["tasks"]}
    labels = {run["name"]: run["tags"]["kind"] for run in payload["runs"]}
    for sid in _full():
        card, rows = _card(sid), _rows(sid)
        assert facets["all"][sid]["median"] == card["objective"]
        assert facets["all"][sid]["n"] == 42
        for kind in set(kinds.values()):
            tasks = [t for t, k in kinds.items() if k == kind]
            label = labels[tasks[0]]
            assert facets[label][sid]["median"] == float(np.median([rows[t]["objective"] for t in tasks])), (sid, kind)
        for run in payload["runs"]:
            row = rows[run["name"]]
            assert run["tags"][f"{sid}_tool_track_rms_mm"] == row["objective"]
            assert run["tags"][f"{sid}_stop_error_mm"] == row["diagnostics"]["stop_error_mm"]
        for metric in ("stop_error_mm", "joint_track_rms_deg", "tool_lag_ms"):
            values = [run["tags"][f"{sid}_{metric}"] for run in payload["runs"]]
            assert float(np.median(values)) == card["diagnostics"][metric], (sid, metric)


def test_matched_speed_curves_and_stock_workbench():
    payload = _payload(COMPARISON / "index.html", "traj-compare-dataset")
    study = json.loads((REPO / "experiments" / "ur5e_speed_sweep" / "study.json").read_text())
    sweep = payload["sweep"]
    assert sweep["x_domain"] == [0.0, 1.0]
    assert sweep["x_buckets"] == study["fractions"] == [step / 10 for step in range(1, 11)]
    curves = next(facet for facet in sweep["facets"] if facet["value"] == "all")["configs"]
    assert {curve["name"] for curve in curves} == set(study["controllers"])
    for curve in curves:
        reference = study["controllers"][curve["name"]]["by_speed"]
        assert [point["median"] for point in curve["points"]] == [row["median_mm"] for row in reference]
        assert [point["n"] for point in curve["points"]] == [len(study["targets"])] * 10
    runs = json.loads((COMPARISON / "workbench" / "runs.json").read_text())["rows"]
    assert len(runs) == len(study["targets"]) * len(_full())
    assert {row["speed"] for row in runs} == {1.0}
    assert all((COMPARISON / "workbench" / row["run_report"]).is_file() for row in runs)


def test_models_datasets_cells_are_the_scorecards():
    """Every Model × Dataset task result is its scorecard row's float, bit for bit (the leaf cell IS the task's
    tool_track_rms_mm), dev and holdout; the dataset roll-up a §57 pivot draws for a leaf row (the median of its tasks:
    the mean of the middle two of an even count, data-ui's pivot-cube) IS each scorecard's objective; the other metrics
    and the gates are the row's."""
    rows = _ruler_rows()
    metas = {p.parent.name: _json(p) for p in (REPO / "solutions").glob("*/meta.json")}
    per_card: dict = {}
    for row in rows:
        sid, task_id = row["id"].split("/", 1)
        assert sid == row["solution"] and row["speed"] == "×1.0"
        card = _split_card(sid, row["split"])
        task_row = {r["task"]: r for r in card["tasks"]}[task_id]
        assert row["rms_mm"] == task_row["objective"], row["id"]
        assert row["stop_mm"] == task_row["kpis"]["stop_error_max_mm"]
        assert row["max_mm"] == task_row["diagnostics"]["tool_track_max_mm"]
        assert row["sat_pct"] == task_row["kpis"]["saturation_share_pct"]
        assert row["gates"] == sum(1 for ok in task_row["verdicts"].values() if ok is True)
        assert row["admissible"] is card["admissible"]
        assert row["deployment"] == f"{card['deployment']['name']} · {row['split']}"
        assert row["ablation"] is ("ablation" in metas[sid].get("tags", []))
        per_card.setdefault((sid, row["split"]), []).append(row["rms_mm"])
    for (sid, split), values in per_card.items():
        card = _split_card(sid, split)
        values = sorted(values)
        assert len(values) == len(card["tasks"])
        mid = len(values) // 2
        assert (values[mid - 1] + values[mid]) / 2 == card["objective"], (sid, split)


def test_models_datasets_families_follow_the_stated_rule():
    """Family › model › config as the page says: an ablation (tag ablation) is in Ablations, its model its ablation kind;
    else the family is the id's pN root named with the first two phrases of that root's change, the model the id's
    first segment, the config the rest ("as built" when none). One leaf row is one solution."""
    metas = {p.parent.name: _json(p) for p in (REPO / "solutions").glob("*/meta.json")}
    leaves: dict = {}
    for row in _mxd_rows():
        sid = row["solution"]
        if row["variant"]:  # an off-ruler controller variant (W3: the feed-forward told the load): its own leaf
            assert row["ruler"] != RULER and row["config"].endswith(f" · {row['variant']}"), row["id"]
            assert leaves.setdefault((row["family"], row["model"], row["config"]), sid) == sid
            continue
        tags = metas[sid].get("tags", [])
        if "ablation" in tags:
            kinds = [t.split(":", 1)[1] for t in tags if t.startswith("ablation:")]
            assert (row["family"], row["model"]) == ("Ablations", kinds[0] if kinds else "ablation"), sid
            assert row["config"] == sid.removeprefix("abl-")
        else:
            root = re.match(r"p\d+", sid).group(0)
            words = ", ".join(metas[root]["change"].split(", ")[:2])
            assert row["family"] == f"P{root[1:]} · {words}", sid
            assert row["model"] == sid.split("-")[0]
            assert row["config"] == (sid.split("-", 1)[1] if "-" in sid else "as built")
        assert leaves.setdefault((row["family"], row["model"], row["config"]), sid) == sid
    page = (MXD / "index.html").read_text()
    assert "first two phrases" in page and "median" in page and "data-rollup-rule" in page


def test_models_datasets_views_are_the_leaderboard_three_and_the_charts():
    """Zach's ruling (2026-11-24 ~21:30, data-ui CONTRACT §57 and §58): one .base, Leaderboard first (the default, and
    the page opens it), then Pivot, then Rows, then the charts (Ranks and the Bars presets, §58); the Leaderboard leaves the ablations out and ranks on the dev
    deployment, the Pivot ranks nothing. When the data-ui checkout is beside this repo, the views are its gallery case's
    (gallery/examples/models-datasets-tta/views.base) at the vendored commit, byte for byte.

    WHY this test exists (Zach, 2026-11-25, on the live page while the pivot was merged only in data-ui): "I am looking
    at the model x dataset here on the public landing page but I don't see it being updated! what happaned?" A view
    change is done when this page ships it (feedback/2026-11-25-model-dataset-page-not-updated.md)."""
    base = (MXD / "models-datasets.base").read_text()
    assert _views(base) == [("pivot", "Leaderboard"), ("pivot", "Pivot"), ("table", "Rows"), ("ranks", "Ranks"),
                            ("bars", "Bars"), ("bars", "Intervals · one task kind"), ("bars", "Violin · tasks"),
                            ("bars", "Normalised · × p1")]
    assert re.search(r'<data-views id="models-datasets" src="models-datasets\.base" view="Leaderboard"',
                     (MXD / "index.html").read_text())
    assert re.search(r"^data: models-datasets\.csv$", base, re.M)
    leaderboard, pivot = base.split("\n  - type: ")[1:3]
    assert 'filters: "ablation == false"' in leaderboard and "reference: ablation" in leaderboard
    assert 'sort: { column: "@ur5e_alone · dev" }' in leaderboard and "color: rank" in leaderboard
    assert "media: { image: preview }" in leaderboard
    assert "filters:" not in pivot and "sort:" not in pivot and "color: none" in pivot and "reference: ablation" in pivot
    # the charts (Zach, 2026-11-24 ~21:30: "lets add that one" (Ranks), "the trick is to support like presets"): Ranks
    # and at least one Bars preset, each over the same pivot block, ranking on the sort column; one normalises against
    # a row the records make
    views = {name: block for (_, name), block in zip(_views(base), base.split("\n  - type: ")[1:])}
    assert "ranks: { column: \"@ur5e_alone · dev\", blocks: task" in views["Ranks"]
    assert "reference: ablation" in views["Ranks"] and "speed: group" in views["Ranks"]
    presets = [name for kind, name in _views(base) if kind == "bars"]
    assert presets and all("bars: { x: " in views[name] and "speed: group" in views[name] for name in presets)
    against = re.search(r'normalize: \{ against: "([^"]+) › ([^"]+)"', views["Normalised · × p1"])
    assert against and any(r["family"] == against[1] and r["model"] == against[2] for r in _mxd_rows())
    for row in _mxd_rows():
        if row["preview"]:
            assert (MXD / row["preview"]).is_file(), row["preview"]
    # every workspace task has its picture; the conveyor cycle's tape is not committed here (it lives in arm_motion_bench's
    # frozen output), so its column has none rather than one drawn from an uncommitted file
    assert {row["task"] for row in _mxd_rows() if not row["preview"]} == {"conveyor-cycle-01"}
    data_ui = REPO.parent / "data-ui"
    if not (data_ui / ".git").exists():
        pytest.skip("no data-ui checkout beside this repo: the views were checked by name, not against the case")
    commit = _json(SITE / "vendor" / "data-ui" / "VENDOR.json")["commit"]
    case = subprocess.run(["git", "-C", str(data_ui), "show", f"{commit}:gallery/examples/models-datasets-tta/views.base"],
                          capture_output=True, text=True, check=True).stdout
    # the port's one change to the case's views (2026-11-25, Zach: "no filters on the columns! I should be able to select
    # which different datasets etc I want to be comparing it on"): a speed level above the dataset (a `group`: each
    # speed's dataset is its own median, never pooled across speeds) and the goal's full-trajectory RMS as a metric; a
    # chart's column id names the speed level too (the one full speed under the dev deployment)
    ported = (case[case.index("\nviews:\n"):]
              .replace("splitBy: [deployment, dataset, kind, task]", "splitBy: [deployment, speed, dataset, kind, task]")
              .replace("roles: { deployment: deployment, dataset: dataset }",
                       "roles: { deployment: deployment, speed: group, dataset: dataset }")
              .replace("metrics: [rms_mm, max_mm, stop_mm, gates]", "metrics: [rms_mm, full_mm, max_mm, stop_mm, gates]")
              .replace("order: [model, config, solution, deployment, kind, task, rms_mm, max_mm,",
                       "order: [model, config, solution, ruler, deployment, speed, dataset, kind, task, rms_mm, full_mm, max_mm,")
              .replace('column: "@ur5e_alone · dev / workspace/v2', 'column: "@ur5e_alone · dev / ×1.0 / workspace/v2'))
    assert base[base.index("\nviews:\n"):] == ported


# ── Every measured dataset is a column (Zach, 2026-11-25) ─────────────────────────────────────────────────────────
# WHY (Zach, 2026-11-25, on the Leaderboard; "the new dataset" is the 30-pick portal conveyor cycle,
# experiments/conveyor_cycle):
# "on the leaderboard view, Codex says it has added a new dataset but I don't see it here"
# "in the left filter bar I can filter by family, models etc so lots of filters on the rows, but no filters on the columns! I should be able to select which different datasets etc I want to be comparing it on."
# Each source below is read here with json, never through the build.

FRACTIONS = [round(step / 10, 1) for step in range(1, 11)]


def _speed(fraction: float) -> str:
    return f"×{fraction:.1f}"


def _off_ruler_sources() -> dict:
    """{(source, solution, variant, split, speed, task): the source's own numbers} for every measured off-ruler result."""
    out = {}
    study = _json(REPO / "experiments" / "ur5e_speed_sweep" / "study.json")
    for sid, per_speed in study["tracking_rms_mm"].items():
        for fraction, values in zip(study["fractions"], per_speed):
            for task, value in zip(study["targets"], values):
                out[("speed study", sid, None, "dev", _speed(fraction), task)] = {"rms_mm": value}
    evidence = _json(REPO / "goals" / "G1-ur5e-tracking-evidence.json")
    import hashlib

    for split in ("dev", "holdout"):
        path = REPO / "goals" / "G1-runs" / f"upright-{split}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["evidence"][f"upright_{split}_sha256"], path
        for run in _json(path)["runs"]:
            out[("goal G1", run["solution"], None, split, _speed(run["fraction"]), run["target"])] = {
                "rms_mm": run["tool_track_rms_mm"], "full_mm": run["full_trajectory_rms_mm"],
                "stop_mm": run["stop_error_max_mm"], "sat_pct": run["saturation_share_pct"],
                "gates": sum(1 for ok in run["gates"].values() if ok is True)}
    portal = [("conveyor baseline", _json(REPO / "experiments" / "conveyor_cycle" / "parent-results.json"))]
    for entry in evidence["evidence"]["portal"]:
        path = REPO / "goals" / "G1-runs" / f"portal-{entry['fraction']:.1f}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["summary_sha256"], path
        portal.append(("goal G1", _json(path)))
    for source, doc in portal:
        for run in doc["runs"]:
            out[(source, doc["controller"], None, "single route", _speed(run["speed_fraction"]), "conveyor-cycle-01")] = {
                "rms_mm": run["tracking_rms_mm"], "full_mm": run["full_trajectory_rms_mm"], "max_mm": run["max_error_mm"],
                "stop_mm": run["kpis"]["stop_error_max_mm"], "sat_pct": run["kpis"]["saturation_share_pct"],
                "gates": sum(1 for ok in run["verdicts"].values() if ok is True)}
    w3 = _json(REPO / "experiments" / "w3_loaded_ur5e_2f85" / "results.json")
    for case in w3["cases"].values():
        if case["plant_load"] is None:  # the bare cases reproduce the scorecards bit for bit: they ARE the ruler's rows
            assert case["reproduces_scorecard"]["bit_identical"] is True
            continue
        for task in case["tasks"]:
            variant = f"feed-forward told {case['model_load']}" if case["model_load"] else None
            out[(f"W3 {case['plant_load']}", case["solution"], variant, case["split"], "×1.0", task["task"])] = {
                "rms_mm": task["objective"], "max_mm": task["diagnostics"]["tool_track_max_mm"],
                "stop_mm": task["kpis"]["stop_error_max_mm"], "sat_pct": task["kpis"]["saturation_share_pct"],
                "gates": sum(1 for ok in task["verdicts"].values() if ok is True)}
    return out


def test_models_datasets_has_a_column_per_measured_dataset():
    """Every measured dataset is on the page as its own columns: ruler v1's dev (ranked) and holdout, and, off the ruler
    and labelled so, the speed study and goal G1's sweep over 0.1…1.0 on the upright paths (dev and holdout), the 30-pick
    portal conveyor cycle at every fraction (the unchanged and the mount-aware controller), and W3's loaded UR5e. A
    column is (deployment, speed, dataset): no column holds rows of two rulers, two splits or two speeds."""
    rows = _mxd_rows()
    ruler = [row for row in rows if row["ruler"] == RULER]
    off = [row for row in rows if row["ruler"] != RULER]
    assert {row["deployment"] for row in ruler} == {"ur5e_alone · dev", "ur5e_alone · holdout"}
    assert {row["speed"] for row in ruler} == {"×1.0"} and {row["dataset"] for row in ruler} == {"workspace/v2"}
    assert off and all(row["ruler"] == "off-ruler" and row["deployment"].endswith("off-ruler") for row in off)
    columns: dict = {}
    for row in rows:
        columns.setdefault((row["deployment"], row["speed"], row["dataset"]), set()).add((row["ruler"], row["split"]))
    assert all(len(owners) == 1 for owners in columns.values()), {k: v for k, v in columns.items() if len(v) > 1}
    have = set(columns)
    conveyor = [k for k in have if k[2] == "conveyor cycle · 30 picks"]
    assert sorted(k[1] for k in conveyor) == [_speed(f) for f in FRACTIONS], conveyor
    for split in ("dev", "holdout"):
        speeds = {k[1] for k in have if k[0] == f"ur5e_alone · {split} · off-ruler" and k[2] == "workspace/v2"}
        assert speeds == {_speed(f) for f in FRACTIONS}, (split, speeds)
    assert any(k[0].startswith("ur5e + 2F-85") for k in have), "W3's loaded check"
    measured = _off_ruler_sources()
    keys = {(row["source"], row["solution"], row["variant"], row["split"], row["speed"], row["task_id"]) for row in off}
    assert keys == set(measured), (sorted(set(measured) - keys)[:5], sorted(keys - set(measured))[:5])
    assert len(off) == len(measured)


def test_models_datasets_off_ruler_cells_are_their_sources():
    """Every off-ruler task result is its source's float, bit for bit (rms_mm is each source's moving-sample tool RMS,
    the ruler's own measure; full_mm the goal's full-trajectory RMS); a number the source does not keep stays empty."""
    measured = _off_ruler_sources()
    for row in _mxd_rows():
        if row["ruler"] == RULER:
            assert row["full_mm"] is None
            continue
        source = measured[(row["source"], row["solution"], row["variant"], row["split"], row["speed"], row["task_id"])]
        for metric in ("rms_mm", "full_mm", "max_mm", "stop_mm", "sat_pct", "gates"):
            assert row[metric] == source.get(metric), (row["id"], metric, row[metric], source.get(metric))


def test_models_datasets_rail_filters_the_columns():
    """The rail filters columns as well as rows: Dataset, Split, Speed fraction, Task kind and Ruler (ranked or
    off-ruler) are facets on the column levels, so picking one leaves only its columns (data-ui's facets filter the
    records; the pivot's columns are the records' values)."""
    base = (MXD / "models-datasets.base").read_text()
    facets = base[base.index("\nfacets:\n"):base.index("\nproperties:\n")]
    for prop in ("dataset", "split", "speed", "kind", "ruler", "family", "model"):
        assert re.search(rf"^  - (?:\{{ property: )?{prop}\b", facets, re.M), prop
    leaderboard = base.split("\n  - type: ")[1]
    assert "splitBy: [deployment, speed, dataset, kind, task]" in leaderboard
    assert "displayName: Speed fraction" in base and "displayName: Ruler" in base


def test_models_datasets_cells_open_their_run():
    """A task result's link is its run: the Comparison report of its task, opened on that run, when the solution ships
    on every dev task; the landing page's player on that run's record (`?run=<record path from runs/index.json>#run`,
    which blackbox_agent 0.1.5's landing reads) when its record ships; else the task's Comparison (and the row says
    so); a holdout task has neither a report nor a saved run, so no link (its cell opens the records behind it)."""
    full = set(_full())
    dev = set(_tasks())
    records = {(s["id"], t): e["record"] for s in _runs_index()["solutions"] for t, e in s["tasks"].items()}
    for row in _mxd_rows():
        if row["ruler"] != RULER:  # off-ruler evidence keeps summaries only: no saved run, no report, no link
            assert row["url"] is None and "off-ruler" in row["opens"], row["id"]
            continue
        sid, task = row["id"].split("/", 1)
        if task in dev and sid in full:
            assert row["url"] == f"../comparison/runs/{task}/report.html#tab=track&run={sid}"
        elif (sid, task) in records:
            assert row["url"] == f"../index.html?run={records[(sid, task)]}#run"
        elif task in dev:
            assert row["url"] == f"../comparison/runs/{task}/report.html#tab=track" and "not saved" in row["opens"]
        else:
            assert row["split"] == "holdout" and row["url"] is None and "only its score" in row["opens"], row["id"]
    page = (MXD / "index.html").read_text()
    # the host script that turns a one-record cell's click into its run (data-ui's data-views-open, CONTRACT §57 cells)
    assert "addEventListener('data-views-open'" in page and "records.length !== 1" in page
    assert "new URL('models-datasets.csv', location.href)" in page


def test_every_landing_link_names_a_shipped_record():
    """Every Model × Dataset link into the landing page names, in its ?run=, a record runs/index.json lists (the landing
    matches it against state.json's playback runs, the same list) and that file ships; and every shipped run outside the
    Comparison has its cell linking there (160 at ruler v1: 34 solutions on 5 tasks, less the 2 in the Comparison)."""
    from urllib.parse import parse_qs, urlsplit

    index = _runs_index()
    listed = {e["record"] for s in index["solutions"] for e in s["tasks"].values()}
    state = {r["path"] for r in _json(SITE / "data" / "state.json")["playback"]["runs"]}
    full = set(_full())
    linked = []
    for row in _mxd_rows():
        parts = urlsplit(row["url"] or "")
        if parts.path != "../index.html":
            continue
        assert parts.fragment == "run" and set(parse_qs(parts.query)) == {"run"}, row["url"]
        record = parse_qs(parts.query)["run"][0]
        assert record in listed and record in state, (row["id"], record)
        assert record == f"runs/{row['id']}.json", (row["id"], record)
        assert (SITE / "data" / record).is_file(), record
        linked.append(record)
    outside = {e["record"] for s in index["solutions"] if s["id"] not in full for e in s["tasks"].values()}
    assert sorted(linked) == sorted(outside) and len(linked) == len(set(linked))


def test_every_link_resolves():
    """Every static href / src on the pages, every link the pages build from their data (a line's report, a target's
    series file, a run's report), every cell's deep link, every site/nav.json link, and each page's one site bar (the
    viewer's <bb-site-nav> reading site/nav.json; lane DROP's header strip, site/nav.js, until 2026-11-24)."""
    build = _build()
    assert build.link_problems() == []
    runs = sorted(COMPARISON.glob("runs/*/report.html"))
    for page in [MXD / "index.html", COMPARISON / "index.html", *runs]:
        text = page.read_text()
        assert text.count("<bb-site-nav ") == 1 and not re.search(r'src="(?:\.\./)*nav\.js"', text), page
    # traj_compare's pages follow the reader's colour scheme (38b5967's dark mode), so their bar is not pinned light;
    # a run report's bar names the run
    dark = '@media (prefers-color-scheme: dark)'
    assert dark in (COMPARISON / "index.html").read_text() and dark in (COMPARISON / "assets" / "style.css").read_text()
    for page in [COMPARISON / "index.html", *runs]:
        assert "<bb-site-nav " in page.read_text() and not re.search(r"<bb-site-nav [^>]*theme=", page.read_text()), page
    for page in runs:
        assert f'here="Run · {page.parent.name}"' in page.read_text(), page
    assert not (SITE / "nav.js").exists(), "site/nav.js (the interim header strip) is retired"


def test_no_private_paths_in_what_these_pages_ship():
    """Public repo: no home directory, private repo, vault path or e-mail address in anything under site/comparison,
    site/models-datasets or site/nav.json."""
    forbidden = re.compile(r"/home/|bam_ws|zach_brain|\.claude|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
    files = [SITE / "nav.json", *[p for d in (COMPARISON, MXD) for p in d.rglob("*") if p.is_file()]]
    hits = []
    for path in files:
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            for match in forbidden.finditer(line):
                context = line[max(0, match.start() - 20): match.end() + 20]
                if not re.search(r"three@|noreply@anthropic\.com", context):
                    hits.append(f"{path.relative_to(REPO)}:{number}: {match.group(0)}")
    assert not hits, "\n".join(hits[:20])


def test_comparison_ships_only_what_a_browser_opens():
    """No duplicate of the run records: no .npz, manifest, analysis, references or row files ship (they stay in
    outputs/dropins/); the viewer files the 42 reports load are one copy each, byte-equal to what build.json pins."""
    import hashlib

    shipped = [p.relative_to(COMPARISON).as_posix() for p in COMPARISON.rglob("*") if p.is_file()]
    assert not [p for p in shipped if p.endswith((".npz", "manifest.json", "analysis.json", ".cache.json", "rows.json",
                                                   ".rrd", ".parquet"))]
    assert not (COMPARISON / "references").exists()
    build = _json(COMPARISON / "build.json")
    for name, digest in build["assets"].items():
        assert hashlib.sha256((COMPARISON / "assets" / name).read_bytes()).hexdigest() == digest
    for report in COMPARISON.glob("runs/*/report.html"):
        text = report.read_text()
        assert len(text) < 2_000_000 and "three.min.js" in text and "THREE.REVISION" not in text, report


def test_comparison_offers_no_rerun_link_to_a_file_it_does_not_ship():
    """No .rrd ships (above), so the runs table must offer no Rerun action: with rerun_server=False + public_url its 84
    rows each linked app.rerun.io and a .rrd download, all 404s (review 2026-11-25). traj_compare's rerun=False says
    the site ships none; the page's own script then draws no Rerun action for a row."""
    page = (COMPARISON / "index.html").read_text()
    payload = _payload(COMPARISON / "index.html", "traj-compare-dataset")
    assert payload.get("rerun") is False
    for key in ("rerun_server", "rerun_sdk", "public_url"):
        assert key not in payload, key
    assert "if (D.rerun === false) return '';" in page
