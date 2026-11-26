# CAN 11 transfer on the adopted rack twin

This is a development-only transfer check for the [simulation goal](../../goals/G2-bam-fb-and-pendulum-simulation.md). The [qualified pendulum corpus](../pendulum_workspace/README.md) used the compact rigid plant. The adopted rack model `can11-r18a` includes LuGre friction, rotor-periodic torque ripple, limiting and command delay. Its resolved gear backlash is absent. That leaves load-side accuracy unmeasured.

## Prediction before replay

Keep the same frozen workspace v2 development tapes and periods at 1.0. Replay the three archived physical `ff_model` tours as sent, including their historical command gains. Then run all 40 development tapes on the adopted rack model with the same real-data feedforward and a 1× command multiplier on the stock board PID. No coefficient is tuned from these replays. We predict the nominal-gain simulation will miss at least one of the 0.5 mm stop and 1.0 mm full-trajectory RMS targets. The richer rack plant has dynamics absent from the compact plant and the historical feedforward is distinct from the qualified simulation controller.

Report positions on the nominal 100 Hz plan grid, after verifying that the archive and the replay issued the frozen targets to the source precision. Use the synchronous tool-point distance, its RMS over the whole tape, and the frozen final-0.1-second stop metric. The archive has encoder positions and a command clock. It does not contain a common-clock measurement of the load-side tip. Record only development diagnostics here. No hardware runs and no UR ruler changes.
