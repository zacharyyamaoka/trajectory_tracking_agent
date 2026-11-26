# UR5e conveyor pick-and-place transfer

Evaluate the selected `p5s-damping185-refit` controller, with its fitted feedforward and gains intact, on the first continuous conveyor dataset. The UR5e hangs upside down in the arm_motion_bench portal scene, with a static belt, four bins and the collision capsule that stands in for the gripper. The simulation checks unloaded motion. It does not measure gripping or sorting success.

**Prediction before replay.** The same controller should return close to the commanded path but miss its upright benchmark error. The fitted gravity model was selected with the base standing on the floor. Its gravity torque has the opposite sign on the portal. Predict at least one stop error over 1 mm or full-speed tracking error over 0.1 mm. Keep the measured result either way.

This is off-score transfer evidence. The original ruler's controller code, joint position and speed checks, torque caps, host bus, stop bands and tracking metric are reused. Clearance is checked against the stock portal geometry at every physics sample. The upright floor check is specific to its deployment.

[`run.py`](run.py) accepts an arm_motion_bench frozen conveyor-cycle output directory, verifies every checksum, and writes the trial summary and 100 Hz signals. [`streaming.py`](streaming.py) uses the same simulator and checks while keeping long runs bounded in memory. Use the arm_motion_bench Python environment, with this repository and robot_controllers on `PYTHONPATH`.

```bash
"$ARM_MOTION_BENCH/.venv/bin/python" -m arm_motion_bench.generate.conveyor_cycle --seed 1125 --picks 30 --output outputs/conveyor_cycle/frozen
PYTHONPATH="${PWD}/src:${ROBOT_CONTROLLERS}/src" "$ARM_MOTION_BENCH/.venv/bin/python" experiments/conveyor_cycle/streaming.py outputs/conveyor_cycle/frozen --out outputs/conveyor_cycle/reproduction
"$ARM_MOTION_BENCH/.venv/bin/python" experiments/conveyor_cycle/report.py outputs/conveyor_cycle/reproduction outputs/conveyor_cycle/reproduction-review
```

The reported dataset froze from the generator later landed as `d69cba2`. Its manifest was recorded before that commit and includes the generator source SHA-256. The board bench's mounted scene support is `d2fe5af` in robot_controllers. The original two-pick pilot used fractions 0.1 and 1.0 before the full freeze and replay.

Use `--controller p5s-damping185-mount-aware` to replay the controller selected for the [tracking goal](../../goals/G1-ur5e-tracking-at-every-speed.md). This revision uses the portal mount's base-frame gravity direction in the feedforward. The [scene check](scene_check.py) compares the default Scene DB export with the frozen planning geometry. The export includes the modeled gripper. The motion bench uses its unloaded capsule stand-in for replay.
