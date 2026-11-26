---
vibe-goal: BAM FB and pendulum tracking in simulation
vibe-done-when:
  - kpi:bam_fb_workspace_sim_worst_stop_mm < 0.5
  - kpi:bam_fb_workspace_sim_worst_full_rms_mm < 1.0
  - kpi:bam_fb_conveyor_sim_worst_stop_mm < 0.5
  - kpi:bam_fb_conveyor_sim_worst_full_rms_mm < 1.0
  - kpi:pendulum_workspace_sim_worst_stop_mm < 0.5
  - kpi:pendulum_workspace_sim_worst_full_rms_mm < 1.0
vibe-target: 2026-11-26T04:29:48-07:00
tier: must
set: 2026-11-25T20:29:48-07:00
---

Reach both tracking targets at the highest declared speed rung across each full frozen corpus in simulation. Start with BAM FB's workspace and conveyor pick-and-place, and independently cover the shoulder pendulum workspace. Each device uses one locked controller revision across its datasets. Use the declared tool point and compare positions in metres at matched target and measured instants. Full-trajectory RMS includes holds. Each stop is a target rest of at least 0.2 s, scored over its final 0.1 s as in the [UR5e goal](G1-ur5e-tracking-at-every-speed.md).

Record corpus manifests, deployment and twin revisions, the exact speed rung, measured run coverage, the two worst cases, and independent admission verdicts. Publish benchmark measurements only after scoring all required runs. Use development tapes to select candidates and lock them before reporting reserved holdout. Preserve the ranked UR5e [ruler](../OBJECTIVES.md). A simulation result does not supply a measurement for the [hardware goal](G3-bam-fb-and-pendulum-hardware.md).

The [combined evidence](G2-simulation-evidence.json) records all 170 runs, including 40 untouched holdout paths. The [BAM FB result](../experiments/bam_fb_transfer/qualification.json) uses one shared controller on the workspace and conveyor, and the [CAN 11 result](../experiments/pendulum_workspace/qualification.json) uses its own locked controller. Their board gain settings apply to these simulation runs. The [tracking review](../reports/bam-fb-pendulum/index.html) includes matched playback.
