"""The landing page's static contract (site/): public, relative, pinned, sized, playback only, and showing only real
numbers. These read the committed files (no browser); `tools/build_site.py shoot` drives the page in headless Chromium.

Replaced 2026-11-24 when the page moved from a live in-browser runtime (Pyodide + MuJoCo WASM) to playing back saved
runs: the wheel / manifest / mirror / shim checks became `test_no_live_runtime_is_shipped_or_loaded`, and the size
limit went from 40 MB to 15 MB.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import re
import struct
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
TEXT_SUFFIXES = {".html", ".js", ".css", ".json", ".py", ".svg", ".md"}
SIZE_LIMIT_BYTES = 15 * 1024 * 1024  # all of site/, committed

pytestmark = pytest.mark.skipif(not (SITE / "index.html").exists(), reason="site/ not built")

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


def _playback_headers() -> list[tuple[Path, str]]:
    """The JSON header of every playback file (they are gzip, so a plain text scan would not see inside them)."""
    out = []
    for path in sorted((SITE / "data" / "playback").rglob("*.bin.gz")):
        blob = gzip.decompress(path.read_bytes())
        length = struct.unpack("<I", blob[8:12])[0]
        out.append((path, blob[12:12 + length].decode()))
    return out


def test_no_private_paths_or_personal_data_in_site():
    """The page is public: no home directories, private repos, vault paths or e-mail addresses anywhere in site/,
    including inside the playback files' headers (a ruler note can quote an exception message)."""
    forbidden = re.compile(r"/home/|bam_ws|zach_brain|\.claude|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
    allowed = re.compile(r"@highlightjs/cdn-assets@|three@|noreply@anthropic\.com")
    sources = [(p, p.read_text(errors="replace")) for p in _site_text_files()] + _playback_headers()
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
    assert urls, "the page loads three.js and highlight.js from jsDelivr"
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
    scripts = re.findall(r"<script[^>]*src=[\"']([^\"']+)", (SITE / "index.html").read_text())
    assert scripts == ["assets/app.js"], scripts


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
    index = json.loads((SITE / "data" / "playback" / "index.json").read_text())
    assert best == index["rule"]["full"]["best"], "the population's best and the playback's best must agree"


def test_site_is_under_the_size_limit():
    total = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    assert total <= SIZE_LIMIT_BYTES, f"site/ is {total / 1e6:.2f} MB"
    assert _build_site().SIZE_LIMIT_BYTES == SIZE_LIMIT_BYTES
