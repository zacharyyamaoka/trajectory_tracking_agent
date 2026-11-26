# BAM FB geared transfer prediction

Recorded before geared replays. Fixed simulation-only dev panel at speed rung 1.0 and repeat 0.

| Route | Reason for inclusion |
| --- | --- |
| `workspace-dev-000` | First workspace dev route, a parity control |
| `workspace-dev-038` | Highest nominal full-trajectory tool RMS in workspace dev |
| `conveyor-dev-018` | Highest nominal stop error in conveyor dev |

The controller, stop windows, target clock, CAD claw site and working five-bar branch are fixed. The controller stays locked at `4cdb58a73b9bec97bce825eff27b8618ee4b1f30232d0370b861ce598138c13f`, with the stock collision detector armed. This is a separate perturbation outside the frozen ranking and qualification.

1. The zero-gap control will preserve the claw frame and contact/closure evidence, with at most 0.00001 mm TCP difference over every sample versus archived nominal trajectories. Require the same target positions, clock and stops, plus intact arm geometry. Run this condition first.
2. Import the six synthetic gap and gear-stiffness inputs of Sim2Real's full-arm homing B2 implementation, and apply stock `gear_backlash.BacklashModel` to the tracking model because the homing model has no claw scoring site. Center the zero only for this stress condition. Placing the nominal hard five-bar friction and switched wrist friction on the output side preserves their magnitudes. A real arm might have gravitational flank calibration or different gaps.
3. Relative to zero gap, predict at least one route's true full-trajectory RMS will rise by 0.10 mm or more, and at least one route will miss either <0.5 mm max stop or <1.0 mm full RMS. Predict that at least one route's motor-encoder-derived TCP will underestimate the actual claw RMS by at least 0.10 mm. An armed detector trip, change of assembly, or invalid sample is a stress failure and must be reported alongside any resulting trace. Track nominal plus B2 at transport parity. Add a B2 condition at the stock bench's existing 1.25× friction variant only after those conditions.

Agent: Codex `/root/bam_fb_geared`. Controller selection was completed before this experiment. No real actuation or hardware-derived gap identification is part of this experiment.
