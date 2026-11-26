# BAM FB conveyor tracking

The existing arm_motion_bench conveyor v2 dataset is a six-drive, home-to-home pick-and-place curriculum for the BAM FB with its closed five-bar, wrist, and claw. It contains 48 development and 16 reporting-only holdout trajectories, evenly split between stationary and moving picks. Use the native Ruckig 1.0 tape for every trajectory. The arm's separately owned benchmark revision determines the fixture and controller provenance. This experiment is outside the UR5e ranked ledger.

The performance targets are below 0.5 mm at the worst measured stop and below 1.0 mm synchronous whole-trajectory TCP RMS. At a rest of at least 0.2 s, the stop metric uses the final 0.1 s. Record simulator faults, contacts, and detector reactions separately from the performance measurements. Report TCP from the encoder/closure model used by the bench.

**Prediction before replay.** On the frozen 1.0 tapes, the unchanged default `record` baseline will miss at least one performance target. Its configured feedback gains and measured-pose gravity term leave friction and tracking lag uncompensated. The published `jtc_baseline` profile may improve tracking with its previously defined controller gains. Its nominal-model and detector-calibration provenance is part of the result.

The simulation fixture is the stock mounted BAM arm from arm_motion_bench. The simulated rig's contact geometry models the drawn belt and support rails, with the benchmark's reduced tip contact model. The 80 mm planning rims and receiving bins are curriculum records. This replay measures arm motion and does not establish payload delivery on the W3 rail-mounted workcell.
