---
id: fb-2d7a91c4
polarity: negative
added: 2026-11-25
from: Zach
filed_by: claude-code (dispatcher)
model: claude-opus-5-5
words: exact
tracks: [trajectory-tracking-agent]
specs: []
source: [tools/build_dropins.py, site/models-datasets/models-datasets.base]
reacting_to: "the live Model × Dataset page after the leaderboard pivot was merged in data-ui"
became: "344cfd3"
---

# A merged view is not shipped until the live page shows it

## Observed

I am looking at the model x dataset here on the public landing page but I don't see it being updated! what happaned?

## Desired

## Why

> [!ai] claude-code (dispatcher), from tools/build_dropins.py
> The leaderboard pivot (Leaderboard / Pivot / Rows, data-ui CONTRACT §57) was merged in data-ui's own gallery, and the
> handoff said it would go into this page "after", without saying that step had not started. The live page still ran
> the previous pivot. Fixed in 344cfd3: the page is built on §57 from today's scorecards (tests/test_dropins.py checks
> the default view is Leaderboard and every cell against its scorecard). Rule kept: a view change is done when the live
> page shows it, checked in a browser after the deploy, not when the library merges it.
