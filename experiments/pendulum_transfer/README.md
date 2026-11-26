# CAN 11 transfer on the adopted rack twin

This is a development-only transfer check for the [simulation goal](../../goals/G2-bam-fb-and-pendulum-simulation.md). The [qualified pendulum corpus](../pendulum_workspace/README.md) used the compact rigid plant. The adopted rack model `can11-r18a` includes LuGre friction, rotor-periodic torque ripple and drive limits. Its adopted parameters do not contain a measured transmission gap. That leaves physical load-side accuracy unmeasured.

## Prediction before replay

Keep the same frozen workspace v2 development tapes and periods at 1.0. Replay the three archived physical `ff_model` tours as sent, including their historical command gains. Then run all 40 development tapes on the adopted rack model with the same real-data feedforward and a 1× command multiplier on the stock board PID. No coefficient is tuned from these replays. We predict the nominal-gain simulation will miss at least one of the 0.5 mm stop and 1.0 mm full-trajectory RMS targets. The richer rack plant has dynamics absent from the compact plant and the historical feedforward is distinct from the qualified simulation controller.

Report positions on the nominal 100 Hz plan grid, after verifying that the archive and the replay issued the frozen targets to the source precision. Use the synchronous tool-point distance, its RMS over the whole tape, and the frozen final-0.1-second stop metric. The archive has encoder positions and a command clock. It does not contain a common-clock measurement of the load-side tip. Record only development diagnostics here. No hardware runs and no UR ruler changes.

## Full-speed development results

| CAN 11 encoder estimate | Runs meeting both targets | Worst stop (mm) | Worst full-trajectory RMS (mm) |
| --- | ---: | ---: | ---: |
| Archived physical `ff_model`, 2× command gains | 95/120 | 1.3410 | 1.2077 |
| Adopted LuGre twin, exact archived commands | 101/120 | 0.9814 | 1.0528 |
| Adopted LuGre twin, `ff_model` at 1× command gains | 5/40 | 1.7133 | 1.6590 |

The largest paired encoder trace difference was 1.1649 mm RMS. All 40 frozen development targets appear in each of the three matched tours and once in the 1× simulation. The stock rack twin exposes a load-side channel only with its separated transmission model active. `r18a` has neither a resolved gear gap nor gear stiffness, so the replay exposes only its encoder-equivalent trace. The archived physical runs also contain only the encoder trace. [Score evidence](r18a-evidence.json)

## Prediction for the locked controller transfer

Replay the [locked identified controller](../pendulum_workspace/controller-lock.json) and its 1× alternative on the same 40 development tapes at 100 Hz. Map the original per-tick position, secant velocity and feedforward torque into stock rack commands. The adopted model supplies rack delay, drive and encoder dynamics. Keep the controller's original lookahead, fit and damping lag. Compare both gain settings with the historical `ff_model` at matching gains. Expect the locked gains to lower worst stop and RMS versus the nominal identified version, and expect at least one requested target to fail with nominal identified gains on the adopted model.

For the separate synthetic stress, freeze those same commands before revealing a transmission gap to the plant. Use the Sim2Real oracle's synthetic CAN 11 total gap of 0.002 rad and its documented rotor inertia share of 0.022, the rack wrapper's default stiff contact, and the adopted LuGre law acting entirely on the load. Stock LuGre supports one side at a time. The synthetic truth belongs only to the plant and scorer. Expect encoder-to-load tool-point disagreement to exceed 0.1 mm on at least one of the 40 tapes. The gap and LuGre placement in this variant are stress-test assumptions.

## Locked controller transfer results

| Controller and CAN 11 simulation estimate | Runs meeting both targets | Worst stop (mm) | Worst full-trajectory RMS (mm) |
| --- | ---: | ---: | ---: |
| Historical `ff_model`, 1× stiffness and 1× damping, adopted twin encoder | 5/40 | 1.7133 | 1.6590 |
| Historical `ff_model`, 4× stiffness and 2× damping, adopted twin encoder | 40/40 | 0.3595 | 0.4691 |
| G2 identified feedforward, 1× stiffness and 1× damping, adopted twin encoder | 0/40 | 3.0658 | 3.1315 |
| G2 locked controller, 4× stiffness and 2× damping, adopted twin encoder | 31/40 | 0.6122 | 0.9207 |
| G2 locked controller, synthetic gap twin encoder | 29/40 | 0.7110 | 0.9245 |
| G2 locked controller, synthetic gap twin load | 27/40 | 0.7952 | 0.9797 |

The historical feedforward at the higher gains was the only configuration to meet both targets on all 40 development paths. Those gains were tested in simulation. The locked G2 controller met the RMS target on the adopted twin and missed the stop target on nine paths. With identical per-task command hashes in the synthetic gap case, the largest instantaneous encoder-to-load difference was 0.3467 mm on `workspace-dev-023`. This test provides a synthetic separation check. Physical load-side tracking remains unverified. [Locked transfer score evidence](locked-evidence.json)

## Prediction for historical feedforward under synthetic backlash

Keep the exact historical `ff_model` command streams that ran at 4× stiffness and 2× damping on the adopted model. Apply those same commands to the pre-existing synthetic LuGre-plus-gap plant at the same 100 Hz clock. Use all 40 development tapes, score both encoder and load, and preserve the prior locked-controller gap result. Expect the simulated load to meet both targets on more than 27 paths but miss the 0.5 mm stop target on at least one path. The adopted-model stop margin is 0.1405 mm, while the synthetic gap can separate the encoder and load by about 0.34 mm at the tip.

## Reproduce the archived comparison

The runner uses rack source revision `05573c957f9c7fb073bedf9a376c30ea38715305` through the rack Python environment with MuJoCo 3.11.0. Set `RACK_WORKTREE`, `ARM_MOTION_BENCH`, `ROBOT_MSGS`, and `ROBOT_TRAJECTORIES` to local checkouts. Run from this repository.

```bash
mkdir -p outputs/pendulum-transfer/source-05573c957
git -C "$RACK_WORKTREE" archive --format=tar 05573c957f9c7fb073bedf9a376c30ea38715305 src/dev/bam_rack_twin | tar -xf - -C outputs/pendulum-transfer/source-05573c957
PYTHONPATH="$PWD/outputs/pendulum-transfer/source-05573c957/src/dev/bam_rack_twin:$ARM_MOTION_BENCH/src:$ROBOT_MSGS/src:$ROBOT_TRAJECTORIES/src:$PWD/src" OPENBLAS_NUM_THREADS=1 "$RACK_WORKTREE/src/dev/bam_rack_twin/.venv/bin/python" experiments/pendulum_transfer/replay.py "$ARM_MOTION_BENCH/datasets/pendulum/workspace/v2" "$ARM_MOTION_BENCH/outputs/runs_real/pendulum/ff_model/workspace-v2/dev" outputs/pendulum-transfer/r18a.json
```

The old real runs used 2× command multipliers on both board gains. The paired twin replay retains those multipliers. The nominal simulation uses 1× with the same identified `ff_model` feedforward. Model ripple is resolved from the existing recorded input when the archived runner has it. The retained tape-position match is within the stock command's microradian rounding. [Replay source](replay.py)

## Reproduce the locked controller transfer

Use the archive and environment from the archived comparison above, and point `ROBOT_CONTROLLERS` to the source at the original lock revision `04d0d58804682237ff606cf85f8958e73a2086df`.

```bash
PYTHONPATH="$PWD/outputs/pendulum-transfer/source-05573c957/src/dev/bam_rack_twin:$ARM_MOTION_BENCH/src:$ROBOT_MSGS/src:$ROBOT_TRAJECTORIES/src:$ROBOT_CONTROLLERS/src:$PWD/src:$PWD/experiments/pendulum_workspace" OPENBLAS_NUM_THREADS=1 "$RACK_WORKTREE/src/dev/bam_rack_twin/.venv/bin/python" experiments/pendulum_transfer/locked_controller.py "$ARM_MOTION_BENCH/datasets/pendulum/workspace/v2" outputs/pendulum-transfer/locked.json
```

The transfer keeps the rack runner's start pose, prelude duration, torque cap and 100 Hz scoring window. During the prelude the identified controller holds its start pose with its own gravity feedforward. The controller command grid in the scoring window stays unchanged. The original compact bench and the rack command extraction agreed on all five command fields within `1e-12` SI units at both gains for development tapes `000` and `026`. Every transferred tape also produced identical command arrays when host position, velocity and torque observations were varied. The rack replay keeps its board feedback and latch setting, which resolves to zero added delay in `r18a`.

The bridge resolves model gravity in the rack's currently accepted frame, as the stock runner does. The 1× historical summary reproduces the stock runner on all 40 cases. On tape `027`, all 356 samples of time, encoder position, velocity, torque and mode matched exactly. [Transfer source](locked_controller.py)

The historical CAN 11 camera estimate of 4.49 arcmin had a 95% interval of approximately −19 to +34 arcmin and was refused by the rack. The gear-gap parameter in the Sim2Real frozen-schedule oracle `can11-frozen-schedule-2f32ddbc.json` was recovered against a sealed simulated 0.002 rad gap in revision `7355462d9dd38e127c122c5cccbd546a67916ba1`. The rack camera review aligns phase and angle zero against the same encoder run. See `tests/test_priors_gravity.py` and `docs/can11_envelope_challenge.py` in the archived rack source.
