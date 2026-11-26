# BAM FB workspace tracking

This off-score benchmark uses the existing `bam_fb/workspace/v2` development and holdout tapes from arm_motion_bench, with all six actuated drives and the composed arm's claw-tip tool point. The matched highest rung is 1.0. The frozen tapes include the whole workspace tour and every hold.

The [frozen inventory audit](workspace-freeze-audit.json) verifies 324 tape and TCP cache checksums. Both splits chain from home back to home at each endpoint. The stock dataset `verify` also regenerated the workspace without differences. The [recording audit](audit.py) checks complete target clocks, positions, velocities, accelerations, and TCP positions against this corpus. Each score retains the plant and controller references and the independent stock gate verdicts.

The initial stock replay records the existing JTC gains and idealized feedforward as a reference. The candidate prediction is that the same six-drive deployment with a public, perturbed load model and calibration from joint/torque observations reduces full-tape error. Calibration may use archived development observations. The conveyor and workspace will share one locked candidate. The existing detector and admission checks remain visible independently of the tracking targets.

## Moving feedback trial

The [twofold moving-gain profile](gains-moving-twofold.json) changes moving stiffness and damping while keeping the absolute hold gains. Predict that it cuts the largest full-tape errors caused by uncompensated moving torque, with no improvement expected in steady held error. The controller retains the same feedforward fit, torque caps, target tapes, and detector.

The [cross-axis feature trial](cross_axis.py) adds an observed correction for J2 and C1. Predict that coupling terms reduce the full-trace error on development tasks where one drive is nearly stationary while the other accelerates. The correction vanishes at rest.

Replay the [calibrated controller](candidate.py) with frozen [parameters](public-calibration.json). The [eightfold moving and hold gains](../bam_fb_conveyor/moving-800-hold-800.json) are a shared workspace and conveyor variant. It needs the composed bench's reference-only feedforward callback and synchronous TCP capture in arm_motion_bench commit `7a3bdc2`.

```bash
PYTHONPATH="src:${ROBOT_CONTROLLERS}/src" "$ARM_MOTION_BENCH/scripts/bam_fb_python.sh" experiments/bam_fb_workspace/candidate.py run --dataset "$ARM_MOTION_BENCH/datasets/bam_fb/workspace/v2" --parameters experiments/bam_fb_workspace/public-calibration.json --gains-json experiments/bam_fb_conveyor/moving-800-hold-800.json --name public-calibrated-x8hold8 --output outputs/bam-fb-workspace/reproduction --workers 1
PYTHONPATH=src "$ARM_MOTION_BENCH/scripts/bam_fb_python.sh" experiments/bam_fb_workspace/audit.py "$ARM_MOTION_BENCH/datasets/bam_fb/workspace/v2" outputs/bam-fb-workspace/reproduction --controller public-calibrated-x8hold8 --acquisition synchronous-tcp --output outputs/bam-fb-workspace/reproduction-dev.json
```
