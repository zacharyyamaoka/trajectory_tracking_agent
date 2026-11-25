"""The landing page's static contract (site/): public, relative, pinned, sized, playback only, and showing only real
numbers. These read the committed files (no browser); `tools/build_site.py shoot` drives the page in headless Chromium.

Replaced 2026-11-24 when the page moved from a live in-browser runtime (Pyodide + MuJoCo WASM) to playing back saved
runs: the wheel / manifest / mirror / shim checks became `test_no_live_runtime_is_shipped_or_loaded`, and the size
limit went from 40 MB to 15 MB. Later that day (lane EV) the runs became bb-run/1 JSON records played by the viewer's
<bb-evidence>, and the 15 MB limit is measured as served (gzip, as GitHub Pages sends text; build_site.served_bytes).
On 2026-11-25 (lane PKG) the landing became blackbox_agent's stock one, built by `blackbox build` around site/: the
script check of `test_no_live_runtime_is_shipped_or_loaded` reads the stock landing's modules (the package's viewer)
instead of site/index.html's, and `test_the_vendored_explainer_is_the_viewers_build` became
`test_the_explainer_is_the_packages_never_a_box_copy`; `test_every_cdn_url_names_an_exact_version` no longer
requires a CDN URL to exist (the retired landing's were its only ones).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
TEXT_SUFFIXES = {".html", ".js", ".css", ".json", ".py", ".svg", ".md", ".xml"}  # .xml: site/data/junit.xml, the test run the Spec page reads
SIZE_LIMIT_BYTES = 1_000_000_000  # GitHub Pages' published-site limit (cited in tools/build_site.py)

pytestmark = pytest.mark.skipif(not (SITE / "data" / "state.json").exists(), reason="site/ not built")

OTHER_LANES = (SITE / "proposals", SITE / "progress.svg", SITE / "views")  # lane P's, lane E's and lane V's files


def _build_site():
    spec = importlib.util.spec_from_file_location("build_site", REPO / "tools" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ours(path: Path) -> bool:
    return not any(path == other or other in path.parents for other in OTHER_LANES)


def _site_text_files() -> list[Path]:
    """Lane W's text files in site/ (everything but the other lanes' paths)."""
    return [p for p in SITE.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES and _ours(p)]


def test_no_private_paths_or_personal_data_in_site():
    """The page is public: no home directories, private repos, vault paths or e-mail addresses anywhere in site/,
    the run records included (a ruler note can quote an exception message; a record names its sources)."""
    forbidden = re.compile(r"/home/|bam_ws|zach_brain|\.claude|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
    allowed = re.compile(r"@highlightjs/cdn-assets@|three@|noreply@anthropic\.com")
    sources = [(p, p.read_text(errors="replace")) for p in _site_text_files()]
    hits = []
    for path, text in sources:
        for number, line in enumerate(text.splitlines(), start=1):
            for match in forbidden.finditer(line):
                if not allowed.search(line[max(0, match.start() - 20): match.end() + 20]):
                    hits.append(f"{path.relative_to(REPO)}:{number}: {match.group(0)}")
    assert not hits, "\n".join(hits[:20])


def test_asset_paths_are_relative():
    """GitHub Pages serves the site from a subpath, so nothing may start at the server root."""
    absolute = re.compile(r"""(?:src|href)=["']/(?!/)|fetch\(\s*["'`]/(?!/)|new URL\(\s*["'`]/(?!/)""")
    hits = [f"{p.relative_to(REPO)}: {m.group(0)}" for p in _site_text_files() if p.suffix in {".html", ".js"}
            for m in absolute.finditer(p.read_text())]
    assert not hits, hits


def test_every_cdn_url_names_an_exact_version():
    urls = set()
    for path in _site_text_files():
        urls |= set(re.findall(r"https://cdn\.jsdelivr\.net/[^\s'\"`)]+", path.read_text()))
    # WHY no `assert urls` (2026-11-25, lane PKG): the retired landing loaded three.js and highlight.js from jsDelivr;
    # the stock landing loads the package's own modules, so the box's files may name no CDN at all. Any it names is pinned.
    unpinned = [url for url in urls if not re.search(r"@\d+\.\d+\.\d+", url)]
    assert not unpinned, unpinned


def test_no_live_runtime_is_shipped_or_loaded():
    """Playback only: no Pyodide, no MuJoCo WebAssembly, no wheels, no worker, no runtime folder (git history keeps them)."""
    for retired in ("wheels", "runtime", "data/repo"):
        assert not (SITE / retired).exists(), f"site/{retired} is the retired live runtime"
    runtime = re.compile(r"pyodide|@mujoco/|mujoco\.wasm|loadPyodide|new Worker\(|\.whl\b|micropip", re.I)
    hits = [f"{p.relative_to(REPO)}: {m.group(0)}" for p in _site_text_files() if p.suffix in {".html", ".js"}
            for m in runtime.finditer(p.read_text())]
    assert not hits, hits
    from blackbox_agent.site import TEMPLATE

    landing = (TEMPLATE / "site" / "index.html").read_text()
    scripts = re.findall(r"<script[^>]*src=[\"']([^\"']+)", landing)
    imports = re.findall(r"import\('([^']+)'\)", landing)
    # WHY the headliner is allowed (2026-11-24): Zach picked the Ticker v1 as the page's headline; it is a static chart
    # module (uPlot) reading data/state.json, not a runtime. WHY bb-evidence (2026-11-24, Zach: "it should use the newer
    # 3D explanation things we designed"): the viewer's metric explainer, playing saved bb-run/1 records with three.js;
    # it simulates and scores nothing. bb-gates: the gate tiles. Anything else, or any Pyodide / MuJoCo load, still fails.
    assert scripts == ["dashboard/viewer/src/components/bb-headliner.js", "dashboard/viewer/src/components/bb-gates.js"], scripts
    assert imports == ["./dashboard/viewer/src/components/bb-evidence.js"], imports
    assert not runtime.search(landing)
    assert not (SITE / "data" / "playback").exists(), "site/data/playback is the retired binary playback"


def test_leaderboard_numbers_are_the_scorecards():
    """Never placeholder numbers: every leaderboard row is a solutions/<id>/scorecard.json, value for value; every scored
    solution not tagged `ablation` is in it."""
    page = json.loads((SITE / "data" / "page.json").read_text())
    rows = page["leaderboard"]["rows"]
    cards = [path for path in sorted((REPO / "solutions").glob("*/scorecard.json"))
             if "ablation" not in json.loads(path.with_name("meta.json").read_text()).get("tags", [])]
    assert sorted(row["id"] for row in rows) == sorted(path.parent.name for path in cards)
    assert page["leaderboard"]["scored"] == bool(cards)
    for row in rows:
        card = json.loads((REPO / "solutions" / row["id"] / "scorecard.json").read_text())
        assert row["objective"] == card["objective"]
        assert row["admissible"] == card["admissible"]
        assert row["gate_pass_rate"] == card["gate_pass_rate"]
    best = page["leaderboard"]["best"]
    index = json.loads((SITE / "data" / "runs" / "index.json").read_text())
    assert best == index["rule"]["full"]["best"], "the population's best and the saved runs' best must agree"


def test_site_is_under_the_size_limit():
    """All of site/ as served: text gzipped (GitHub Pages sends it so; git stores it so), media as they are."""
    bs = _build_site()
    total = bs.site_bytes(served=False)
    assert total <= SIZE_LIMIT_BYTES, f"site/ is {total / 1e6:.2f} MB, over GitHub Pages' 1 GB"
    assert bs.SIZE_LIMIT_BYTES == SIZE_LIMIT_BYTES
    big = [p for p in SITE.rglob("*") if p.is_file() and p.stat().st_size > bs.FILE_LIMIT_BYTES]
    assert not big, f"over GitHub's 100 MiB per-file limit: {big}"


def test_the_served_size_is_measured_not_assumed(tmp_path):
    """served_bytes gzips text and counts media raw: a file of repeated text weighs far less than its size, and an
    incompressible one weighs its size."""
    import os

    bs = _build_site()
    text = tmp_path / "a.json"
    text.write_text("[" + ",".join(["0.12345"] * 20000) + "]")
    noise = tmp_path / "b.json"
    noise.write_bytes(os.urandom(50000))
    media = tmp_path / "c.mp4"
    media.write_bytes(b"\0" * 50000)
    assert bs.served_bytes(text) < text.stat().st_size / 20
    assert bs.served_bytes(noise) >= noise.stat().st_size
    assert bs.served_bytes(media) == media.stat().st_size


def test_the_explainer_is_the_packages_never_a_box_copy():
    """bb-evidence plays the runs from the package's viewer (the stock landing imports it); the box ships no copy."""
    from blackbox_agent.site import COMPONENTS

    assert not (SITE / "vendor" / "bb-evidence.js").exists() and not (SITE / "assets" / "app.js").exists()
    source = (COMPONENTS / "bb-evidence.js").read_text()
    assert "register(BBEvidence)" in source or "customElements.define" in source
