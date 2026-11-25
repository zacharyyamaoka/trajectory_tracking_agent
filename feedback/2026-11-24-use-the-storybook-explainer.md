---
id: fb-63f894c7
polarity: negative
added: 2026-11-24
from: Zach
filed_by: claude-code (lane EV)
model: claude-opus-5-5
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: []
source: [site/README.md, site/index.html]
reacting_to: "the landing page's own 3D playback stage, score cards and joint plots"
---

# Use the explainer designed in the storybook

## Observed

The landing page still explains a run with its own 3D stage, score cards and joint plots, not the newer 3D
explanation designed in the viewer's Storybook.

## Desired

The landing page uses that newer 3D explanation.

## Why

> [!ai] claude-code (lane EV), from site/README.md
> The newer explanation is the blackbox_agent viewer's `bb-evidence` (Lens ↔ Recorder over one saved bb-run/1
> record). The page now plays one per (solution, task) the pickers choose: `tools/build_site.py` writes the records
> with the viewer's own fold and lists them in `site/data/state.json`; `tests/test_site_playback.py` checks that every
> option the pickers offer has a listed record that validates against the viewer's schema.
