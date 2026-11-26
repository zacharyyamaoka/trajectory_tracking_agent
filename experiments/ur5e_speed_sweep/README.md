# UR5e speed study

Five configurations, 42 matched dev targets, and ten nominal fractions from 0.1 to 1.0. This study uses simulation and sits outside the frozen ranking. At 1.0 it uses the original tapes. Other fractions stretch those profiles and resample at 100 Hz. The last interval can add up to 0.01 seconds to reach the physics-aligned grid.

```bash
uv run --all-extras python experiments/ur5e_speed_sweep/run.py --output outputs/ur5e-speed-sweep/full.json --workers 8
uv run --all-extras python experiments/ur5e_speed_sweep/summarize.py outputs/ur5e-speed-sweep/full.json experiments/ur5e_speed_sweep/study.json
uv run --all-extras python experiments/ur5e_speed_sweep/limits_audit.py --output experiments/ur5e_speed_sweep/limits.json
uv run --all-extras python experiments/ur5e_speed_sweep/report.py
```

The summary verifies the task-level scores and gate verdicts at 1.0 against the frozen scorecards. `study.json` carries the matched scalar observations and time spent at different joint speeds. `limits.json` records the independently audited original tapes. The optional `--arm-motion-bench` path checks the generator’s original five native timing rungs against its manifest. Those tapes use the generator’s per-rung kinematic limits. The ten evenly spaced fractions in this study use time dilation of the 1.0 profile.

Comparison reads the study’s scalars for the speed curves. The full-speed Targets and Runs workbench opens the recorded frozen runs. The heatmaps and the nominal-speed distribution in Coverage describe the same 54 frozen full-speed tapes. Read the [report](https://zacharyyamaoka.github.io/trajectory_tracking_agent/reports/ur5e-speed-sweep.html), [speed sweeps](https://zacharyyamaoka.github.io/trajectory_tracking_agent/comparison/#/sweeps), [trajectory speed scale](https://zacharyyamaoka.github.io/trajectory_tracking_agent/datasets/ur5e/#tab=trajectory-speed-scale) or [Targets workbench](https://zacharyyamaoka.github.io/trajectory_tracking_agent/comparison/workbench/#tab=targets).
