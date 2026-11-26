---
vibe-goal: BAM FB and pendulum tracking on hardware
vibe-done-when:
  - kpi:bam_fb_workspace_real_worst_stop_mm < 0.5
  - kpi:bam_fb_workspace_real_worst_full_rms_mm < 1.0
  - kpi:bam_fb_conveyor_real_worst_stop_mm < 0.5
  - kpi:bam_fb_conveyor_real_worst_full_rms_mm < 1.0
  - kpi:pendulum_workspace_real_worst_stop_mm < 0.5
  - kpi:pendulum_workspace_real_worst_full_rms_mm < 1.0
vibe-target: 2026-11-26T20:29:48-07:00
tier: must
set: 2026-11-25T20:29:48-07:00
---

On the physical BAM FB and shoulder pendulum, reach the same two performance targets at each deployment's highest declared speed rung across the matched workspace and conveyor qualification corpora. Use one locked controller revision per device across its datasets. Record the as-built configuration, active speed limits, target tapes, acquisition timebase and the source and uncertainty of physical tool position. Score every trajectory sample, including holds, and use the same stop definition as the [simulation goal](G2-bam-fb-and-pendulum-simulation.md).

Use archived runs to establish baselines and identify models where provenance permits. A shorter ladder, unmatched stimulus, motor-side-only estimate that cannot observe downstream backlash, or gap in physical acquisition leaves the corresponding target unmeasured. Register the real bench and playback plan with its operator. Keep active recovery state and any motion admission checks separate from these measured performance targets.
