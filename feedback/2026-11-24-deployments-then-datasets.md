---
id: fb-f04bee0c
polarity: positive
added: 2026-11-24
from: Zach
filed_by: claude-code (lane CV)
model: claude-opus-5-5
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: []
source: [tools/build_coverage.py, tests/test_coverage_pages.py]
reacting_to: "the UR5e trajectory coverage workbench (traj_compare) living outside this site"
---

# Pick a deployment, then see its datasets' coverage

## Observed

The coverage workbench he uses for the UR5e datasets is a separate page; on this site there is no way to see all the
datasets of one deployment, and datasets can only be compared within the same kind of deployment.

## Desired

Pages left to right across the top (landing, dashboard, models × datasets, then datasets): first a stock data-ui table
of deployments with a gallery grouped by deployment type (a heading per type, picture tiles, as McMaster-Carr's
catalogue); clicking a type or a deployment opens the coverage of its datasets, filtered to it. The coverage viewer is a
stable part, dropped in, never copied.

## Why

> [!ai] claude-code (lane CV), from tools/build_coverage.py and tests/test_coverage_pages.py
> `site/deployments/` (one row per robot, deployment and dataset; every number read from the file its row names) and
> `site/datasets/ur5e/` (traj_compare's `write_workbench` over the ruler's dataset, its files as it writes them); the
> stage bar is `site/stages/`. Rows not in ruler v1 stay listed and greyed with their OBJECTIVES §5 reason. About the
> pages, not the score, so `specs: []`.
