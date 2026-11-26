# Ideas (the queue)

Two lists. Each idea says what it should move and by how much. Cross a line off with the solution id that tried it;
never delete it.

## I'll try

- [x] Measure the worst stop and full-trajectory RMS across the matched UR5e workspace and conveyor runs, with one controller revision and all ten speeds in the report.
  - Goal: G1 · step 1
  - The locked mount-aware controller measured 0.268052 mm worst stop and 0.187768 mm worst full-run RMS across 550 simulations. [Evidence](goals/G1-ur5e-tracking-evidence.json) and [playback](reports/ur5e-accuracy/index.html).

- [x] ~~Host Coulomb feed-forward on the best gen-0 layout. Expect: tool RMS down where the joints reverse (real_kp2's lever on BAM FB, never tried on the UR5e here).~~ → done at plan time instead of the host (the plan knows the target velocity): `p5s-bus` (given Coulomb, once the lookahead stopped double-counting it) then `p5s-fric` / `p5s-fric2` (identified curves).
- [x] ~~Per-joint lookahead calibrated on dev tasks only, not on robot_controllers' calibration sweep. Expect: lag down, RMS down a little.~~ → derived instead of fitted: bus command delay − (encoder delay + one board tick), `p5s-bus-enc`; the dev regression's qd coefficient is ~0 on every joint after it, so there is nothing left to calibrate.
- [x] ~~Coulomb ff with the bus's own lookahead, not the calibration's~~ → `p5s-bus` 0.595 mm dev (holdout 0.534), admissible. The calibration folds friction lag into the wrists' lookahead (+3.75/+4.5 ms); p5s then compensated friction twice. With Coulomb in the ff, lookahead = bus delay.
- [x] ~~Take the board's own lead out of the lookahead~~ → `p5s-bus-enc` 0.393 mm dev (holdout 0.332), admissible. The board walks its setpoint one tick (0.25 ms) before using it and closes on a 0.5 ms-old position, so its PD balances 0.75 ms ahead; every joint led by 0.042-0.046 deg per rad/s, now ~0.
- [x] ~~Identify per-joint Coulomb + viscous from dev run records~~ → `p5s-fric` 0.245 mm dev (holdout 0.278), admissible. wrist_2's friction is soft (vs 0.2 rad/s), wrist_3 has ~none; the given Coulomb over-pushed both. w2 error 0.121 → 0.015 deg.
- [x] ~~Move the position target off the chord (−a·T²/12)~~ → `p5s-chord` 0.244 mm dev (holdout 0.283), admissible. qdd coefficient −0.0019 deg per rad/s² on every joint as predicted; tool median only −0.6 % (mean −2.5 %).
- [x] ~~Identify the gravity error from the *joint errors*~~ → `p5s-grav` 0.097 mm dev (holdout 0.126), admissible, better on 41/42 tasks. (kp·e is a clean torque-error signal; the board's tau carries ±10 N·m of quantisation buzz). Regressing kp·e on the given model's own gravity term explains most of elbow (0.45 → 0.25 N·m) and w1 (0.094 → 0.035) and part of lift (1.08 → 0.90; with sin/cos of q2..q4 → 0.48). Expect: lift/elbow/w1 biases gone, ~10-20 %. Got −60 %.
- [x] ~~Second friction pass against the target velocity, from joint errors~~ → `p5s-fric2` 0.079 mm dev (holdout 0.102), admissible, better on 39/42.
- [x] ~~Stiffer board gains (kp ×2, kd ×√2) on top of the identified models~~ → `p5s-kp2` 0.056 mm dev, admissible, better on 41/42; energy +8.6 %. Transfer risk: see Suggestions for Zach.
- [x] ~~kp ×4, kd ×2~~ → `p5s-kp4` 0.046 mm dev, admissible, −17 % (diminishing); saturation share 0.038 %, energy +24 % over configured gains. Not going stiffer: more gain mostly buys twin-only accuracy.
- [x] ~~Same joint-error identification for the inertia terms~~ → the uniform qdd lead was the board's velocity-estimate lag, not inertia: `p5s-vlag` (ff −= kd·1.3 ms·qdd) 0.043 mm dev, admissible, −6 %.
- [x] ~~Re-identify friction + gravity from joint errors at the current (kp ×4) gains, as an additive pass~~ → `p5s-pass2` 0.032 mm dev (holdout 0.030), admissible, −27 % (expected ~5 %). Every joint-error regression coefficient is now ~0.
- [x] ~~Niche at the boards' configured gains: the same second pass on p5s-fric2~~ → `p5s-fric2-pass2` 0.070 mm dev, admissible (−12 %): the best candidate that does not lean on stiffer gains.
- [x] ~~Less board damping at kp ×4 (kd ×1.5)~~ → `p5s-kd15` 0.035 mm, worse than p5s-pass2 (0.032): the buzz it removes is cheaper than the damping it loses.
- [x] ~~More board damping (kd ×2.5)~~ → `p5s-kd25` 0.035 mm, worse, saturation share 1.3 % (gate 2 %). kd ×2 is the local optimum at kp ×4.
- [x] ~~Fold the four identification passes into one model~~ → `p5s-onefit`: one model.json (exact merge, commands equal within 1.4e-14) and `identify_pass.py`, one command per further pass.
- [x] ~~Pass 3 with identify_pass.py~~ → `p5s-pass3` 0.0313 mm dev (−0.7 %, better on 20/42; holdout 0.0307 vs 0.0302): converged. Further passes are noise; the joint error is a fifth of an encoder count.
- [x] ~~Transfer check: the stiff line's identified model at the configured gains~~ → `p5s-pass3-g1` 0.156 mm, worse than the x1-fitted `p5s-fric2-pass2` (0.070) on 42/42 tasks. Joint-error identification learns the closed loop as well as the plant: refit at the gains you run.
- [x] ~~…and without the kd·1.3 ms·qdd term~~ → `p5s-pass3-g1-nolag` 0.141 mm: that term is a tenth of the loss; the rest is friction, which in this twin depends on the loop around it.
- [x] ~~Make the identification gain-portable by adding M(q)·ë to the PD error torque fit and running the same model at x1 and x4.~~ [Stiff gains](solutions/p5s-inertia/scorecard.json) scored 0.03179 mm vs 0.03133 mm for the matched PD-only fit. [Configured gains](solutions/p5s-inertia-g1/scorecard.json) scored 0.15701 mm vs 0.15645 mm for PD-only, missing the 10% improvement target. All 84 dev task runs passed every gate. Keep separate fits for each gain setting.
- [x] ~~Middle rung: the same pass at kp ×2~~ → `p5s-kp2-pass2` 0.045 mm. Frontier fitted at each gain: x1 0.070 · x2 0.045 · x4 0.031 mm.
- [x] Fit direction-dependent friction at the leading controller’s fixed gains.
  - Prediction before replay: dev `tool_track_rms_mm` below 0.03100 mm and every task passes all five gates.
  - [p5s-friction-asym scorecard](solutions/p5s-friction-asym/scorecard.json). 0.031402 mm with 42/42 tasks passing all gates. The median was higher than the parent's 0.031334 mm.
- [x] Average the leading controller’s planned feedforward over each joint’s command hold.
  - Prediction before replay: dev `tool_track_rms_mm` below 0.03100 mm and every task passes all five gates.
  - [p5s-hold-average scorecard](solutions/p5s-hold-average/scorecard.json). 0.031944 mm with 42/42 tasks passing all gates. Midpoint sampling gave the lower median.
- [x] Fit a diagonal acceleration-proportional feedforward residual at the leading controller’s fixed gains.
  - Prediction before replay: dev `tool_track_rms_mm` below 0.03100 mm and every task passes all five gates.
  - [p5s-accel-residual scorecard](solutions/p5s-accel-residual/scorecard.json). 0.031337 mm with 42/42 tasks passing all gates. The median was slightly higher than the parent's 0.031334 mm.
- [x] Use the exact position intercept for the leading controller’s fixed secant slope over each command hold.
  - Prediction before replay: dev `tool_track_rms_mm` below 0.03100 mm and every task passes all five gates.
  - [p5s-chord-integral scorecard](solutions/p5s-chord-integral/scorecard.json). 0.032265 mm with 42/42 tasks passing all gates. The parent's acceleration-based intercept gave the lower median.
- [x] Use the board’s causal velocity-filter response to compensate target-velocity lag.
  - Prediction before replay: dev `tool_track_rms_mm` below 0.03100 mm and every task passes all five gates.
  - [p5s-filter-history scorecard](solutions/p5s-filter-history/scorecard.json). 0.031732 mm with 42/42 tasks passing all gates. The parent's constant-lag model gave the lower median.
- [x] Compare damping multipliers 1.85 and 2.15 around the leading controller’s 2.0.
  - Prediction before replay: dev `tool_track_rms_mm` below 0.03100 mm and every task passes all five gates.
  - [1.85 scorecard](solutions/p5s-damping185/scorecard.json), [2.15 scorecard](solutions/p5s-damping215/scorecard.json). 0.031083 and 0.031627 mm respectively. Both passed every gate on all 42 tasks, and 1.85 improved on the parent.
- [x] Refit one residual pass at damping multiplier 1.85.
  - Prediction before replay: dev `tool_track_rms_mm` below 0.03100 mm and every task passes all five gates.
  - [p5s-damping185-refit scorecard](solutions/p5s-damping185-refit/scorecard.json). 0.029714 mm with 42/42 tasks passing all gates. The [reporting-only holdout](solutions/p5s-damping185-refit/scorecard_holdout.json) scored 0.030846 mm with 12/12 tasks passing all gates.
- [x] Give every dev task equal total weight in the leading model’s identification pass.
  - Prediction before replay: dev `tool_track_rms_mm` below 0.03100 mm and every task passes all five gates.
  - [p5s-task-balanced-fit scorecard](solutions/p5s-task-balanced-fit/scorecard.json). 0.031186 mm with 42/42 tasks passing all gates. The median improved on the 0.031334 mm baseline and missed the 0.03100 mm milestone.
- [ ] Identify from a dedicated calibration run (a rich excitation trajectory, its own runs only) instead of the dev records, so the identified model never sees the tasks it is scored on. Needs a way to run a non-dataset trajectory through the boundary without `deployment.plant()` (see Suggestions for Zach).
  - [Calibration proof](experiments/calibration_only/README.md). A fit from two independent training tapes reduced error on both separate validation tapes and passed all five checks. Full-workspace transfer to the ranked dev split is the remaining step.
- [x] Verify the message boundary and host cadence ([O1.1](specs/O1.1-the-boundary.md)). A valid controller receives joint states at 50 Hz. Malformed and incomplete commands fail `completed`.
- [x] Verify scoring against the frozen tape ([O1.3](specs/O1.3-the-trajectory-is-given.md)). A half-speed controller is still scored on the original tape. The tests caught that a controller could reopen the original sample arrays for writing. It now receives its own immutable samples.

## Suggestions for Zach

- [ ] Ruler v2: a calibration dataset the agent may run freely for identification, separate from dev (today it identifies from dev runs, so dev is both its training data and its score; holdout still checks it).
- [ ] Ruler v2: link and gearbox compliance in the twin, before stiffer gains count as a win.
- [x] Which gain line goes to a real arm first. **Default taken (dispatcher, 2026-11-24): `p5s-kp2-pass2` (kp x2, 0.045 mm dev) is the real-arm candidate, with `p5s-fric2-pass2` (the boards' normal gains, 0.070 mm, same energy as p4s) as the fallback; kp x4 (`p5s-pass3`, 0.031 mm, +24 % energy) stays sim-only until the twin has compliance.** Flying it is a hardware step for Zach; change the pick by editing this line.

- [ ] Which gain rung should graduate to the real arm? Frontier, each rung identified at its own gains (dev mm): x1 `p5s-fric2-pass2` 0.070 (same energy as p4s, 12× better than p4s's 0.848) · x2 `p5s-kp2-pass2` 0.045 · x4 `p5s-pass3` 0.031 (energy +24 %, saturation 0.014 %). The twin cannot say how much stiffness the real UR5e/moteus loop tolerates; recommendation: x1 or x2.
- [ ] Ruler or tooling: a sanctioned *calibration run* (an excitation trajectory a solution may run through the boundary before the tasks, without `deployment.plant()`), so identification stops being fitted on the dev tasks it is scored on. Today the only data are dev run records; holdout says it transfers (dev 0.031 / holdout 0.031) but the scheme reads as fitting on the test set.
- [x] ~~`tests/test_site_static.py::test_leaderboard_numbers_are_the_scorecards` fails whenever an agent adds a solution (site/data is built by lane W's tool, not by `tta progress`). Either `tta progress` rebuilds site/data or the test reads the ledger.~~ → resolved 2026-11-24: the page plays back saved runs (d693415) and AGENTS.md step 4 rebuilds site/data with each solution (be07c90); 948 tests pass at f806e8a.
- [ ] Ruler v2: the twin has no link/gearbox compliance or structural resonance, so board stiffness costs nothing here but the kd-noise energy (+8.6 % at kp ×2). Without a gain-related gate (a resonance mode in the plant, an energy or torque-ripple gate, or a cap on sent stiffness), the search will drift to the stiffest gains the saturation gate allows. `p5s-kp2` and anything stiffer should be read with that in mind.
- [ ] Ruler v2: add speeds 0.25 / 0.5 and the conveyor dataset, so a gain at full speed can't hide a loss at low speed.
