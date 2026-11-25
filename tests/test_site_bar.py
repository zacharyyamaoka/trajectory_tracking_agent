"""The site's one bar and its dashboard (lane SHIP, 2026-11-24; blackbox_agent viewer CONTRACT §18).

Zach, 2026-11-24: "I 100% like the separate landing page and then the open the dashboard button." "So right now we want a
tab for Trajectory Coverage and Trajectory Comparison. And also one for Model x Dataset." Every dashboard page carries the
viewer's <bb-site-nav> reading the one site/nav.json; the dashboard itself (site/dashboard/) is the blackbox_agent viewer,
vendored by blackbox_agent's tools/vendor_viewer.py and held here to its VENDOR.json; the landing (site/index.html) keeps
its own bar with "Open the dashboard →". These read the committed files; `tools/build_site.py`'s headless checks drive them.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
DASHBOARD = SITE / "dashboard"
sys.path.insert(0, str(REPO / "tools"))
import site_bar  # noqa: E402

pytestmark = pytest.mark.skipif(not (DASHBOARD / "VENDOR.json").exists(), reason="site/dashboard not vendored")


def _bar_pages() -> list[Path]:
    """Every page of the site's dashboards: the vendored dashboard and each drop-in page."""
    return [DASHBOARD / "index.html", SITE / "deployments" / "index.html", *sorted((SITE / "datasets").glob("*/index.html")),
            SITE / "comparison" / "index.html", *sorted((SITE / "comparison").glob("runs/*/report.html")),
            SITE / "models-datasets" / "index.html"]


def test_the_dashboard_is_the_viewer_as_vendored_never_edited():
    """site/dashboard/ is blackbox_agent's viewer at one commit: every file its VENDOR.json lists, byte for byte, and no
    other (re-vendor with blackbox_agent's tools/vendor_viewer.py; never edit the copy)."""
    meta = json.loads((DASHBOARD / "VENDOR.json").read_text())
    assert re.fullmatch(r"[0-9a-f]{40}", meta["commit"]) and meta["source"].endswith("/blackbox_agent")
    assert meta["reads"] == {"nav": "../nav.json", "state": "../data/state.json"}
    listed = {row["path"]: row["sha256"] for row in meta["files"]}
    problems = [f"edited or missing: {path}" for path, digest in listed.items()
                if not (DASHBOARD / path).is_file() or hashlib.sha256((DASHBOARD / path).read_bytes()).hexdigest() != digest]
    problems += [f"not vendored: {p.relative_to(DASHBOARD)}" for p in DASHBOARD.rglob("*")
                 if p.is_file() and p.name != "VENDOR.json" and p.relative_to(DASHBOARD).as_posix() not in listed]
    assert not problems, problems[:20]
    for need in ("index.html", "viewer/site/dashboard.js", "viewer/src/components/bb-site-nav.js", "viewer/pages/site/overview.json"):
        assert need in listed, need


def test_nav_json_is_bb_site_nav_and_every_link_is_a_page_of_the_site():
    assert site_bar.nav_problems() == []
    doc = json.loads(site_bar.NAV.read_text())
    assert [d["label"] for d in doc["dashboards"]] == ["Black box", "Trajectory coverage", "Trajectory comparison", "Model × Dataset"]
    assert doc["site"]["landing"] == "index.html" and doc["site"]["home"] == "blackbox"
    box = next(d for d in doc["dashboards"] if d["id"] == "blackbox")
    assert box["href"] == "dashboard/" and box["tabs"] == "viewer", "the Black box is the vendored viewer"


def test_every_dashboard_page_carries_exactly_one_bar_and_no_interim_bar():
    pages = _bar_pages()
    runs = list((SITE / "comparison").glob("runs/*/report.html"))
    assert len(runs) == 42 and len(pages) == 5 + len(runs), len(pages)  # the dashboard, 2 coverage, comparison + 42 runs, M×D
    assert site_bar.page_problems(pages[1:]) == []
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


def test_the_landing_keeps_its_own_bar_and_opens_the_dashboard():
    """proposals-landing 02 (Zach's pick): a page of its own; "Open the dashboard →" in its bar and under the goal opens
    the Black box Overview; its footer lists every dashboard of nav.json, in order."""
    html = (SITE / "index.html").read_text()
    assert "<bb-site-nav" not in html
    opens = re.findall(r'<a class="btn btn-primary[^"]*" href="([^"]+)" data-open-dashboard>', html)
    assert opens == ["dashboard/#overview", "dashboard/#overview"], opens
    assert "Open the dashboard" in html and html.index('id="goal"') < html.index("<bb-headliner")
    doc = json.loads(site_bar.NAV.read_text())
    footer = html[html.index('<footer'):]
    listed = re.findall(r'<li><a href="([^"]+)">([^<]+)</a>', footer.split("<h4>This project</h4>")[0])
    assert [label for _, label in listed] == [d["label"] for d in doc["dashboards"]]
    for (href, _), d in zip(listed, doc["dashboards"]):
        assert href.split("#")[0] == d["href"], (href, d["href"])


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_vendored_model_places_every_page_under_its_own_dashboard():
    """The vendored bar's own model (bb-site-nav.model.js) on each page's URL and include: the dashboard it marks open is
    the one the include names, and a drop-in page is one of that dashboard's pages (or under its match prefix)."""
    pages = [p for p in _bar_pages() if p != DASHBOARD / "index.html"]
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


def test_agents_md_says_how_to_re_vendor():
    text = (REPO / "AGENTS.md").read_text()
    assert "tools/vendor_viewer.py" in text and "site/dashboard/" in text
