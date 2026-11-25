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

import importlib.util
import json
import math
import re
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


def test_the_pages_are_current():
    """The committed pages are the build of today's sources: the solutions the landing page ships on every task, the 42
    dev tasks, and one Model × Dataset row per scored solution × task. A new best or a new scorecard makes this red."""
    build = _json(COMPARISON / "build.json")
    assert [s["id"] for s in build["solutions"]] == _full(), f"stale: {REBUILD}"
    assert build["tasks"] == _tasks(), f"stale: {REBUILD}"
    cells = _json(MXD / "cells.json")["rows"]
    scored = sorted(p.parent.name for p in (REPO / "solutions").glob("*/scorecard.json"))
    assert sorted({row["solution"] for row in cells}) == scored, f"stale: {REBUILD}"
    assert len(cells) == len(scored) * len(_tasks())


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
    facets = {facet["value"]: {c["name"]: c["points"][0] for c in facet["configs"]} for facet in payload["sweep"]["facets"]}
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


def test_models_datasets_cells_are_the_scorecards():
    """Every Model × Dataset cell is its scorecard row's number; the margins are the objective (the median of the
    dataset, PICKS' roll-up with one dataset) and the worst task; the rank is recounted from the scorecards."""
    cells = _json(MXD / "cells.json")["rows"]
    metas = {p.parent.name: _json(p) for p in (REPO / "solutions").glob("*/meta.json")}
    cards = {sid: _card(sid) for sid in {row["solution"] for row in cells}}
    solutions = [sid for sid in cards if "ablation" not in metas[sid].get("tags", [])]
    for row in cells:
        card = cards[row["solution"]]
        task_row = {r["task"]: r for r in card["tasks"]}[row["task"]]
        assert row["tool_track_rms_mm"] == task_row["objective"]
        assert row["stop_error_max_mm"] == task_row["kpis"]["stop_error_max_mm"]
        assert row["objective_mm"] == card["objective"]
        assert row["worst_task_mm"] == max(r["objective"] for r in card["tasks"])
        failed = [g for g, ok in task_row["verdicts"].items() if ok is not True]
        assert row["failed_gate_count"] == len(failed) and row["verdict"] == ("fail" if failed else "pass")
        others = [_rows_of(cards[s])[row["task"]] for s in solutions]
        assert row["rank_on_task"] == 1 + sum(1 for v in others if v < task_row["objective"])
        assert row["iteration"] == ("ablation" if "ablation" in metas[row["solution"]].get("tags", []) else "solution")
    # the per-dataset median a data-ui pivot computes (summarize Median: the mean of the middle two of 42) is the objective
    for sid, card in cards.items():
        values = sorted(row["tool_track_rms_mm"] for row in cells if row["solution"] == sid)
        assert (values[20] + values[21]) / 2 == card["objective"], sid


def _rows_of(card: dict) -> dict:
    return {r["task"]: r["objective"] for r in card["tasks"]}


def test_models_datasets_families_follow_the_stated_rule():
    """Family by lineage, as the page says: gen-0 -> "generation 0", ablation -> "ablations", else "<root> lineage"
    where root is the generation-0 solution reached through `parent`."""
    metas = {p.parent.name: _json(p) for p in (REPO / "solutions").glob("*/meta.json")}
    for row in _json(MXD / "cells.json")["rows"]:
        tags = metas[row["solution"]].get("tags", [])
        if "ablation" in tags:
            assert row["family"] == "ablations"
        elif "gen-0" in tags:
            assert row["family"] == "generation 0"
        else:
            node = row["solution"]
            while metas[node].get("parent"):
                node = metas[node]["parent"]
            assert "gen-0" in metas[node].get("tags", []) and row["family"] == f"{node} lineage"
    page = (MXD / "index.html").read_text()
    assert "Family, by lineage" in page and "median" in page and "data-rollup-rule" in page


def test_models_datasets_cells_open_their_run():
    """A cell's link is its run: the Comparison report of its task, opened on that run, when the solution ships on every
    task; the landing page's player on that run's record (`?run=<record path from runs/index.json>#run`, which
    blackbox_agent 0.1.5's landing reads) when its record ships; else the task's Comparison (and the record says so)."""
    full = set(_full())
    records = {(s["id"], t): e["record"] for s in _runs_index()["solutions"] for t, e in s["tasks"].items()}
    for row in _json(MXD / "cells.json")["rows"]:
        if row["solution"] in full:
            assert row["url"] == f"../comparison/runs/{row['task']}/report.html#tab=track&run={row['solution']}"
        elif (row["solution"], row["task"]) in records:
            assert row["url"] == f"../index.html?run={records[(row['solution'], row['task'])]}#run"
        else:
            assert row["url"].startswith(f"../comparison/runs/{row['task']}/report.html") and "not saved" in row["opens"]


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
    for row in _json(MXD / "cells.json")["rows"]:
        parts = urlsplit(row["url"])
        if parts.path != "../index.html":
            continue
        assert parts.fragment == "run" and set(parse_qs(parts.query)) == {"run"}, row["url"]
        record = parse_qs(parts.query)["run"][0]
        assert record in listed and record in state, (row["id"], record)
        assert record == f"runs/{row['solution']}/{row['task']}.json", (row["id"], record)
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
