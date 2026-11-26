# BAM FB geared tracking stress

This experiment measures the locked BAM FB simulation controller at rung 1.0 on two workspace dev routes and one conveyor dev route. The [prediction](prediction.md) fixes the routes and comparisons. The [full nominal qualification](../bam_fb_transfer/qualification.json) has its own 118-route result.

## Measured results

The zero-gap replays matched the archived claw positions exactly over all 1,409 samples. The assembled frame, five-bar closure and working branch also matched at all 33 waypoint checks.

| Rung 1.0 dev route | Zero-gap claw RMS / worst stop (mm) | B2 claw RMS / worst stop (mm) | B2 + 1.25× friction claw RMS / worst stop (mm) | Armed detector trip, B2 / B2 + friction (ms) |
| --- | ---: | ---: | ---: | ---: |
| Workspace 000 | 0.575 / 0.139 | 70.036 / 1.369 | 69.875 / 1.038 | 20 / 10 |
| Workspace 038 | 0.962 / 0.286 | 113.685 / 163.290 | 113.741 / 163.390 | 10 / 10 |
| Conveyor 018 | 0.583 / 0.418 | 274.850 / 481.726 | 274.905 / 481.811 | 10 / 10 |

All six geared runs interrupted the reference with the armed detector's stop-and-hold reaction. The resulting full-record errors include the skipped motion. All six kept the working branch and recorded zero contact force and zero MuJoCo warnings. The workspace 000 encoder FK reported a 0.088 mm worst stop under B2, while the simulated claw's worst stop was 1.369 mm. [Per-route evidence and frame verification](results.json)

## Detector startup

The rigid-arm momentum observer crossed its threshold at the first or second 10 ms host tick. In B2 with nominal friction, the threshold crossings were J2 and C1 at 1.70× and 1.27× on workspace 000, W1 at 1.65× on workspace 038, and J1 and W1 at 1.18× and 1.006× on conveyor 018. Peak claw error over those same trigger-inclusive windows was 1.463, 0.236 and 0.462 mm. None of the matched zero-gap traces crossed at the same tick.

On every threshold-crossing axis the motor/link split was at least a tenth of the synthetic gap, and requested and reported applied torques shared a sign. The request latches after 5.5 ms and feeds a 200 Hz current-loop model (0.796 ms time constant). The five-bar replies are 1.5 ms old. Wrist replies have zero modeled delay. The observer uses the applied torque averaged over the just-completed 10 ms interval. The detector therefore needs a startup prediction that accounts for shaft motion and the measured torque timing. Any observer recalibration needs a paired contact test as well as a contact-free test. [Predeclared torque diagnostic](detector-prediction.md), [paired torque and timing evidence](detector-evidence.json)

## Friction location ablation

Moving B2 friction back to the original motor hinges leaves the same synthetic clearances and gear stiffness in place. Workspace 038 and conveyor 018 still tripped on W1 at 10 ms, at 1.30× and 1.22× the threshold. Workspace 000 now completed with the detector armed. Its actual claw still exceeded both targets at 1.558 mm RMS and 1.541 mm max stop. Motor encoder FK reported 0.531 mm RMS and 0.086 mm max stop. With the original friction implementation on the motor coordinate, the geared model alone was enough to produce both false detector trips and meaningful unobserved tool error. The change in friction coordinate affected whether workspace 000 tripped. [Predeclared ablation](friction-location-prediction.md), [per-route results](motor-friction-results.json), [detector torque evidence](motor-friction-detector-evidence.json)

## Fixture and measurements

- The [stock homing topology check](../bam_fb_transfer/gear-check.json) verifies each gearbox independently. The homing MJCF has no named claw TCP. The replay imports its synthetic B2 clearances and gear stiffness through `hidden_specs("B2")`, then applies `gear_backlash.wrap.BacklashModel` to the original composed **tracking** MJCF. This preserves the CAD claw site, physical stops and five-bar link closure. The gears start with centered clearance and zero twist.
- The zero-gap control replays the same clock, motors, contact checks, and armed detector against the archived benchmark. The geometry check compares the actual TCP frame and closure at 33 target poses. A paired motor/gap perturbation confirms that opposite rotations leave the claw frame fixed on each axis.
- The stock wrist friction switches on link speed between sliding and breakaway values. The three five-bar drives keep their constant Coulomb value. Friction and damping act on the output tendons in the geared case. One companion condition increases all six friction values by the bench's existing 1.25× factor. This isolates the paired change in friction under B2. The model still uses switched Coulomb wrist friction. The gap sizes, friction factor and center-zero assumption are simulated cases.
- Actual-claw measurements use the simulated claw site's position on the benchmark clock. Motor encoder FK includes the original simulated board reply ages. Its difference from actual claw combines reply age, gearbox twist and closure compliance. Current-tick motor and link angles are saved separately. Track RMS includes every sample and each hold. The max stop measurement averages position error over the final 0.1 s of each stock stop window.
- Detector reactions, collisions, closure branch, warnings and clock checks are retained. A stopped-and-held tape that continues recording still fails the stress run if the detector activated. No tuning or holdout acquisition takes place in this lane.

## Reproduce

Use the sibling motion bench's BAM FB Python runner from its simulation environment. Add the tracking package, `robot_models`, `dataclass_values` and `robot_controllers` source directories to `PYTHONPATH`. Supply the motion bench checkout through `--bench` and an ignored working directory through `--output`. The runner reads the existing locked source and calibration snapshot in `outputs/bam-fb-conveyor/frozen-candidate/` and the two nominal trace folders shown in [the runner](replay.py). Use `--resume` to reuse committed-input-checked zero-gap traces after an interrupted geared replay. The runner writes [`results.json`](results.json) after each completed route and keeps the raw traces in the chosen output directory. Add `--resume --motor-friction-ablation` after the main replay to write the friction-location comparison as [`motor-friction-results.json`](motor-friction-results.json). [The diagnostic](diagnose.py) accepts the recording directory and `--summary` to rebuild either per-axis torque comparison.
