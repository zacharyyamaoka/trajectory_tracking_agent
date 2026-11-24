"""The landing page's static contract (site/): public, relative, pinned, sized, and showing only real numbers.

These read the committed files only (no browser); the in-browser run is checked by `tools/build_site.py parity`.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
TEXT_SUFFIXES = {".html", ".js", ".css", ".json", ".py", ".svg", ".md"}
SIZE_LIMIT_BYTES = 40 * 1024 * 1024  # the brief: site/ under ~40 MB committed

pytestmark = pytest.mark.skipif(not (SITE / "index.html").exists(), reason="site/ not built")


OTHER_LANES = (SITE / "proposals", SITE / "progress.svg")  # lane P's and lane E's files: their own checks


def _site_text_files() -> list[Path]:
    """Lane W's text files in site/ (everything but the other lanes' paths)."""
    return [p for p in SITE.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES
            and not any(p == other or other in p.parents for other in OTHER_LANES)]


def test_no_private_paths_or_personal_data_in_site():
    """The page is public: no home directories, private repos, vault paths or e-mail addresses anywhere in site/."""
    forbidden = re.compile(r"/home/(?!pyodide)|bam_ws|zach_brain|\.claude|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
    allowed = re.compile(r"@mujoco/mujoco@|@highlightjs/cdn-assets@|three@|pyodide@|noreply@anthropic\.com")
    hits = []
    for path in _site_text_files():
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
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
    assert urls, "the page loads its runtime from jsDelivr"
    unpinned = [url for url in urls if not re.search(r"@\d+\.\d+\.\d+|/v\d+\.\d+\.\d+/|\$\{", url)]
    assert not unpinned, unpinned


def test_manifest_wheels_exist_and_match_their_sha256():
    manifest = json.loads((SITE / "runtime" / "manifest.json").read_text())
    assert manifest["mujoco_wasm"] == "3.11.0", "the WASM build must be the same MuJoCo release as the native wheel"
    names = {row["dist"] for row in manifest["wheels"]}
    assert {"robot-msgs", "robot-controllers", "trajectory-tracking-agent", "dataclass-values"} <= names
    for row in manifest["wheels"]:
        wheel = SITE / "wheels" / row["file"]
        assert wheel.exists(), row["file"]
        assert hashlib.sha256(wheel.read_bytes()).hexdigest() == row["sha256"], row["file"]
        assert "+dirty" not in str(row.get("commit")), f"{row['file']} was built from an uncommitted tree"
    for row in manifest["repo_files"]:
        assert (SITE / "data" / "repo" / row["path"]).exists(), row["path"]
        assert "holdout" not in row["path"], "the page never ships holdout tapes"


def test_mirrored_repo_files_are_byte_copies():
    manifest = json.loads((SITE / "runtime" / "manifest.json").read_text())
    for row in manifest["repo_files"]:
        source = REPO / row["path"]
        if source.exists():  # a solution removed since the build is caught by the leaderboard test instead
            assert (SITE / "data" / "repo" / row["path"]).read_bytes() == source.read_bytes(), row["path"]


def test_leaderboard_numbers_are_the_scorecards():
    """Never placeholder numbers: every leaderboard row is a solutions/<id>/scorecard.json, value for value."""
    page = json.loads((SITE / "data" / "page.json").read_text())
    rows = page["leaderboard"]["rows"]
    cards = sorted((REPO / "solutions").glob("*/scorecard.json"))
    assert len(rows) == len(cards)
    assert page["leaderboard"]["scored"] == bool(cards)
    for row in rows:
        card = json.loads((REPO / "solutions" / row["id"] / "scorecard.json").read_text())
        assert row["objective"] == card["objective"]
        assert row["admissible"] == card["admissible"]
        assert row["gate_pass_rate"] == card["gate_pass_rate"]


def test_site_is_under_the_size_limit():
    total = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    assert total < SIZE_LIMIT_BYTES, f"site/ is {total / 1e6:.1f} MB"


def test_shim_is_the_only_mujoco_and_says_so():
    shim = (SITE / "runtime" / "mujoco_shim.py").read_text()
    assert "THE ONLY NON-ORIGINAL CODE" in shim
    # no physics here: the shim never calls a stepping or dynamics function by itself, only forwards what it is asked
    assert not re.search(r"_mj\.mj_(step|forward|inverse|kinematics)\(", shim)
    worker = (SITE / "runtime" / "worker.js").read_text()
    assert "registerJsModule('_mujoco_js'" in worker
