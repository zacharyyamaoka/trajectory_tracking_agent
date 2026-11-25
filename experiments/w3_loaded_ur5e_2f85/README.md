# W3 loaded check: UR5e + Robotiq 2F-85 + an object (off-score)

**Verdict: with the gripper in the feed-forward and the object not (what a real picker runs), p5s-pass3's ≤ 1 mm stop
survives the 60 g object with about 4× margin.**
- **60 g object:** 0.070 mm. 42/42 dev and 12/12 holdout pass. Worst stop 0.235 mm on the ruler's tool point, 0.306 mm
  at the TCP.
- **0.3 kg object:** 0.208 mm, everything passes. Worst stop 0.380 mm, 0.560 mm at the TCP.
- **Where it breaks (sweep, dev):** between 0.7 and 0.8 kg on the ruler's tool point (42/42 at 0.7 kg, 41/42 at 0.8 kg),
  and between 0.4 and 0.5 kg at the TCP, where the object is (all stops ≤ 1 mm at 0.4 kg, one task over at 0.5 kg).
- **How it breaks:** always on stop error, as a static sag. Never on saturation (worst task ≤ 0.9 %, gate 2 %) and never
  on time.

**With nothing in the model (the honest unaware case), the 0.985 kg load already breaks one task.** The objective goes
from 0.031 to 0.487 mm and 41/42 pass; workspace-dev-010 stops 1.090 mm off and never settles inside 1 mm. Holdout
passes 12/12 (worst 0.756 mm). At the TCP, 5 of 42 dev tasks stop more than 1 mm off. Telling the feed-forward the
whole payload brings it back to 0.055 mm with 42/42 passing.

This is a labelled side check. It is not a ruler number, not a solution and not a ledger row. Ruler v1 and its dataset,
score and solutions are untouched. Ruler v1 scores the bare arm.

## The load

Two point masses hang off wrist_3. The vendored links' own inertials stay as they are.

| What | Mass | Where (along the tool axis, from the flange face) | Source |
|---|---|---|---|
| Robotiq 2F-85 | 0.925 kg | 39.55 mm (the open hand's centre of mass) | mass: robotparts `parts/robotiq-2f-85/part.py` (Robotiq manual Table 5-1). Centre of mass: robotparts `files/2f-85.xml` (MuJoCo Menagerie robotiq_2f85_v4, 0.900 kg), computed with MuJoCo at the open pose |
| Object | 0.06 kg | 144 mm (the dataset's TCP) | the tapes' `tcp_pos`, which matches this model's FK to 5e-16 m |

- **Not modelled:** the hand's own rotational inertia, at most 1.05e-3 kg m² (1.3 % of one wrist joint's armature). Also
  not modelled: finger motion, object swing or slip, and the cable.
- **Robotiq's CoM table is not in robotparts.** robotparts stores no centre of mass for the 2F-85 (`com_z_m: None`), so
  the centre of mass comes from Menagerie's mass distribution.
- **TCP offset:** Robotiq states its TCP at 174 mm. The tapes carry 144 mm, so that is where the object sits.

**In the plain `loaded` cases the controller is never told about the load. That is the honest test.**
- p5s-pass3 keeps the given `rigid_body` model (no payload, links 10 % wrong) and its `model.json`, which was identified
  on the bare arm.
- p1 has no model at all.

The labelled cases tell p5s-pass3's feed-forward part of the load, exactly; the arm's links stay 10 % wrong. That is the
one line a solution would change, injected here without editing the solution.

| Case | The plant carries | The feed-forward is told |
|---|---|---|
| `loaded` | gripper + 60 g object | nothing |
| `loaded+model-knows` | gripper + 60 g object | gripper + object (an upper bound on what identifying the payload can buy) |
| `loaded+model-knows-gripper` | gripper + 60 g object | the gripper only. This is what a real picker runs: the gripper is fixed and known, each object's weight is not |
| `0.3kg-object+model-knows-gripper` | gripper + 0.3 kg object | the gripper only |
| break sweep (dev, summaries) | gripper + 0.06 to 1.5 kg object | the gripper only |

## How it runs

Each task is the ruler's own run: `evaluate._rung`, robot_controllers' `run_episode`, seed 0, and the deployment's
boards, bus and timing. Scoring is `evaluate._score`, the ruler's metrics and gates. Two things differ:

1. **The plant's MjModel is the loaded one.** `LoadedUr5ePlant` is `Ur5ePlant` with the model passed in through
   `_stopped_model`.
2. **The episode runs 2 s past the trajectory's end**, so the settle time can be measured. The ruler's metrics only read
   samples up to the end, so this changes no ruler number.

The script checks itself before it reports anything:
- **Bare reproduction:** the bare case must match each solution's committed scorecard task by task, bit for bit
  (objective, kpis, verdicts), or the script stops. It does for p5s-pass3 dev (0.031333594888818476 mm), p5s-pass3
  holdout (0.030664937510676324) and p1 dev (6.249808422116393).
- **Hook self-check:** robot_controllers' own payload hook (`Scene.payload_kg`) and this script's model path, given the
  same 0.985 kg at the tool site, give bit-identical runs.

**Added here (not the ruler's):**
- **Achieved:** the first instant after which the tool stays within 1 mm of the trajectory's final target until 2 s past
  the end, summed over tasks. It is measured on a 1 kHz grid. "Never settle" means the tool is still outside 1 mm at
  end + 2 s.
- **Perfect tracker:** the same instant for the target itself. Every tape ends with a hold, so this comes before the
  commanded end.
- **Overrun:** achieved minus perfect tracker, per task.
- **TCP numbers:** the ruler's definitions applied at flange + 0.144 m. The ruler's own tool point is the flange.

## Results

Robot time throughout, never wall time. The ruler point is the flange site `tool`; the TCP table is at the object.

| Case | Split | Tool RMS (mm, ruler objective) | Stop error median / worst (mm) | Saturation worst task (%) | Gates passed | Commanded (s) | Achieved: settled ≤ 1 mm (s) | Perfect tracker (s) | Worst task overrun (ms) |
|---|---|---|---|---|---|---|---|---|---|
| p5s-pass3/bare | dev | 0.0313 | 0.085 / 0.197 | 0.014 | 42/42 | 99.36 | 74.91 | 75.11 | 2 |
| p5s-pass3/bare | holdout | 0.0307 | 0.069 / 0.106 | 0.017 | 12/12 | 28.80 | 21.97 | 22.03 | -1 |
| p5s-pass3/loaded | dev | 0.4874 | 0.435 / 1.090 | 0.102 | 41/42 | 99.36 | 73.81 over 41 tasks; 1 never settle | 75.11 | 73 |
| p5s-pass3/loaded | holdout | 0.5745 | 0.467 / 0.756 | 0.148 | 12/12 | 28.80 | 21.89 | 22.03 | 2 |
| p5s-pass3/loaded+model-knows | dev | 0.0553 | 0.095 / 0.210 | 0.283 | 42/42 | 99.36 | 74.92 | 75.11 | 0 |
| p5s-pass3/loaded+model-knows-gripper | dev | 0.0704 | 0.097 / 0.235 | 0.498 | 42/42 | 99.36 | 74.90 | 75.11 | 0 |
| p5s-pass3/loaded+model-knows-gripper | holdout | 0.0710 | 0.085 / 0.207 | 0.139 | 12/12 | 28.80 | 21.96 | 22.03 | 1 |
| p5s-pass3/0.3kg-object+model-knows-gripper | dev | 0.2076 | 0.183 / 0.380 | 0.317 | 42/42 | 99.36 | 74.85 | 75.11 | 0 |
| p5s-pass3/0.3kg-object+model-knows-gripper | holdout | 0.2039 | 0.129 / 0.392 | 0.200 | 12/12 | 28.80 | 21.93 | 22.03 | 2 |
| p1/bare | dev | 6.2498 | 5.602 / 13.998 | 0.000 | 1/42 | 99.36 | 1.16 over 1 tasks; 41 never settle | 75.11 | 6 |
| p1/loaded | dev | 7.9696 | 7.128 / 17.297 | 0.000 | 0/42 | 99.36 | 0.00 over 0 tasks; 42 never settle | 75.11 | — |

At the TCP (flange + 0.144 m, where the object is; the ruler's definitions, not the ruler's point):

| Case | Split | TCP RMS (mm) | TCP stop error median / worst (mm) | Tasks with TCP stops ≤ 1 mm | TCP achieved (s) |
|---|---|---|---|---|---|
| p5s-pass3/bare | dev | 0.0379 | 0.097 / 0.227 | 42/42 | 75.20 |
| p5s-pass3/bare | holdout | 0.0371 | 0.076 / 0.124 | 12/12 | 21.92 |
| p5s-pass3/loaded | dev | 0.7370 | 0.671 / 1.399 | 37/42 | 5 never settle |
| p5s-pass3/loaded | holdout | 0.7950 | 0.691 / 0.981 | 12/12 | 22.34 |
| p5s-pass3/loaded+model-knows | dev | 0.0852 | 0.104 / 0.249 | 42/42 | 75.23 |
| p5s-pass3/loaded+model-knows-gripper | dev | 0.1146 | 0.109 / 0.306 | 42/42 | 75.21 |
| p5s-pass3/loaded+model-knows-gripper | holdout | 0.1065 | 0.115 / 0.220 | 12/12 | 21.91 |
| p5s-pass3/0.3kg-object+model-knows-gripper | dev | 0.3286 | 0.279 / 0.560 | 42/42 | 75.23 |
| p5s-pass3/0.3kg-object+model-knows-gripper | holdout | 0.3036 | 0.209 / 0.549 | 12/12 | 21.88 |
| p1/bare | dev | 6.3458 | 6.067 / 15.199 | 0/42 | 42 never settle |
| p1/loaded | dev | 8.9280 | 8.351 / 19.517 | 0/42 | 42 never settle |

Worst 3 tasks per case: by stop error (ruler point), then by overrun (settle time minus a perfect tracker's):

- **p5s-pass3/bare@dev**: stop error workspace-dev-039 (via_points) 0.197 mm; workspace-dev-025 (a_to_b_joint) 0.195 mm; workspace-dev-005 (a_to_b_joint) 0.190 mm. Overrun workspace-dev-009 +2 ms; workspace-dev-002 -1 ms; workspace-dev-008 -1 ms.
- **p5s-pass3/bare@holdout**: stop error workspace-holdout-000 (a_to_b_joint) 0.106 mm; workspace-holdout-003 (a_to_b_joint) 0.105 mm; workspace-holdout-005 (a_to_b_joint) 0.085 mm. Overrun workspace-holdout-010 -1 ms; workspace-holdout-005 -2 ms; workspace-holdout-000 -3 ms.
- **p5s-pass3/loaded@dev**: stop error workspace-dev-010 (a_to_b_joint) 1.090 mm; workspace-dev-017 (via_points) 0.957 mm; workspace-dev-009 (a_to_b_line) 0.851 mm. Overrun workspace-dev-010 never settles; workspace-dev-009 +73 ms; workspace-dev-020 +33 ms.
- **p5s-pass3/loaded@holdout**: stop error workspace-holdout-005 (a_to_b_joint) 0.756 mm; workspace-holdout-008 (a_to_b_joint) 0.691 mm; workspace-holdout-003 (a_to_b_joint) 0.689 mm. Overrun workspace-holdout-010 +2 ms; workspace-holdout-001 -5 ms; workspace-holdout-009 -9 ms.
- **p5s-pass3/loaded+model-knows@dev**: stop error workspace-dev-005 (a_to_b_joint) 0.210 mm; workspace-dev-025 (a_to_b_joint) 0.209 mm; workspace-dev-039 (via_points) 0.202 mm. Overrun workspace-dev-015 +0 ms; workspace-dev-036 +0 ms; workspace-dev-002 -1 ms.
- **p5s-pass3/loaded+model-knows-gripper@dev**: stop error workspace-dev-008 (a_to_b_joint) 0.235 mm; workspace-dev-005 (a_to_b_joint) 0.231 mm; workspace-dev-025 (a_to_b_joint) 0.216 mm. Overrun workspace-dev-015 +0 ms; workspace-dev-025 +0 ms; workspace-dev-002 -1 ms.
- **p5s-pass3/loaded+model-knows-gripper@holdout**: stop error workspace-holdout-011 (a_to_b_joint) 0.207 mm; workspace-holdout-004 (via_points) 0.176 mm; workspace-holdout-001 (via_points) 0.112 mm. Overrun workspace-holdout-010 +1 ms; workspace-holdout-000 -3 ms; workspace-holdout-005 -3 ms.
- **p5s-pass3/0.3kg-object+model-knows-gripper@dev**: stop error workspace-dev-020 (a_to_b_line) 0.380 mm; workspace-dev-007 (a_to_b_joint) 0.376 mm; workspace-dev-037 (a_to_b_joint) 0.349 mm. Overrun workspace-dev-002 +0 ms; workspace-dev-015 +0 ms; workspace-dev-025 +0 ms.
- **p5s-pass3/0.3kg-object+model-knows-gripper@holdout**: stop error workspace-holdout-010 (a_to_b_joint) 0.392 mm; workspace-holdout-008 (a_to_b_joint) 0.303 mm; workspace-holdout-011 (a_to_b_joint) 0.228 mm. Overrun workspace-holdout-010 +2 ms; workspace-holdout-000 -6 ms; workspace-holdout-005 -6 ms.
- **p1/bare@dev**: stop error workspace-dev-009 (a_to_b_line) 13.998 mm; workspace-dev-010 (a_to_b_joint) 12.243 mm; workspace-dev-008 (a_to_b_joint) 10.450 mm. Overrun workspace-dev-000 never settles; workspace-dev-001 never settles; workspace-dev-002 never settles.
- **p1/loaded@dev**: stop error workspace-dev-009 (a_to_b_line) 17.297 mm; workspace-dev-010 (a_to_b_joint) 16.306 mm; workspace-dev-017 (via_points) 13.525 mm. Overrun workspace-dev-000 never settles; workspace-dev-001 never settles; workspace-dev-002 never settles.

Object mass sweep (p5s-pass3, dev; the gripper known to the feed-forward, the object not):

| Object (kg) | Tool RMS (mm) | Stop error median / worst (mm) | Gates passed | Saturation worst task (%) | TCP stop error worst (mm) | Tasks with TCP stops ≤ 1 mm |
|---|---|---|---|---|---|---|
| 0.06 | 0.0704 | 0.097 / 0.235 | 42/42 | 0.498 | 0.306 | 42/42 |
| 0.3 | 0.2076 | 0.183 / 0.380 | 42/42 | 0.317 | 0.560 | 42/42 |
| 0.4 | 0.2712 | 0.227 / 0.607 | 42/42 | 0.761 | 0.704 | 42/42 |
| 0.5 | 0.3368 | 0.296 / 0.827 | 42/42 | 0.439 | 1.072 | 41/42 |
| 0.6 | 0.3980 | 0.343 / 0.932 | 42/42 | 0.684 | 1.253 | 40/42 |
| 0.7 | 0.4614 | 0.405 / 0.948 | 42/42 | 0.574 | 1.278 | 40/42 |
| 0.8 | 0.5263 | 0.454 / 1.010 | 41/42 | 0.894 | 1.384 | 36/42 |
| 0.9 | 0.5906 | 0.449 / 1.234 | 40/42 | 0.343 | 1.700 | 32/42 |
| 1 | 0.6534 | 0.543 / 1.218 | 38/42 | 0.808 | 1.639 | 26/42 |
| 1.5 | 0.9763 | 0.778 / 1.601 | 30/42 | 0.901 | 2.301 | 15/42 |

The tables, the worst-task list and the sweep are `loaded_check.py --table`, printed from `results.json`.

## Where it breaks

**Gripper known, object not.**
- **The 60 g object costs little:** 0.031 → 0.070 mm. The worst stop is 0.235 mm against 0.197 mm bare, and no task
  finishes more than 1 ms behind a perfect tracker (dev and holdout).
- **What remains is the object's own sag.** It grows with the object's mass: 0.235 → 0.380 → 0.607 → 0.827 mm worst stop
  at 0.06 / 0.3 / 0.4 / 0.5 kg. In the 0.06 and 0.3 kg cases (the ones with per-task rows), the error 2 s after the end
  is within 0.15 mm of each task's worst stop, so it is static.
- **The first tasks to break:**
  - workspace-dev-017 (via_points) is the first task over 1 mm at the TCP (0.5 kg) and the first to fail the ruler's
    stop gate (0.8 kg, 1.010 mm).
  - dev-010, 020, 009, 035 and 040 follow. These are the same poses that fail when nothing is modelled.
- **At 1 kg:** 38/42 pass, and only 26/42 tasks stop within 1 mm at the TCP.

**Nothing modelled: stop error, as a static sag.**
- **The error does not decay.** On every loaded task, the error 2 s after the end is within 0.12 mm of the task's worst
  stop error (median difference 0.007 mm). The worst stop can be an earlier one, which is why the two are not equal.
  workspace-dev-010 stops 1.090 mm off and is still 1.107 mm off 2 s later; at the TCP it is 1.399 mm, then 1.426 mm.
- **Why:** the feed-forward lacks the payload's gravity torque. The board model's law is PD + feed-forward with no
  integral term (robot_controllers `bench/board.py`), so at p5s-pass3's kp ×4 it holds a constant offset against it.
- **Proof it is the model, not the controller structure:** the `+model-knows` case removes that torque and the error
  drops back to the bare arm's size (worst stop 0.210 mm against 0.197 mm bare).
- **The 5 tasks over 1 mm at the TCP** are dev-010, 017, 020, 035 and 040 (1.40, 1.28, 1.16, 1.06, 1.01 mm).

**Not saturation.**
- The worst task saturates 0.10 % of its samples (bare 0.014 %; with the payload in the model 0.28 %; with the gripper
  known 0.50 %; at most 0.90 % anywhere in the sweep, up to a 1.5 kg object), against a 2 % gate.
- Peak |torque| / cap by joint goes from 0.59 / 1.00 / 0.46 / 0.24 / 0.17 / 0.15 (bare) to
  0.65 / 1.00 / 0.50 / 0.29 / 0.23 / 0.15 (loaded).
- shoulder_lift touches its cap on a few samples in both cases.

**Not time.**
- Over the 41 tasks that settle, the loaded arm enters the 1 mm band in 73.81 s. A perfect tracker on the same tasks
  takes 74.02 s.
- Only two tasks finish late: workspace-dev-009 by 73 ms and workspace-dev-020 by 33 ms. Both sag 0.78-0.85 mm, close
  to the band's edge, so the tool crosses into the band late.

**p1 was already off the gate.** Unloaded it is 6.25 mm with 1/42 passing; loaded it is 7.97 mm with 0/42 passing, and
no task ever settles within 1 mm.

## What this does not say

- **The twin has no compliance**, and p5s-pass3 runs its boards at kp ×4 (AGENTS.md lesson 3, `transfer-risk:stiffness`).
  The sag is about 0.5 mm only because that stiffness is free here. On a real arm, joint compliance adds to it.
- **Point masses only.** See "The load" for what is left out.
- **`+model-knows` is an upper bound.** It knows the payload exactly. A solution would have to identify it through the
  boundary, for example one `identify_pass.py` run with the gripper on, and would land somewhere between the two rows.
- **`+model-knows-gripper` assumes the gripper's mass and centre of mass are known exactly.** The mass is the
  datasheet's; the centre of mass here is Menagerie's. A real picker would identify the gripper once.
- **The sweep is dev only and keeps summaries only.** Its break masses are bracketed at 0.1 kg steps. Its 0.06 and 0.3 kg
  rows equal the case rows.
- **Holdout is reported, never selected on** (OBJECTIVES §4).

## Clip

`reports/media/w3-loaded-check/loaded-p5s-pass3-dev-010.mp4` is gitignored and lives in the local checkout only. It is
10.9 s, muted H.264, 1280×720.

- **What it shows:** loaded p5s-pass3 on workspace-dev-010, the task that fails, at median speed for the set (peak TCP
  speed 0.81 m/s, rank 20 of 42). It plays once in real time, then again at 0.25×.
- **How it is made:** the simulated joint log is replayed on a render-only model, Menagerie's UR5e with Menagerie's
  robotiq_2f85 attached at the flange. That model's flange matches the ruler's tool site to 0 m.
- **Markers:** orange is the object at the TCP. Green is the target path and the target TCP at the same instant.
- **The sag is not visible.** About 1 mm is far below a pixel at this framing; the numbers are in `results.json`.

## Reproduce

```bash
uv run python experiments/w3_loaded_ur5e_2f85/loaded_check.py
MUJOCO_GL=egl uv run python experiments/w3_loaded_ur5e_2f85/render_clip.py --out reports/media/w3-loaded-check/loaded-p5s-pass3-dev-010.mp4
```

- **`loaded_check.py`** takes about 6.5 min in one process (the cases, then the sweep) and writes `results.json`.
- **`render_clip.py`** needs ffmpeg and a MuJoCo Menagerie checkout (`--menagerie`, default `$MUJOCO_MENAGERIE` or
  `~/.cache/mujoco_menagerie`; made with Menagerie 370c439).
- **Pinned to:** robot_controllers f25f485 (src unchanged at the commit recorded in `results.json`) and MuJoCo 3.11.0.
