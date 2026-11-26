---
id: fb-5c0e9a37
polarity: negative
added: 2026-11-25
from: Zach
filed_by: claude-code (dispatcher lane MXD-ALL)
model: claude-opus-5-5
words: exact
tracks: [trajectory-tracking-agent]
specs: []
source: [tests/test_dropins.py, tools/build_dropins.py]
reacting_to: "the Model × Dataset Leaderboard, which showed only ur5e_alone › workspace/v2 dev and holdout"
became: "905b842"
---

# Every measured dataset is a column, and the rail filters columns too

## Observed

on the leaderboard view, Codex says it has added a new dataset but I don't see it here

in the left filter bar I can filter by family, models etc so lots of filters on the rows, but no filters on the columns! I should be able to select which different datasets etc I want to be comparing it on.

## Desired

## Why

> [!ai] claude-code (dispatcher lane MXD-ALL), from tools/build_dropins.py
> "The new dataset" was the 30-pick portal conveyor cycle (experiments/conveyor_cycle), flown at speed fractions
> 0.1…1.0 by the unchanged controller (parent-results.json) and the mount-aware one (goal G1). The page read one
> hard-coded dataset, the scorecards' `workspace/v2`, so it never showed it, nor the speed study, G1's upright sweep or
> W3's loaded check. Now every measured per-task result is a row with its ruler, deployment, speed, dataset and split;
> each source is its own column group marked off-ruler (the Leaderboard still ranks on ruler v1's dev), and the rail's
> Ruler, Dataset, Split, Speed fraction and Task kind facets pick the columns. G1's per-run summaries were only in
> gitignored outputs/, so they are committed under goals/G1-runs/, each checked against the sha256 the G1 evidence file
> already names.
