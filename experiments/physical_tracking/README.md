# Physical tracking evidence

[`audit_archives.py`](audit_archives.py) reads the saved physical traces with the bench's frozen dataset loader. For each highest-rung task it compares the clock, joint positions, velocities and accelerations, and TCP references against the immutable tape before calculating either performance metric. It scores only the prescribed tape, including the holds already on that tape. Additional run-out is beyond that measurement interval.

The [archive evidence](archive-evidence.json) is an encoder-FK diagnostic. The CAN 11 source logs board replies on the command clock. It has no independent calibrated measurement of the tip or acquisition timestamp on the load side. The highest-rung BAM FB legacy recording has 257 exchanges on its command clock, a median exchange interval of 17.012 ms, and an overspeed event. Its command clock and target coverage differ from the immutable 100 Hz tape.

Run it with the arm_motion_bench Python environment and provide the checkout as the first argument. The optional `--legacy-bam` takes the imported workspace trace and its original raw-run directory. The script reads stored data and has no hardware entry point.
