---
id: fb-976d2723
polarity: negative
added: 2026-11-24
from: Zach
filed_by: claude-code (dispatcher lane FS)
model: claude-opus-5-5
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: []
source: [src/trajectory_tracking_agent/cli.py, tests/test_solutions_provenance.py]
reacting_to: "17 of 18 generation-1 solutions recording no proposer"
became: "78b84bd"
---

# Every solution names the agent and model that proposed it

## Observed

With the proposer optional in `tta new`, 17 of 18 generation-1 solutions recorded no agent or model.

## Desired

AI output says which agent and model wrote it: his provenance rule, applied to every solution.

## Why

> [!ai] claude-code (lane FS), from cli.py and tests/test_solutions_provenance.py
> `tta new` now refuses to run without `--agent` and `--model` (or TTA_AGENT / TTA_MODEL); the 17 were backfilled from
> the commit that added each (78b84bd); `tests/test_solutions_provenance.py` fails on an empty proposer. A build-contract
> rule (CONTRACT §2's `proposed_by`), not an OBJECTIVES.md requirement, so `specs: []`.
