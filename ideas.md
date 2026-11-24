# Ideas (the queue)

Two lists. Each idea says what it should move and by how much. Cross a line off with the solution id that tried it;
never delete it.

## I'll try

- [ ] Host Coulomb feed-forward on the best gen-0 layout. Expect: tool RMS down where the joints reverse (real_kp2's lever on BAM FB, never tried on the UR5e here).
- [ ] Per-joint lookahead calibrated on dev tasks only, not on robot_controllers' calibration sweep. Expect: lag down, RMS down a little.
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
- [ ] Fold the four identification passes into one script and one fit, re-run on the best's own runs, so a solution carries one model instead of a stack (friction, gravity, friction2, pass2). Expect: no score change; much easier to read and to move to a real arm.

## Suggestions for Zach

- [ ] Ruler v2: the twin has no link/gearbox compliance or structural resonance, so board stiffness costs nothing here but the kd-noise energy (+8.6 % at kp ×2). Without a gain-related gate (a resonance mode in the plant, an energy or torque-ripple gate, or a cap on sent stiffness), the search will drift to the stiffest gains the saturation gate allows. `p5s-kp2` and anything stiffer should be read with that in mind.

- [ ] Ruler v2: add speeds 0.25 / 0.5 and the conveyor dataset, so a gain at full speed can't hide a loss at low speed.
