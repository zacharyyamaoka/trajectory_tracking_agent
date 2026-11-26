# Diagnostic prediction for the geared detector trips

This follow-up is specified after observing the first B2 trigger times and threshold crossings, before inspecting the corresponding command and feedback torques. It reads the existing, armed paired recordings at the first trigger tick and preceding host interval. No controller or detector settings are changed.

1. The contact callback will record no contact force on the first triggering rows. The nominal observer sees motor-side data and therefore lacks the twist and output-side friction states added to the plant. A torque mismatch that appears in the geared run before any contact is a false collision trigger within this model.
2. At least one threshold-crossing axis per geared run will show a material motor/link angle split by the trigger tick, defined here as at least one tenth of its full synthetic gap. The aged board torque and the requested torque will have the same sign on the triggering axes. Check each axis, and leave any mismatches visible.
3. Compare by axis on that same host tick against the zero-gap replay. Keep the host command, the last latched motor torque request and the delayed board torque sample explicit. They arrive at different physical times. Use the existing bench and plant code to account for command delay, current-loop response, and reply delay. This evidence can locate an observer startup mismatch and guide a recalibration experiment. The paired conditions jointly change gear compliance and the friction coordinate, so these data cannot attribute the trigger to one parameter in isolation.

Agent: Codex `/root/bam_fb_geared`.
