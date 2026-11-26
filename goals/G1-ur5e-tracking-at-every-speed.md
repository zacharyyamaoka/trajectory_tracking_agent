---
vibe-goal: UR5e tracking at every speed
vibe-done-when:
  - kpi:ur5e_worst_stop_error_mm < 0.5
  - kpi:ur5e_worst_full_trajectory_rms_mm < 1.0
vibe-target: 2026-11-25T22:27:33-07:00
tier: must
set: 2026-11-25T19:27:33-07:00
---

Aim for a worst stop error below 0.5 mm and a full-trajectory tool-position RMS below 1.0 mm on every UR5e trajectory at every tested speed. Take the maximum of each quantity across the complete trial matrix for the same controller revision. These are performance targets for the three-hour goal. The ruler determines admissibility independently.

Start with the 42 frozen upright workspace dev paths and the frozen 30-pick portal conveyor cycle, each at fractions 0.1, 0.2, …, 1.0. Confirm the locked controller on the existing 12 upright holdout paths over the same fractions. Hardware validation is a separate stage. Compare the target and measured TCP at the same 100 Hz instants with the TCP defined by that deployment.

Keep the frozen stop definition for each run. A stop is a target rest of at least 0.2 s, and its error is the target TCP versus the mean measured TCP over its last 0.1 s. RMS uses every sample from the first target instant through the last, including every hold. Missing runs, invalid samples, or an unmeasured stop leave the data incomplete. Publish the two maxima together against one replay revision after measuring the whole matrix. Report deployment gate results alongside the measurements.

The frozen ruler continues to rank upright speed-1.0 trials by its moving-sample median. The new benchmarks belong in [goal measurements](metrics.json).
