---
id: fb-deacaaaa
polarity: positive
added: 2026-11-24
from: Zach
filed_by: claude-code (pick-trajgen box agent)
model: claude-opus-5-5
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: []
source: [tests/test_finds_hold.py]
reacting_to: "what the search found on its own: the secant velocity with the calibrated lookahead"
became: "43a958b"
---

# The secant lookahead was a real find

## Observed

What the search turned up on its own, the secant lookahead among others, was the impressive part.

## Desired

## Why

> [!ai] claude-code (pick-trajgen box agent), from tests/test_finds_hold.py
> A find is worth keeping only while it stays true, so [`tests/test_finds_hold.py`](../tests/test_finds_hold.py)
> re-scores it live on today's code instead of reading it back from the ledger. On dev, the secant velocity beats the
> tangent on each of generation 0's six twins (`p2`/`p2s` … `p7`/`p7s`). The calibrated lookahead beats the datasheet's
> (`p3s`/`p4s`). Each pair differs in that one ingredient only, which the test checks from the tags in `meta.json`. A
> change in robot_controllers or the deployment that quietly undid either find turns it red.
