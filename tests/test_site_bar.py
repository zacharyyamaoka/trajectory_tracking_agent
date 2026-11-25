"""The site's one bar and its dashboard (lane SHIP, 2026-11-24; lane PKG, 2026-11-25; blackbox_agent viewer CONTRACT §18).

Zach, 2026-11-24: "I 100% like the separate landing page and then the open the dashboard button." "So right now we want a
tab for Trajectory Coverage and Trajectory Comparison. And also one for Model x Dataset." Every dashboard page carries the
viewer's <bb-site-nav> reading the one site/nav.json. Since 2026-11-25 the landing and the dashboard are blackbox_agent's
own (`blackbox build`, run by .github/workflows/pages.yml through its site.yml@v0): the box keeps no copy of either, and
these tests hold the box's side of that contract against the installed package (the `site` extra, pinned in uv.lock).
`tools/build_site.py`'s headless checks drive the built site.

Replaced 2026-11-25 (lane PKG): `test_the_dashboard_is_the_viewer_as_vendored_never_edited` (site/dashboard/ held to its
VENDOR.json) became `test_the_box_keeps_no_copy_of_the_package_and_the_package_has_the_dashboard`; the landing test
reads the package's stock landing instead of site/index.html; the node model test runs the package's bar model; the
AGENTS.md test asserts the package workflow instead of the re-vendor command.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
sys.path.insert(0, str(REPO / "tools"))
import site_bar  # noqa: E402

blackbox_site = pytest.importorskip("blackbox_agent.site", reason="the `site` extra: uv run --all-extras")
DASHBOARD = blackbox_site.DASHBOARD  # what `blackbox build` writes to <site>/dashboard/
LANDING = blackbox_site.TEMPLATE / "site" / "index.html"  # what it writes to <site>/index.html (no override here)


def _bar_pages() -> list[Path]:
    """Every drop-in page of the site's dashboards (the Black box's own page is the package's)."""
    return [SITE / "deployments" / "index.html", *sorted((SITE / "datasets").glob("*/index.html")),
            SITE / "comparison" / "index.html", *sorted((SITE / "comparison").glob("runs/*/report.html")),
            SITE / "models-datasets" / "index.html"]


def test_the_box_keeps_no_copy_of_the_package_and_the_package_has_the_dashboard():
    """No vendored viewer, fold or landing in the box: the package's build would drop the first and the last, and a copy
    drifts. The package has what the site bar and the nav links rely on."""
    for copy in ("site/dashboard", "site/index.html", "site/overrides/index.html", "tools/bb",
                 "site/vendor/bb-evidence.js", "site/vendor/bb-headliner.js"):
        assert not (REPO / copy).exists(), f"{copy} is the package's: delete it (blackbox check names it)"
    for need in ("index.html", "viewer/site/dashboard.js", "viewer/src/components/bb-site-nav.js",
                 "viewer/src/components/bb-site-nav.model.js", "viewer/pages/site/overview.json"):
        assert (DASHBOARD / need).is_file(), need
    dash = (DASHBOARD / "index.html").read_text()
    assert 'data-state="../data/state.json"' in dash and 'src="../nav.json"' in dash, "the dashboard reads the site's files"


def test_nav_json_is_bb_site_nav_and_every_link_is_a_page_of_the_site():
    assert site_bar.nav_problems() == []
    doc = json.loads(site_bar.NAV.read_text())
    assert [d["label"] for d in doc["dashboards"]] == ["Black box", "Trajectory coverage", "Trajectory comparison", "Model × Dataset"]
    assert doc["site"]["landing"] == "index.html" and doc["site"]["home"] == "blackbox"
    box = next(d for d in doc["dashboards"] if d["id"] == "blackbox")
    assert box["href"] == "dashboard/" and box["tabs"] == "viewer", "the Black box is the package's viewer"
    for d in doc["dashboards"]:  # in-site paths only (blackbox check: a link that leaves the site is a problem)
        for item in [d, *d.get("pages", [])]:
            assert not re.match(r"^(?:[a-z][a-z0-9+.-]*:|/)", item["href"]) and ".." not in item["href"].split("/"), item


def test_every_dashboard_page_carries_exactly_one_bar_and_no_interim_bar():
    pages = _bar_pages()
    runs = list((SITE / "comparison").glob("runs/*/report.html"))
    assert len(runs) == 42 and len(pages) == 4 + len(runs), len(pages)  # 2 coverage, comparison + 42 runs, M×D
    assert site_bar.page_problems(pages) == []
    # the dashboard's own page loads the bar with the viewer (its host module imports every component, bb-site-nav too)
    dash = (DASHBOARD / "index.html").read_text()
    assert site_bar.TAG.findall(dash) == ['<bb-site-nav src="../nav.json" current="blackbox" href="#{page}"></bb-site-nav>']
    assert '<script type="module" src="viewer/site/dashboard.js"></script>' in dash
    assert "import '../src/components/index.js';" in (DASHBOARD / "viewer/site/dashboard.js").read_text()
    assert "import './bb-site-nav.js';" in (DASHBOARD / "viewer/src/components/index.js").read_text()
    for path in SITE.rglob("*.html"):
        if (SITE / "proposals") in path.parents:  # lane P's design proposals, frozen as they were picked
            continue
        assert not site_bar.OLD_BARS.search(path.read_text(errors="replace")), f"{path.relative_to(REPO)} carries an interim bar"
    for retired in ("nav.js", "stages"):
        assert not (SITE / retired).exists(), f"site/{retired} is retired"


def test_the_landing_is_the_stock_one_and_its_hero_plays_the_saved_runs():
    """proposals-landing 02 (Zach's pick), now the package's stock landing: its own bar, "Open the dashboard →" in the bar
    and under the goal opens the Black box Overview, the footer lists nav.json's dashboards; its hero swaps the Ticker for
    <bb-evidence> when state.json's playback slice lists runs, which this box's export writes (tools/build_site.py)."""
    html = LANDING.read_text()
    assert "<bb-site-nav" not in html
    opens = re.findall(r'<a class="btn btn-primary[^"]*" href="([^"]+)" data-open-dashboard>', html)
    assert opens == ["dashboard/#overview", "dashboard/#overview"], opens
    assert "Open the dashboard" in html and html.index('id="goal"') < html.index("<bb-headliner")
    assert "json('nav.json')" in html, "the footer lists every dashboard of nav.json"
    assert "s.playback && s.playback.runs" in html and "components/bb-evidence.js" in html
    state = json.loads((SITE / "data" / "state.json").read_text())
    assert state["playback"]["runs"], "the hero would fall back to the Ticker: run tools/build_site.py build"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_package_bar_model_places_every_page_under_its_own_dashboard():
    """The package's bar model (bb-site-nav.model.js) on each page's URL and include: the dashboard it marks open is
    the one the include names, and a drop-in page is one of that dashboard's pages (or under its match prefix)."""
    pages = _bar_pages()
    asks = []
    for page in pages:
        tag = site_bar.TAG.search(page.read_text()).group(0)
        current = re.search(r'current="([^"]+)"', tag).group(1)
        asks.append({"url": "https://example.test/site/" + page.relative_to(SITE).as_posix(), "current": current})
    script = """
      const m = await import(process.argv[1]);
      const fs = await import('node:fs');
      const doc = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
      const model = m.makeModel(doc, 'https://example.test/site/nav.json');
      const out = JSON.parse(process.argv[3]).map((a) => { const w = m.locate(model, { url: a.url }); return [w.dash && w.dash.id, w.tab && w.tab.id]; });
      console.log(JSON.stringify(out));
    """
    model = DASHBOARD / "viewer" / "src" / "components" / "bb-site-nav.model.js"
    run = subprocess.run(["node", "--input-type=module", "-e", script, "--", str(model), str(site_bar.NAV), json.dumps(asks)],
                         capture_output=True, text=True, check=True)
    for ask, (dash, tab) in zip(asks, json.loads(run.stdout)):
        assert dash == ask["current"] and tab, (ask, dash, tab)


def test_agents_md_and_the_workflow_say_the_package_builds_the_page():
    text = (REPO / "AGENTS.md").read_text()
    assert "blackbox build" in text and "site.yml@v0" in text and "site/index.html" in text
    assert "vendor_viewer" not in text and "tools/bb/" not in text
    workflow = (REPO / ".github" / "workflows" / "pages.yml").read_text()
    assert "uses: zacharyyamaoka/blackbox_agent/.github/workflows/site.yml@v0" in workflow
    assert "permissions: {contents: read, pages: write, id-token: write}" in workflow
