# `ur5e_alone/workspace/v2`: the frozen dataset of ruler v1

The UR5e's whole workspace, arm alone on the floor (OBJECTIVES §3): joint A→B moves, straight tool lines, via points and
the two ISO 9283 tasks. **dev** = seed 1001 (42 tasks, 99.36 s at speed 1.0), **holdout** = seed 2001 (12 tasks, 28.80 s).
Timed by bam_ruckig (jerk-limited, time-optimal) at the UR5e's limits (π rad/s, 6 rad/s², 60 rad/s³ per joint).

## What is here

| File | What | Where it came from |
|---|---|---|
| `manifest.json`, `tasks.jsonl`, `station.json`, `rejections.jsonl` | the frozen dataset | byte-for-byte copy of arm_motion_bench `datasets/ur5e_alone/workspace/v2/` (its last change: `1ba1d8c`, 2026-11-23) |
| `tapes/<task_id>.npz` (54 files, 3.7 MB) | the speed-1.0 tapes | arm_motion_bench's generator, regenerated bit for bit on 2026-11-24 (below) |
| `tapes_manifest.json` | the sha256 of every file above | written once by lane E on 2026-11-24; `tta verify` re-checks it |

**Tape format.** Each tape is robot_msgs `save_npz` of one `JointTrajectory`, exactly as arm_motion_bench
`datasets._write_rung_tapes` writes the 1.0 rung; read it with `robot_msgs.load_npz(path)`. It carries `t` (s, from 0, a
100 Hz grid), `positions`, `velocities`, `accelerations` (rad, rad/s, rad/s², `(N, 6)`), a `piece` channel (which move a
sample belongs to; its labels are in `header.meta["pieces"]`), the joint limits and no effort column. Two extra arrays,
`tcp_pos` / `tcp_rot`, are the dataset station's TCP (flange + 0.144 m, the BAM claw); the ruler never reads them, its tool
point is OBJECTIVES §2's (the flange site, through robot_controllers' FK). **Joint order** is
`shoulder_pan, shoulder_lift, elbow, wrist_1, wrist_2, wrist_3`, robot_controllers' `UR5E_JOINTS`; the loader
(`ruler/dataset.py`) refuses a tape in any other order.

**Why verbatim copies, not a re-encoding.** Each tape's sha256 is the one arm_motion_bench's `manifest.json` lists under
`files`, so `tta verify` checks the chain back to the generator, not only to this copy. The 54 files are 3.7 MB (1.9 MB
gzipped), inside the 10 MB budget.

**How the tapes were produced.** bam_ruckig is private, so this public repo ships tapes, not the generator. On
2026-11-24, in arm_motion_bench's own venv (bam_ruckig sha256 `f68b0442…3086caa`, Ruckig Pro 0.19.4):

```bash
cd ~/arm_motion_bench && taskset -c 2-5,16,17 .venv/bin/python -m arm_motion_bench verify datasets/ur5e_alone/workspace/v2 --no-restore
```

printed `OK, every regenerated file matches the manifest (9 s)`, and the tapes on disk in
`outputs/datasets/ur5e_alone/workspace/v2/tapes/` matched the manifest too; the copies here are those bytes
(`workspace-<split>-NNN.npz`, the speed-1.0 rung; the slower rungs and the `.tcp.npz` caches are left out, ruler v1 runs
speed 1.0 only).

## The mount, gravity and limits (checked 2026-11-24)

- **Same mount, up to a yaw.** arm_motion_bench's `floor` mount puts the base body at the origin with an identity
  quaternion; robot_controllers' bare UR5e (`ur5e_bare.xml`, the ruler's plant) keeps Menagerie's base at the origin with
  Rz(π). Over every sample of all 54 tapes, the dataset's stored TCP equals Rz(π) · (this model's flange site + 0.144 m
  along the flange normal) to 9.7e-16 m (the heights agree to 8.9e-16 m). So the two scenes differ only by a 180° yaw about
  the vertical base axis, which changes no number the ruler measures: distances, heights and the floor are the same.
- **Floor and gravity.** The floor plane is z = 0 at the base in both (arm_motion_bench: the top of its `mount_floor` box;
  here `Deployment.floor_z_m = 0.0`). robot_controllers' model sets no `<option gravity>`, so MuJoCo's default
  (0, 0, −9.81) m/s², straight down onto that floor; `deployment()` refuses to build if that ever changes.
- **Joint limits used by `limit_violations`** are this folder's `station.json`: positions ±2π rad (elbow ±3.1415 rad) and
  π rad/s (180 °/s, the UR5e datasheet) on every joint, with the 1.05 allowance on velocity. They agree with the MJCF's
  joint ranges (±6.28319, elbow ±3.1415) to < 1e-5 rad, and the station's torque caps (150 ×3, 28 ×3 N·m) are the boards'
  caps; `deployment()` checks both at load and fails closed on a mismatch.
- **Collision.** The dataset admitted every task with Menagerie's capsules + a claw stand-in kept ≥ 10 mm off the floor;
  the ruler's `floor_clearance` gate checks the tool point and every link origin of the bare model against z = 0 (the bare
  plant has no contacts).
