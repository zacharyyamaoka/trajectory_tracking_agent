"""The Deployments and Datasets pages (site/deployments/, site/datasets/<robot>/: the Trajectory coverage dashboard) and
their site bar, written by tools/build_coverage.py. These read the committed files against their sources, independently of the build's own
code where they can: a row's numbers against the manifest it names, a robot's name against robot_controllers, a link's
filter against the workbench's own rows. `tools/shoot_coverage.py` drives the pages in headless Chromium.

Sources outside this repo (arm_motion_bench, for the rows not in the ruler) are read when a checkout is beside this one
(or at TTA_ARM_MOTION_BENCH); without it those checks skip and say so.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
DEPLOYMENTS = SITE / "deployments" / "deployments.json"
BENCH = Path(os.environ.get("TTA_ARM_MOTION_BENCH", REPO.parent / "arm_motion_bench"))

pytestmark = pytest.mark.skipif(not DEPLOYMENTS.exists(), reason="site/deployments not built")
needs_bench = pytest.mark.skipif(not (BENCH / "datasets").is_dir(),
                                 reason=f"no arm_motion_bench checkout at {BENCH}: its rows are not re-read")


def _rows() -> list[dict]:
    return json.loads(DEPLOYMENTS.read_text())["rows"]


def _by_id() -> dict[str, dict]:
    return {row["id"]: row for row in _rows()}


def _children(row: dict) -> list[dict]:
    return [r for r in _rows() if r["parent"] == row["id"]]


def _source_path(row: dict) -> Path:
    source = row["source"]
    if source.startswith("arm_motion_bench "):
        return BENCH / source.split(" ", 1)[1]
    return REPO / source


def _objectives() -> str:
    return (REPO / "OBJECTIVES.md").read_text()


def _build():
    spec = importlib.util.spec_from_file_location("build_coverage", REPO / "tools" / "build_coverage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── every row matches its source ────────────────────────────────────────────────────────────────────────────────────


def test_ruler_dataset_row_is_the_frozen_manifest():
    """The one dataset in ruler v1 is OBJECTIVES §3's, and its numbers are its manifest's (this repo's copy)."""
    dataset = re.search(r"^## 3\. The dataset v1: `([^`]+)`", _objectives(), re.M).group(1)
    deployment = re.search(r"^## 2\. Deployment v1: `([^`]+)`", _objectives(), re.M).group(1)
    in_ruler = [row for row in _rows() if row["status"] == "ruler-v1"]
    assert {(row["level"], row["key"]) for row in in_ruler if row["level"] != "Robot"} == {
        ("Deployment", deployment), ("Dataset", dataset)}
    row = _by_id()[f"dataset:{dataset}"]
    assert row["source"] == f"datasets/{dataset}/manifest.json"
    manifest = json.loads((REPO / row["source"]).read_text())
    tasks = [json.loads(line) for line in (REPO / "datasets" / dataset / "tasks.jsonl").read_text().splitlines() if line]
    assert row["dev"] == manifest["counts"]["dev"]["total"] == sum(t["split"] == "dev" for t in tasks)
    assert row["holdout"] == manifest["counts"]["holdout"]["total"] == sum(t["split"] == "holdout" for t in tasks)
    assert row["trajectories"] == len(tasks)
    assert row["duration_s"] == pytest.approx(sum(manifest["duration_rung_1_s"].values()), abs=0.01)


@needs_bench
def test_every_dataset_row_matches_its_manifest():
    rows = [row for row in _rows() if row["level"] == "Dataset"]
    titles = _bench_titles()
    for row in rows:
        manifest = json.loads(_source_path(row).read_text())
        assert row["key"] == f"{manifest['robot']}/{manifest['dataset']}/{manifest['version']}", row["id"]
        assert row["dev"] == manifest["counts"]["dev"]["total"], row["id"]
        assert row["holdout"] == manifest["counts"]["holdout"]["total"], row["id"]
        assert row["trajectories"] == row["dev"] + row["holdout"], row["id"]
        assert row["duration_s"] == pytest.approx(sum(manifest["duration_rung_1_s"].values()), abs=0.01), row["id"]
        assert row["name"] == titles["DATASET_TITLES"].get(manifest["dataset"], manifest["dataset"]), row["id"]


@needs_bench
def test_every_frozen_dataset_has_a_row():
    """Nothing is hidden: every newest dataset version in this repo and in arm_motion_bench is a row."""
    newest: dict[tuple[str, str], int] = {}
    for root in (REPO / "datasets", BENCH / "datasets"):
        for manifest in root.glob("*/*/v*/manifest.json"):
            pair, version = (manifest.parents[2].name, manifest.parents[1].name), int(manifest.parent.name[1:])
            newest[pair] = max(newest.get(pair, 0), version)
    keys = {row["key"] for row in _rows() if row["level"] == "Dataset"}
    assert keys == {f"{d}/{n}/v{v}" for (d, n), v in newest.items()}


@needs_bench
def test_every_deployment_row_matches_its_station_and_datasets():
    titles = _bench_titles()
    for row in [r for r in _rows() if r["level"] == "Deployment"]:
        datasets = _children(row)
        for key in ("datasets", "dev", "holdout", "trajectories", "in_workbench"):
            assert row[key] == sum(child[key] for child in datasets), (row["id"], key)
        if not datasets:  # a robot robot_controllers defines with no frozen dataset anywhere
            assert row["status"] == "not-in-ruler" and row["scene"] is None
            continue
        assert row["name"] == titles["DEPLOYMENT_TITLES"].get(row["key"], row["key"])
        for child in datasets:
            station = json.loads(_source_path(child).with_name("station.json").read_text())
            assert station["robot"] == row["key"] and station["title"] == row["scene"], child["id"]


def test_every_robot_row_is_a_robot_controllers_arm():
    from robot_controllers.bench import arms

    robots = {row["key"]: row for row in _rows() if row["level"] == "Robot"}
    assert list(robots) == sorted(robots, key=list(robots).index)  # (order is the gallery's)
    assert set(robots) == {name for name, _ in arms.ARM_MODULES}
    for name, row in robots.items():
        assert row["name"] == arms.arm(name).title
        children = _children(row)
        assert children, f"{name} has no deployment row"
        for key in ("datasets", "trajectories", "in_workbench"):
            assert row[key] == sum(child[key] for child in children), (name, key)


def test_rows_not_in_the_ruler_say_why_from_objectives_section_5():
    """A deferred row names its spec, the spec is a deferred one, and the quote it shows is OBJECTIVES §5's."""
    section5 = " ".join(_objectives().split("## 5.", 1)[1].split())
    for row in _rows():
        assert row["why"], row["id"]
        if row["status"] == "deferred":
            spec = next((REPO / "specs").glob(f"{row['spec']}-*.md"))
            assert "kind: deferred" in spec.read_text(), spec
            quote = re.search(r"“(.+?)”", row["why"]).group(1)
            assert quote in section5 and quote in spec.read_text(), (row["id"], quote)
        elif row["status"] == "not-in-ruler":
            assert row["spec"] is None, row["id"]


@needs_bench
def test_committed_rows_are_what_the_sources_give_now():
    """A rebuild would write the same rows (else the page is stale: run tools/build_coverage.py build)."""
    assert _build().facts() == _rows()


# ── links: every gallery tile opens a Datasets page filtered to it ──────────────────────────────────────────────────


def _kept(href: str) -> tuple[Path, list[dict], dict[str, list[str]]]:
    parts = urlsplit(href)
    page = (DEPLOYMENTS.parent / parts.path).resolve()
    held = json.loads((page / "trajectories.json").read_text())["rows"]
    query = {key: values[0].split(",") for key, values in parse_qs(parts.query).items()}
    return page, [r for r in held if all(r.get(key) in values for key, values in query.items())], query


def test_every_gallery_tile_links_to_a_datasets_page_filtered_to_it():
    tiles = [row for row in _rows() if row["card"] == "yes"]
    assert tiles, "the gallery has no tiles"
    linked = [row for row in tiles if row["coverage"]]
    assert linked, "no tile opens a Datasets page"
    for row in linked:
        page, kept, query = _kept(row["coverage"])
        assert (page / "index.html").exists() and (page / "coverage.base").exists(), row["id"]
        assert '<data-workbench id="coverage" src="coverage.base"' in (page / "index.html").read_text()
        assert len(kept) == row["in_workbench"] > 0, row["id"]
        if row["level"] == "Robot":
            assert query == {}, f"{row['id']}: a robot opens all its datasets"
        else:
            assert query.get(row["level"].lower()) == [row["key"]], row["id"]
            assert all(r[row["level"].lower()] == row["key"] for r in kept)


def test_every_dataset_row_on_the_datasets_page_links_with_its_filter():
    for row in [r for r in _rows() if r["level"] == "Dataset" and r["in_workbench"]]:
        _, kept, query = _kept(row["coverage"])
        assert query["dataset"] == [row["key"]] and len(kept) == row["in_workbench"]


def test_a_tile_without_a_page_is_greyed_with_its_reason_and_never_a_link():
    for row in [r for r in _rows() if r["card"] == "yes" and not r["coverage"]]:
        assert row["status"] != "ruler-v1" and row["in_workbench"] == 0, row["id"]
        picture = (DEPLOYMENTS.parent / row["thumb"]).read_text()
        assert row["status_label"] in picture, row["id"]
        assert (row["spec"] or "dataset") in picture, row["id"]


def test_the_workbench_holds_exactly_the_ruler_datasets():
    """The Datasets page shows what the ruler scores (datasets go with the agent), each trajectory once."""
    for data in sorted((SITE / "datasets").glob("*/trajectories.json")):
        rows = json.loads(data.read_text())["rows"]
        assert len({r["name"] for r in rows}) == len(rows)
        robot = _by_id()[f"robot:{data.parent.name}"]
        assert len(rows) == robot["in_workbench"]
        ruler = {r["key"] for r in _rows() if r["level"] == "Dataset" and r["status"] == "ruler-v1" and r["robot"] == robot["key"]}
        assert {r["dataset"] for r in rows} == ruler
        for key in ruler:
            tasks = (REPO / "datasets" / key / "tasks.jsonl").read_text().splitlines()
            assert sum(r["dataset"] == key for r in rows) == len([t for t in tasks if t.strip()])


# ── the site bar (lane CV's stage bar until 2026-11-24; tests/test_site_bar.py holds every page of the site) ──────────


def test_both_pages_carry_the_one_site_bar_reading_site_nav_json():
    """One <bb-site-nav> each, reading site/nav.json, current = the Trajectory coverage dashboard, no stage bar left."""
    import sys

    sys.path.insert(0, str(REPO / "tools"))
    import site_bar

    pages = [SITE / "deployments" / "index.html", *sorted((SITE / "datasets").glob("*/index.html"))]
    assert len(pages) >= 2
    assert site_bar.page_problems(pages) == []
    for page in pages:
        assert 'current="coverage"' in page.read_text(), page
    assert not (SITE / "stages").exists(), "site/stages/ (the interim stage bar) is retired"


# ── public: no private paths anywhere under site/ ───────────────────────────────────────────────────────────────────

PRIVATE = re.compile(r"/home/|bam_ws|zach_brain|\.claude|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
TEXT = {".html", ".js", ".mjs", ".css", ".json", ".base", ".md", ".svg", ".txt", ".py", ".yml", ".yaml"}


def _private_hits(paths) -> list[str]:
    hits = []
    for path in paths:
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            for match in PRIVATE.finditer(line):
                hits.append(f"{path.relative_to(REPO)}:{number}: {match.group(0)}")
    return hits


def test_no_private_paths_in_these_pages_or_the_kit():
    roots = (SITE / "deployments", SITE / "datasets", SITE / "vendor" / "data-ui")
    files = [p for root in roots for p in root.rglob("*") if p.is_file() and p.suffix in TEXT]
    assert files
    hits = _private_hits(files)
    assert not hits, "\n".join(hits[:20])


def test_no_private_paths_anywhere_under_site():
    """The whole public site, every text file (the other lanes' too): no home directory, private repo or vault path,
    and no e-mail address."""
    hits = _private_hits(p for p in SITE.rglob("*") if p.is_file() and p.suffix in TEXT)
    assert not hits, "\n".join(hits[:20])


def test_the_kit_is_the_pinned_data_ui_commit_with_only_these_views():
    record = json.loads((SITE / "vendor" / "data-ui" / "VENDOR.json").read_text())
    build = _build()
    assert record["commit"] == build.DATA_UI_REF
    assert sorted(record["views"]) == sorted(build.KIT_VIEWS)
    assert record["repo"] == "data-ui"


def _bench_titles() -> dict:
    tree = ast.parse((BENCH / "src" / "arm_motion_bench" / "playback.py").read_text())
    return {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("DEPLOYMENT_TITLES", "DATASET_TITLES")}
