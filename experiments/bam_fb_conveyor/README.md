# BAM FB conveyor tracking

The existing arm_motion_bench conveyor v2 dataset is a six-drive, home-to-home pick-and-place curriculum for the BAM FB with its closed five-bar, wrist, and claw. It contains 48 development and 16 reporting-only holdout trajectories, evenly split between stationary and moving picks. Use the native Ruckig 1.0 tape for every trajectory. The arm's separately owned benchmark revision determines the fixture and controller provenance. This experiment is outside the UR5e ranked ledger.

The performance targets are below 0.5 mm at the worst measured stop and below 1.0 mm synchronous whole-trajectory TCP RMS. At a rest of at least 0.2 s, the stop metric uses the final 0.1 s. The live simulator samples the claw site on the reference clock. Legacy encoder and closure FK remains a separate diagnostic. Simulator faults, contacts, and detector reactions are recorded separately from the performance measurements.

**Prediction before replay.** On the frozen 1.0 tapes, the unchanged default `record` baseline will miss at least one performance target. Its configured feedback gains and measured-pose gravity term leave friction and tracking lag uncompensated. The published `jtc_baseline` profile may improve tracking with its previously defined controller gains. Its nominal-model and detector-calibration provenance is part of the result.

The simulation fixture is the stock mounted BAM arm from arm_motion_bench. The simulated rig's contact geometry models the drawn belt and support rails, with the benchmark's reduced tip contact model. The 80 mm planning rims and receiving bins are curriculum records. This replay measures arm motion and does not establish payload delivery on the W3 rail-mounted workcell.

## Baseline evidence

[Baseline results](baseline.json) record matched full-speed measurements for all 48 dev routes per profile. Fresh `record` replays reproduced the archived stop and RMS errors, gate verdicts and detector decisions exactly. The strongest stock profile reached 0.374 mm at the worst stop and 1.543 mm worst full-trajectory RMS. Its 48 runs passed the existing gates. The [review](review.html) links to matched playback through the stock Trajectory Comparison viewer when served with its review assets.

The [scorer](score.py) checks every native tape and FK cache against the frozen manifest, verifies the recorded reference arrays against their corresponding native tape, and reports the five run gates and dataset false-alarm gate independently. An interrupted recording supplies no complete-tape measurement. Legacy traces have encoder and closure FK only. Replays with the synchronous simulated site use its position with the encoder measurement retained separately.

A [fresh native Ruckig regeneration](target-regeneration.json) reproduced all 256 frozen tape and FK payloads and matched the station, tasks, and rejection records exactly.

Set `BENCH` to the arm_motion_bench checkout and `TRAJ_COMPARE` to the stock Trajectory Comparison checkout. Use their existing environments and pass one controller directory to the scorer. Keep raw records under the output root.

```sh
PYTHONPATH=src "$BENCH/scripts/bam_fb_python.sh" experiments/bam_fb_conveyor/score.py "$BENCH/datasets/bam_fb/conveyor/v2" "$BENCH/outputs/runs/bam_fb/hold_friction_v2/conveyor-v2" outputs/bam-fb-conveyor/hold_friction_v2.json
PYTHONPATH="$TRAJ_COMPARE/src:src" "$BENCH/scripts/bam_fb_python.sh" experiments/bam_fb_conveyor/report.py "$BENCH/datasets/bam_fb/conveyor/v2" "$BENCH/outputs/runs/bam_fb" outputs/bam-fb-conveyor/comparison.html outputs/bam-fb-conveyor/hold_friction_v2.json --tasks conveyor-dev-013 conveyor-dev-034
```

## Development pilot

Compare the shared public-model candidate with a 50% increase in moving feedback stiffness and the corresponding square-root increase in damping. Keep effective hold gains, feedforward, detector thresholds and every target tape fixed. The pilot uses four dev cases, `conveyor-dev-000`, `conveyor-dev-013`, `conveyor-dev-034` and `conveyor-dev-038`. They include both belt modes and the strongest stock profile's worst stop and RMS cases. Predict lower full-trajectory RMS on at least three cases. Treat a new collision, closure fault, saturation or false detector reaction as evidence against the gain variant. Holdout stays untouched until the shared BAM FB controller is locked.

The first pilot reduced RMS by 22–28% on all four cases. All passed the existing gates. The new 0.5 mm stop target was missed at the 0.20 s release holds. During their final 0.1 s, residual errors stayed around 0.6–0.8 mm while the wrist and five-bar remained near rest. The final 0.50 s holds stayed below 0.41 mm. Next, test twice the effective hold stiffness with square-root damping at the same moving gains, with a prediction that the 0.20 s worst-stop result returns below 0.5 mm. Then try lifting moving stiffness to three times stock under the same new absolute hold gains; predict a further RMS reduction on at least three cases. Both checks retain the exact reference and existing gates.

With three times stock moving stiffness and eight times stock effective hold stiffness, all four cases passed their stop target and existing gates. Two passed the full-trajectory RMS target. Worst full-trajectory RMS was 1.595 mm on `conveyor-dev-038`. Test moving stiffness at five and eight times stock while keeping absolute hold gains fixed. Predict at least three RMS improvements at the five-times rung. The eight-times run probes whether the remaining improvement is available without a limit, contact, torque or detector regression. It is a simulation gain probe.

## Locked simulation results

The eight-times stiffness profile passed 48 of 48 conveyor development routes and 42 of 42 workspace development routes at native 1.0. The [same controller was locked for both datasets](controller-lock.json) before opening either holdout. It then passed 16 of 16 conveyor holdout routes. The [complete conveyor audit](candidate-evidence.json) records 0.451645 mm worst stop error and 0.813833 mm worst full-trajectory RMS. All 64 runs passed the stock per-run gates, with zero false alarms on the armed detector. The encoder-FK diagnostic independently measured worst values of 0.451666 mm and 0.737281 mm using those same traces.

The eight-times profile is a simulation result. The [shared controller source](../bam_fb_workspace/candidate.py) evaluates a public rigid-body model with a residual fitted to development joint position and torque observations. The plant retains its collision and torque rules. The measured position for the goal is the simulator's claw site on the exact target clock.

The [gallery](review.html) shows the full-speed result with recorded stock Trajectory Comparison playback, downloadable scores, and the controller lock. The live comparison shows the target, both stock baselines, and the locked replay on the same timeline.

## Locked controller sensitivity

The [eight-trial pilot](sensitivity-evidence.json) used the first two seeded benchmark repeats on four development routes, including the nominal development worst cases for stop and RMS error. Each repeat combines six-axis friction perturbation within ±10%, an initial joint offset up to 0.05°, and encoder noise. All eight passed both targets and the existing run gates. Worst stop error was 0.437 mm and worst full RMS was 0.808 mm. The pilot covers those sampled simulator conditions. Gearbox backlash and external TCP metrology are separate tests.
