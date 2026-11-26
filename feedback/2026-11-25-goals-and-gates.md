---
id: fb-a0e8374c
polarity: negative
added: 2026-11-25
from: Zach
filed_by: Codex
model: gpt-6.2-sol
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: []
source: [goals/G1-ur5e-tracking-at-every-speed.md]
---

# Keep performance goals separate from gates

## Observed

The initial response described the requested UR5e tracking targets as strict per-run requirements.

## Desired

Set the requested performance as a goal with its own completion time. Keep the ruler's existing admission gates.

## Why

> [!ai] A goal tracks a result to reach. Ruler gates determine eligibility. A timed goal can use strict numeric target comparisons on a complete evidence set while the gate results remain independently visible.
