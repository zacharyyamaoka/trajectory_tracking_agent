# Objectives & Gates (ruler v1, frozen 2026-11-24)

The outside of the black box: what goes in, what comes out, and how a solution is scored. Nothing here says what
is inside a solution. Changing anything in this file makes **ruler v2**: a new section below, and every solution in
`solutions/` is re-scored on it. A solution never edits this file, `datasets/` or `src/trajectory_tracking_agent/ruler/`.

WHY frozen (Zach, 2026-11-24): *"BEFORE I even take a look at kind what is going on inside … finalize the API, what is
going in and out, what are the evaluation metrics, and how are they calculated."* The arm_motion_bench contract was
amended 16 times in four days (v3.1 → v3.16), and two benches scored the same UR5e about 1000× apart
(< 0.05 mm vs 2.0 mm), because they drew the boundary in different places. One frozen ruler fixes both.

## 1. The black box

```python
from robot_msgs import JointTrajectory, JointState, ServoCommand    # the vocabulary (robot_msgs)

# IN: given; a solution never changes them
deployment = trajectory_tracking_agent.deployment("ur5e_alone")      # robot + scene + bus + host rate
task = trajectory_tracking_agent.tasks("dev")[k]                     # task.trajectory: a robot_msgs JointTrajectory

# THE BLACK BOX: the only thing a solution is (solutions/<id>/solution.py)
controller = solution.build(task.trajectory, deployment)             # a robot_msgs JointController
command, diagnostics = controller.tick(joint_state, dt)              # JointState in, ServoCommand out, every host tick

# OUT
scorecard = trajectory_tracking_agent.evaluate("<solution id>", split="dev")
```

- **The boundary is robot_msgs `JointTrajectory` + `JointState` in, `ServoCommand` out** (robot_controllers' contract
  §2), at the deployment's host rate over its bus. A moteus board takes a `ServoCommand` as is; a UR servoJ stream is
  one with position only; UR's direct torque is one with feed-forward only. The solution may use any of those fields.
- **The deployment owns the rate and the bus**, never the solution: robot, scene, host rate, bus timing, the servo
  boards' model and caps.
- **A solution cannot retime, reshape or skip the trajectory** (layer 3 of the arm_motion_bench v2.0 layers: the
  trajectory and the robot are given; the levers are the torque and the controller).

## 2. Deployment v1: `ur5e_alone`

| Part | Value | Source |
|---|---|---|
| Robot + plant | MuJoCo Menagerie UR5e, the "truth" plant (armature, dry friction, damping), floor-mounted | `robot_controllers.bench.ur5e` (`Ur5ePlant`, `UR5E_TRUTH`) |
| Servo boards | the moteus board model with the UR5e datasheet caps (150 ×3, 28 ×3 N·m) | `robot_controllers.bench.ur5e.ur5e_board_config()` |
| Host rate | 50 Hz (the rig's) | robot_controllers base scenario |
| Bus | the datasheet bus for six devices | `robot_controllers.timing` / `BusTiming.from_datasheet` |
| Scene | the arm alone on a floor (floor plane z = 0 at the base) | arm_motion_bench `ur5e_alone` (CONTRACT v3.16) |
| Tool point | the flange site `tool`, 0.1 m along wrist_3 | `robot_controllers.bench.ur5e.tool_position` |

The plant, boards and bus are imported from robot_controllers at a pinned version, never copied or edited here.

## 3. The dataset v1: `ur5e_alone/workspace/v2`

- The UR5e's whole workspace, arm alone on the floor: joint A→B moves, straight tool lines, via points and the two
  ISO 9283 tasks. **dev** = seed 1001 (42 tasks), **holdout** = seed 2001 (12 tasks).
- Timed by bam_ruckig (jerk-limited, time-optimal) at the UR5e's limits. **Speed 1.0 only** in ruler v1.
- Frozen copy of arm_motion_bench `datasets/ur5e_alone/workspace/v2` (its `manifest.json` sha256s), with the timed
  tapes at speed 1.0 committed (bam_ruckig is private, so the public repo ships tapes, not the generator).
  `tta verify` re-checks every sha256.

## 4. The score

**Objective (one number, lower is better): `tool_track_rms_mm`** = the median over dev tasks of each task's RMS
distance between the measured tool point and the target tool point *at the same instant*, over the task's moving
samples. Both tool points come from the joint encoders through the same FK (§2's tool point), never from simulator
body poses. *Moving* = target tool speed > 1 mm/s or any target joint speed > 0.06 °/s (arm_motion_bench `kpi_names`).

**Gates (per task; a solution is *admissible* only if every dev task passes every gate):**

| Gate | Pass when | Why |
|---|---|---|
| `completed` | no exception, no NaN command, the run reaches the trajectory's end and settles | a crash is not a score |
| `stop_error_max_mm` | ≤ 1.0 mm: target vs mean tool position over each stop's last 0.1 s (a stop = target at rest ≥ 0.2 s) | Zach's standing 1 mm tool gate (2026-11-11) |
| `saturation_share_pct` | ≤ 2 %: share of samples where any joint torque is ≥ 98 % of its cap | speed bought with saturation doesn't transfer |
| `limit_violations` | 0 samples outside a position limit or above 1.05 × a velocity limit | — |
| `floor_clearance` | 0 samples with the tool point or any link origin below the floor plane | the bare plant has no contacts, so collision with the scene is checked geometrically |

**Every verdict fails closed** (arm_motion_bench v3.11): a missing or NaN value is a failed gate, never a pass.

**Diagnostics** (reported, never optimized): `tool_track_max_mm`, `joint_track_rms_deg` (worst joint),
`tool_lag_ms`, `stop_error_mm` (median), `saturation_share_pct`, `energy_j` (positive mechanical work, labelled
"motor energy"), `tool_jerk_rms_m_s3`, `host_compute_ms_p95` (the solution's own `tick` time), `wall_time_s`.

**Holdout** is scored only by `evaluate(..., split="holdout")` for reporting. Choosing between solutions on holdout
is a bug (it would make holdout a second dev set). The leaderboard shows holdout − dev beside each admissible solution.

**Ranking:** admissible solutions by `tool_track_rms_mm` (lower first); then the rest by gate pass rate, then
objective. The *best* solution is the lowest-objective admissible one.

## 5. Deferred to ruler v2 (named so nobody thinks they were forgotten)

Speeds below 1.0 (the sweep), the conveyor and impact datasets, collision detection and false alarms, BAM FB and the
1-DOF pendulum deployments, the real arm (a separate stage a solution graduates into; never inside the search loop),
model error as a deployment axis, a camera-measured tool point.
