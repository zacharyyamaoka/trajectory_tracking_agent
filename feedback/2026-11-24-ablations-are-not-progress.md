---
id: fb-946a295e
polarity: negative
added: 2026-11-24
from: Zach
filed_by: claude-code (dispatcher lane FS)
model: claude-opus-5-5
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: [O4.9]
source: [tools/progress_chart.py, src/trajectory_tracking_agent/ledger.py, tests/test_ablation_tags.py]
reacting_to: "PROGRESS.md counting the ablation study's variants as admissible solutions"
became: f806e8a
---

# Ablation variants are not search progress

## Observed

PROGRESS.md said "61 of 64 admissible", counting the ablation study's 30 variants as if they were search steps.

## Desired

An ablation study measures what a finished line's parts were worth; its variants stay off the progress chart, the
population views, the best and the counts, and each view says how many it left out.

## Why

> [!ai] claude-code (lane FS), from tools/progress_chart.py, ledger.py and tests/test_ablation_tags.py
> The repo states the rule as Zach's (2026-11-24): "ablation variants must not read as search progress". The chart and
> the views leave `ablation`-tagged solutions out and count them (79b2625); the ledger leaves them out of the best,
> PROGRESS.md and status.json (f806e8a). That narrows how [O4.9](../specs/O4.9-ranking.md)'s *best* is read without
> changing the ruler. `tests/test_ablation_tags.py` and `tests/test_ledger_ablation.py` hold it.
