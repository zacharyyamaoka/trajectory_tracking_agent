# BAM FB gear-model readiness

[`check_twin.py`](check_twin.py) loads Sim2Real's stock six-drive full-arm homing model twice. `B0` provides the rigid reference. `B2` adds each motor's gap hinge and places the corresponding friction on the output tendon. The model retains its closed five-bar equality. The check moves the motor and gap by opposite amounts and confirms every link transform stays fixed. Then it holds the motor angle fixed and verifies that the link angle changes.

The [recorded gear-model check](gear-check.json) verifies the fixture on MuJoCo 3.11.0. The modeled clearances are synthetic homing parameters. Transfer to the tracking benchmark still needs an independent replay with the same target tape and tool frame. The physical deployment needs measured clearances and a load-side truth signal. The [tracking archive audit](../physical_tracking/README.md) explains the available measurements.
