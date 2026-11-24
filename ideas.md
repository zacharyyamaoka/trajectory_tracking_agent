# Ideas (the queue)

Two lists. Each idea says what it should move and by how much. Cross a line off with the solution id that tried it;
never delete it.

## I'll try

- [ ] Host Coulomb feed-forward on the best gen-0 layout. Expect: tool RMS down where the joints reverse (real_kp2's lever on BAM FB, never tried on the UR5e here).
- [ ] Per-joint lookahead calibrated on dev tasks only, not on robot_controllers' calibration sweep. Expect: lag down, RMS down a little.
- [x] ~~Coulomb ff with the bus's own lookahead, not the calibration's~~ → `p5s-bus` 0.595 mm dev (holdout 0.534), admissible. The calibration folds friction lag into the wrists' lookahead (+3.75/+4.5 ms); p5s then compensated friction twice. With Coulomb in the ff, lookahead = bus delay.
- [x] ~~Take the board's own lead out of the lookahead~~ → `p5s-bus-enc` 0.393 mm dev (holdout 0.332), admissible. The board walks its setpoint one tick (0.25 ms) before using it and closes on a 0.5 ms-old position, so its PD balances 0.75 ms ahead; every joint led by 0.042-0.046 deg per rad/s, now ~0.
- [x] ~~Identify per-joint Coulomb + viscous from dev run records~~ → `p5s-fric` 0.245 mm dev (holdout see ledger), admissible. wrist_2's friction is soft (vs 0.2 rad/s), wrist_3 has ~none; the given Coulomb over-pushed both. w2 error 0.121 → 0.015 deg.
- [ ] Identify the gravity error (constant joint biases on lift/elbow/w1 at 0.01 deg) from the stops and slow samples. Expect: stop error down, tool RMS down a little.

## Suggestions for Zach

- [ ] Ruler v2: add speeds 0.25 / 0.5 and the conveyor dataset, so a gain at full speed can't hide a loss at low speed.
