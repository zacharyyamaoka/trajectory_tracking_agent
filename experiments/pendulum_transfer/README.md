# CAN 11 transfer on the adopted rack twin

This is a development-only transfer check for the [simulation goal](../../goals/G2-bam-fb-and-pendulum-simulation.md). The [qualified pendulum corpus](../pendulum_workspace/README.md) used the compact rigid plant. The adopted rack model `can11-r18a` includes LuGre friction, rotor-periodic torque ripple, limiting and command delay. Its resolved gear backlash is absent. That leaves load-side accuracy unmeasured.

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

## Reproduce the archived comparison

The runner uses the [archived rack code](https://github.com/zacharyyamaoka/bam_ws/tree/05573c957f9c7fb073bedf9a376c30ea38715305/src/dev/bam_rack_twin) through the rack Python environment with MuJoCo 3.11.0. Provide the workspace paths through `BAM_WS`, `ARM_MOTION_BENCH`, `ROBOT_MSGS`, and `ROBOT_TRAJECTORIES`. Run from this repository.

```bash
mkdir -p outputs/pendulum-transfer/source-05573c957
git -C "$BAM_WS" archive --format=tar 05573c957f9c7fb073bedf9a376c30ea38715305 src/dev/bam_rack_twin | tar -xf - -C outputs/pendulum-transfer/source-05573c957
PYTHONPATH="$PWD/outputs/pendulum-transfer/source-05573c957/src/dev/bam_rack_twin:$ARM_MOTION_BENCH/src:$ROBOT_MSGS/src:$ROBOT_TRAJECTORIES/src:$PWD/src" OPENBLAS_NUM_THREADS=1 "$BAM_WS/src/dev/bam_rack_twin/.venv/bin/python" experiments/pendulum_transfer/replay.py "$ARM_MOTION_BENCH/datasets/pendulum/workspace/v2" "$ARM_MOTION_BENCH/outputs/runs_real/pendulum/ff_model/workspace-v2/dev" outputs/pendulum-transfer/r18a.json
```

The old real runs used 2× command multipliers on both board gains. The paired twin replay retains those multipliers. The nominal simulation uses 1× with the same identified `ff_model` feedforward. Model ripple is resolved from the existing recorded input when the archived runner has it. The retained tape-position match is within the stock command's microradian rounding. [Replay source](replay.py)

The historical CAN 11 camera estimate of 4.49 arcmin had a 95% interval of approximately −19 to +34 arcmin and was refused by the rack. The gear-gap parameter reported by the [Sim2Real frozen-schedule oracle](https://github.com/zacharyyamaoka/sim2real/blob/7355462d9dd38e127c122c5cccbd546a67916ba1/src/sim2real/cards/frozen_reports/can11-frozen-schedule-2f32ddbc.json) was recovered against a sealed simulated 0.002 rad gap. The stock camera review aligns phase and angle zero against the same encoder run. Those sources establish the model capability and the physical observability gap. [Rack backlash acceptance test](https://github.com/zacharyyamaoka/bam_ws/blob/05573c957f9c7fb073bedf9a376c30ea38715305/src/dev/bam_rack_twin/tests/test_priors_gravity.py) · [Rack camera comparison method](https://github.com/zacharyyamaoka/bam_ws/blob/05573c957f9c7fb073bedf9a376c30ea38715305/src/dev/bam_rack_twin/docs/can11_envelope_challenge.py)
