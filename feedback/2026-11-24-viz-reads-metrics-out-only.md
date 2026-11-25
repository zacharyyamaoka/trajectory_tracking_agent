---
id: fb-974bf6f2
polarity: negative
added: 2026-11-24
from: Zach
filed_by: claude-code (dispatcher lane FS)
model: claude-opus-5-5
words: exact
tracks: [trajectory-tracking-agent]
specs: []
source: [site/proposals/_build/build_data.py, tools/population_views.py]
reacting_to: "the five proposals for showing what the metrics mean (lane P)"
became: "53e6e66"
---

# The viz reads the metrics out, never the solution

## Observed

KEY OF COURSE IS THAT THE BLACKBOX VIZ IS NOT RELATED TO THE SOLUTION ONLY TO THE METRICS OUT

## Desired

## Why

> [!ai] claude-code (lane FS), from site/proposals and tools/population_views.py
> Every view of this agent reads only what comes out of the black box: the ledger, the scorecards and the saved run
> records (the target, the measured joints and torques, the deployment, the ruler's numbers), never a `solution.py` or a
> controller's own command. First applied in the five metric proposals (53e6e66), then in the population views (9161ac9);
> `tests/test_population_views.py::test_views_never_read_solution_code` holds the views to it. It is about the pages, not
> the score, so no OBJECTIVES.md requirement covers it (`specs: []`).
