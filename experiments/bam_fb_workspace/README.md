# BAM FB workspace tracking

This off-score benchmark uses the existing `bam_fb/workspace/v2` development and holdout tapes from arm_motion_bench, with all six actuated drives and the composed arm's claw-tip tool point. The matched highest rung is 1.0. The frozen tapes include the whole workspace tour and every hold.

The initial stock replay records the existing JTC gains and idealized feedforward as a reference. The candidate prediction is that the same six-drive deployment with a public, perturbed load model and calibration from joint/torque observations reduces full-tape error. Calibration may use archived development observations. The conveyor and workspace will share one locked candidate. The existing detector and admission checks remain visible independently of the tracking targets.
