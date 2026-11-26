# BAM FB workspace tracking

This off-score benchmark uses the existing `bam_fb/workspace/v2` development and holdout tapes from arm_motion_bench, with all six actuated drives and the composed arm's claw-tip tool point. The matched highest rung is 1.0. The frozen tapes include the whole workspace tour and every hold.

The initial stock replay records the existing JTC gains and idealized feedforward as a reference. The candidate prediction is that the same six-drive deployment with a public, perturbed load model and calibration from joint/torque observations reduces full-tape error. Calibration may use archived development observations. The conveyor and workspace will share one locked candidate. The existing detector and admission checks remain visible independently of the tracking targets.

## Moving feedback trial

The [twofold moving-gain profile](gains-moving-twofold.json) changes moving stiffness and damping while keeping the absolute hold gains. Predict that it cuts the largest full-tape errors caused by uncompensated moving torque, with no improvement expected in steady held error. The controller retains the same feedforward fit, torque caps, target tapes, and detector.

The [cross-axis feature trial](cross_axis.py) adds an observed correction for J2 and C1. Predict that coupling terms reduce the full-trace error on development tasks where one drive is nearly stationary while the other accelerates. The correction vanishes at rest.
