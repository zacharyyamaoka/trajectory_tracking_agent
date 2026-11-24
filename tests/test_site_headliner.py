"""The landing page leads with the Ticker v1 headliner (Zach's pick, 2026-11-24), fed by a current state.json."""

from __future__ import annotations

import json
from pathlib import Path

from trajectory_tracking_agent import ledger

SITE = Path(__file__).resolve().parents[1] / "site"


def test_the_page_loads_the_headliner_first() -> None:
    html = (SITE / "index.html").read_text()
    assert (SITE / "vendor" / "bb-headliner.js").exists()
    assert '<script type="module" src="vendor/bb-headliner.js">' in html
    assert html.index("<bb-headliner") < html.index('class="stage"'), "the headliner sits above the playback"


def test_state_json_is_the_ledgers_best() -> None:
    state = json.loads((SITE / "data" / "state.json").read_text())
    assert state["schema"].startswith("bb-state/"), state["schema"]
    best = next(k for k in state["kpis"] if k["id"] == "best")
    top = ledger.best()
    assert abs(best["value"] - top["objective"]) < 1e-12, "site/data/state.json is stale: run tools/build_site.py build"
