---
id: fb-604bdf7e
polarity: negative
added: 2026-11-24
from: Zach
filed_by: claude-code (dispatcher lane FS)
model: claude-opus-5-5
words: exact
tracks: [trajectory-tracking-agent]
specs: [O1.1, O4.1]
source: [OBJECTIVES.md]
reacting_to: "arm_motion_bench's contract, amended v3.1 to v3.16 in four days"
became: 09e3ba7
---

# Freeze the API and the metrics before looking inside

## Observed

BEFORE I even take a look at kind what is going on inside … finalize the API, what is going in and out, what are the
evaluation metrics, and how are they calculated.

## Desired

## Why

> [!ai] claude-code (lane FS), from OBJECTIVES.md
> These words are the WHY for freezing ruler v1, quoted at the top of OBJECTIVES.md. The same line gives the evidence:
> the arm_motion_bench contract was amended 16 times in four days, and two benches scored the same UR5e about 1000×
> apart because they drew the boundary in different places. It became OBJECTIVES.md (commit 09e3ba7): the boundary
> ([O1.1](../specs/O1.1-the-boundary.md)), the objective and how it is calculated
> ([O4.1](../specs/O4.1-objective-tool-track-rms.md)), and the gates, all fixed before any agent-written solution.
