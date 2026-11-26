# Armed gear friction location ablation

Freeze the three original development trajectories at the same 1.0 rung and the same locked controller. Keep the collision detector armed and the same clearance, gear stiffness, joint model, contact callback, timing and nominal friction magnitudes. Set only `BacklashModel(output_friction=False)`. The bench's hard five-bar friction will stay on the original motor-coordinate joints and the switched wrist loss will again use motor speed. This is a software ablation of the friction coordinate and force mapping. A real gearbox can contain losses on both sides.

Prediction: at least one replay will still cross the detector threshold within the first 20 ms in the absence of contact. A trip here shows that relocating nominal friction to output tendons is unnecessary for the startup failure on that route. Agreement of the triggering axes between both cases would strengthen the result. If any motor-friction run preserves the reference, report it and do not attribute that route's original trip to loss of motion alone. This comparison does not separate gear elasticity from clearance or quantify either on hardware.

Agent: Codex `/root/bam_fb_geared`.
