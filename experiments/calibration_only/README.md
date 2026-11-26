# Calibration-only identification (off-score)

A feedforward correction fitted to two generated UR5e calibration tapes reduced tool tracking error on both independent validation tapes. The six fits used 798 moving host observations in total. Each fit had rank 9 of 9, with unregularized condition numbers of 365–396. [Compact evidence](evidence.json)

| Validation seed | Unfitted tool RMS | Fitted tool RMS | Fitted worst stop | Fitted gates |
|---|---:|---:|---:|---:|
| 3141 | 1.840319 mm | 0.593634 mm | 0.661254 mm | 5/5 |
| 3241 | 1.548145 mm | 0.307908 mm | 0.320481 mm | 5/5 |

The experiment uses the same 50 Hz host timing, board gains and given 10%-error dynamics for both runs. The calibration wrapper supplies the kinematic tape and captures the exact `JointState` delivered to each controller tick. The fit aligns the reference to each message’s sample timestamp and learns a residual from the PD error. The evaluator keeps the plant handle and uses the existing tracking metrics and gates. [Fit and controller](calibration_model.py) · [Simulator runner](calibration_offscore.py) · [Boundary and gates](../../OBJECTIVES.md)

This evidence covers two local training motions and two validation motions around different poses, within 11° of their respective centres. The oscillator band is configured at 0.2–1.6 Hz. The result establishes that a separate calibration fit can improve tracking on these simulated motions. Transfer across the full UR5e workspace, to the ranked benchmark, and to hardware remains unmeasured.

## Reproduce

Run with the box’s existing bench environment and a sibling checkout of [robot_trajectories](https://github.com/zacharyyamaoka/robot_trajectories). The proof uses its stock multisine, hold and concatenation generators and the stock episode loop from [robot_controllers](https://github.com/zacharyyamaoka/robot_controllers).

```bash
env PYTHONPATH="$HOME/robot_trajectories/src" "$HOME/trajectory_tracking_agent/.venv/bin/python" "$HOME/trajectory_tracking_agent/experiments/calibration_only/calibration_offscore.py" --output "$HOME/trajectory_tracking_agent/outputs/loop-calibration/reproduced.json"
```

The command writes a compact summary with coefficients, observation counts, tape hashes, metrics and gate outcomes. Two fresh runs on the verified environment produced byte-identical summaries. Provenance · Codex (calibration feasibility lane), trajectory tracking base `da81ec5`, robot_trajectories `e2cdd76`, robot_controllers `3159fe9`, robot_msgs `8827f5f`.
