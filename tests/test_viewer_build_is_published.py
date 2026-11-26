"""The site's viewers are built from committed, published traj_compare code (Zach, 2026-11-25, Vibe Tracks feedback
fb-8337cc64: "Ok right now I don't see our newer targets view..").

WHY: on 2026-11-25 the GitHub copy of the site still served the Comparison viewer from build a4c3c79, made from
uncommitted traj_compare code. Local main had the newer targets view, but nobody could see it there. A build from a
dirty or unpushed checkout can't be reproduced, and it hides the viewer that is actually on main.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
COMPARISON_BUILD = REPO / "site" / "comparison" / "build.json"
DATASETS_BUILD = REPO / "site" / "datasets" / "ur5e" / "build.json"
TRAJ_COMPARE = Path.home() / "traj_compare"
SHA = re.compile(r"^[0-9a-f]{7,40}$")


def _pins() -> dict[str, str]:
    comparison = json.loads(COMPARISON_BUILD.read_text())["made_by"]["traj_compare"]
    datasets = json.loads(DATASETS_BUILD.read_text())["traj_compare"]
    return {"comparison": comparison["commit"], "datasets": datasets}


def test_comparison_is_built_from_committed_traj_compare():
    made_by = json.loads(COMPARISON_BUILD.read_text())["made_by"]["traj_compare"]
    assert made_by["dirty"] is False, "rebuild site/comparison from a clean traj_compare checkout"
    assert SHA.match(made_by["commit"]), made_by


def test_every_page_uses_the_same_traj_compare_build():
    pins = _pins()
    assert all(SHA.match(sha) for sha in pins.values()), pins
    assert len(set(pins.values())) == 1, f"the pages use different viewer builds: {pins}"


def test_the_pinned_viewer_build_is_on_traj_compare_main():
    """Only checkable on a machine with the traj_compare clone; elsewhere the two checks above still hold."""
    if not (TRAJ_COMPARE / ".git").exists():
        pytest.skip("no ~/traj_compare clone here")
    for page, sha in _pins().items():
        known = subprocess.run(["git", "-C", str(TRAJ_COMPARE), "cat-file", "-e", f"{sha}^{{commit}}"],
                               capture_output=True)
        if known.returncode != 0:
            pytest.skip(f"{sha} not fetched into ~/traj_compare yet")
        published = subprocess.run(["git", "-C", str(TRAJ_COMPARE), "merge-base", "--is-ancestor", sha, "origin/main"])
        assert published.returncode == 0, f"{page} is built from traj_compare {sha}, which is not on origin/main"
