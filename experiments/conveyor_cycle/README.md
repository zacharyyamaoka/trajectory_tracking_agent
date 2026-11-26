# UR5e conveyor pick-and-place transfer

Evaluate the selected `p5s-damping185-refit` controller, with its fitted feedforward and gains intact, on the first continuous conveyor dataset. The UR5e hangs upside down in the arm_motion_bench portal scene, with a static belt, four bins and the collision capsule that stands in for the gripper. The simulation checks unloaded motion. It does not measure gripping or sorting success.

**Prediction before replay.** The same controller should return close to the commanded path but miss its upright benchmark error. The fitted gravity model was selected with the base standing on the floor. Its gravity torque has the opposite sign on the portal. Predict at least one stop error over 1 mm or full-speed tracking error over 0.1 mm. Keep the measured result either way.

This is off-score transfer evidence. The original ruler's controller code, joint position and speed checks, torque caps, host bus, stop bands and tracking metric are reused. Clearance is checked against the stock portal geometry at every physics sample. The upright floor check is specific to its deployment.

`run.py` accepts an arm_motion_bench frozen conveyor-cycle output directory, verifies every checksum, and writes the trial summary and 100 Hz signals without editing the dataset. Use the arm_motion_bench Python environment, adding this repository's `src` directory and the sibling robot_controllers checkout to `PYTHONPATH`.
