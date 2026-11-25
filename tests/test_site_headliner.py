"""The landing page leads with the Ticker v1 headliner, fed by a current state.json. WHY (Zach, 2026-11-24, picking
Ticker v1 among the headliner proposals): "this chart as the headline, we just want to see it's basically progressing"
(feedback/2026-11-24-chart-as-the-headline.md; the retired site/index.html carried the quote until 2026-11-25).

Since 2026-11-25 (lane PKG) the landing is blackbox_agent's stock one (`blackbox build`): the Ticker loads from the
package's viewer, never a box copy (site/vendor/bb-headliner.js is gone), and the saved-run explainer takes the hero
when the playback slice lists runs, the Ticker moving below it to Progress. `test_the_page_loads_the_headliner_first`
became `test_the_stock_landing_loads_the_headliner_and_puts_the_runs_first`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trajectory_tracking_agent import ledger

SITE = Path(__file__).resolve().parents[1] / "site"


def test_the_stock_landing_loads_the_headliner_and_puts_the_runs_first() -> None:
    blackbox_site = pytest.importorskip("blackbox_agent.site", reason="the `site` extra: uv run --all-extras")
    html = (blackbox_site.TEMPLATE / "site" / "index.html").read_text()
    assert '<script type="module" src="dashboard/viewer/src/components/bb-headliner.js">' in html
    assert (blackbox_site.COMPONENTS / "bb-headliner.js").is_file() and (blackbox_site.COMPONENTS / "bb-evidence.js").is_file()
    assert not (SITE / "vendor" / "bb-headliner.js").exists() and not (SITE / "index.html").exists()
    # the hero: the Ticker until the playback slice lists runs, then <bb-evidence> with the Ticker moved to Progress
    assert html.index('id="hero"') < html.index("<bb-headliner") < html.index('id="progress"') < html.index("<bb-gates")
    assert "progress.append(document.getElementById('headliner'))" in html and "hero.replaceChildren(ev)" in html


def test_state_json_is_the_ledgers_best() -> None:
    state = json.loads((SITE / "data" / "state.json").read_text())
    assert state["schema"].startswith("bb-state/"), state["schema"]
    best = next(k for k in state["kpis"] if k["id"] == "best")
    top = ledger.best()
    assert abs(best["value"] - top["objective"]) < 1e-12, "site/data/state.json is stale: run tools/build_site.py build"
