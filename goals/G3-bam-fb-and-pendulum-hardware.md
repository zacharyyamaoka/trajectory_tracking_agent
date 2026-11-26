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

The [archive audit](../experiments/physical_tracking/archive-evidence.json) records the historical encoder estimates and the coverage and clock gaps. It does not supply a goal measurement.

The archived [CAN 11 plan preflight](../experiments/physical_tracking/pendulum-preflight.json) verifies the stock plan parser and limits checker with devices disabled. The [sampling study](../experiments/physical_tracking/camera-sampling-evidence.json) quantifies how the historical camera cadence affects RMS even with ideal positions and timestamps.

The standing BAM FB bench rule caps sped-up physical tapes at rung 0.25 and caps each measured joint speed independently. The [stock speed preflight](../experiments/physical_tracking/bam-fb-speed-preflight.json) covers all 54 workspace and 32 static conveyor tapes at 0.25. The 32 moving-belt routes exist at rung 1.0 only. Record the fully covered admitted physical rung with the owner and preserve the simulation corpus. Any capped pilot remains partial qualification until the matching moving-belt routes and run evidence exist.

Start physical qualification on CAN 11 once the owner clears the shared supply and confirms the rack configuration. Begin at 0.1, step up through the owner's commissioned ladder, and record bus-voltage peaks and regen-clamp behavior at each step, as requested for the 36 V installation. Keep concurrent BAM FB motion at or below 0.2 during that ladder. Calibrate the mounted D405's exposure clock and load-side tool frame against independent references before scoring its recordings.
