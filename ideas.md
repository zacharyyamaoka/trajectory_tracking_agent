# Ideas (the queue)

Two lists. Each idea says what it should move and by how much. Cross a line off with the solution id that tried it;
never delete it.

## I'll try

- [ ] Host Coulomb feed-forward on the best gen-0 layout. Expect: tool RMS down where the joints reverse (real_kp2's lever on BAM FB, never tried on the UR5e here).
- [ ] Per-joint lookahead calibrated on dev tasks only, not on robot_controllers' calibration sweep. Expect: lag down, RMS down a little.

## Suggestions for Zach

- [ ] Ruler v2: add speeds 0.25 / 0.5 and the conveyor dataset, so a gain at full speed can't hide a loss at low speed.
