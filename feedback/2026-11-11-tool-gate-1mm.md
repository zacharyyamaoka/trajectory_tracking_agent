---
id: fb-1874f81f
polarity: negative
added: 2026-11-11
from: Zach
filed_by: claude-code (dispatcher lane FS)
model: claude-opus-5-5
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: [O4.3, O4.2]
source: [OBJECTIVES.md, src/trajectory_tracking_agent/ruler/gates.py]
reacting_to: "a standing rule from before this repo existed"
became: "09e3ba7"
---

# A 1 mm tool gate at every stop

## Observed

Zach set a standing 1 mm tool gate on 2026-11-11. This repo names it ("Zach's standing 1 mm tool gate") but does not
quote his words.

## Desired

At every stop, the tool ends within 1 mm of its target.

## Why

> [!ai] claude-code (lane FS), from OBJECTIVES.md §4 and ruler/gates.py
> Adopted into ruler v1 as the `stop_error_max_mm` gate, ≤ 1.0 mm over each stop's last 0.1 s
> ([O4.3](../specs/O4.3-gate-stop-error.md)), and as the band `completed` settles in at the trajectory's end
> (`evaluate.py`'s `SETTLE_BAND_MM`, [O4.2](../specs/O4.2-gate-completed.md)).
