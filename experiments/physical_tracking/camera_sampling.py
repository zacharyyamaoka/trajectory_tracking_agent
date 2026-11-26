"""Measure temporal interpolation error on the frozen CAN 11 target tapes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from arm_motion_bench.datasets import load_dataset
from arm_motion_bench.robots.pendulum import tip_poses

from trajectory_tracking_agent.ruler import metrics

FRAME_RATES_HZ = (15, 30, 60, 100)
FRAME_PHASES = (0.0, 0.25, 0.5, 0.75)


def read_tapes(path):
    dataset = load_dataset(path)
    if dataset.info.robot != "pendulum" or dataset.manifest.get("version") != "v2":
        raise ValueError("expected the CAN 11 workspace v2 dataset")
    for task in dataset.tasks:
        if max(task.rungs) != 1.0:
            raise ValueError(f"unexpected highest rung for {task.task_id}")
        trajectory = dataset.target(task.task_id, rung=1.0)
        time, position, _ = dataset.target_tcp(task.task_id, rung=1.0)
        np.testing.assert_allclose(trajectory.t, time, atol=1e-12, rtol=0)
        stops = metrics.stop_windows(time, metrics.moving_mask(time, position, trajectory.velocities))
        if not stops:
            raise ValueError(f"{task.task_id} has no measurable stop")
        yield task.task_id, trajectory, time, position, stops


def trial(tape, rate_hz, phase):
    target, trajectory, time, position, stops = tape
    # WHY add exact endpoints: isolate interpolation between frames from start/end coverage and camera pose noise.
    interior = (np.arange(1 + int(time[-1] * rate_hz)) + phase) / rate_hz
    optical_time = np.r_[0.0, interior[(interior > 0) & (interior < time[-1])], time[-1]]
    camera_q = trajectory.resample(optical_time).positions[:, 0]
    optical_position = tip_poses(camera_q)[:, :3, 3]
    recovered = np.column_stack([np.interp(time, optical_time, coordinate) for coordinate in optical_position.T])
    rms = metrics.tool_track_rms_mm(position, recovered, np.ones(len(time), dtype=bool))
    stop = metrics.stop_error_max_mm(time, position, recovered, stops)
    return {"target": target, "frame_phase": phase, "full_trajectory_rms_mm": rms, "stop_error_max_mm": stop}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tapes = list(read_tapes(args.dataset))
    result = {"schema": "tta.can11-camera-sampling/1", "scope": "noiseless target-tape interpolation sensitivity",
              "target_count": len(tapes), "rung": 1.0, "phases": list(FRAME_PHASES),
              "dataset_manifest_sha256": hashlib.sha256((args.dataset / "manifest.json").read_bytes()).hexdigest(),
              "rates": {}}
    for rate in FRAME_RATES_HZ:
        rows = [trial(tape, rate, phase) for tape in tapes for phase in FRAME_PHASES]
        result["rates"][str(rate)] = {"scenarios": len(rows),
                                     "worst": {metric: max(rows, key=lambda row: row[metric]) for metric in
                                               ("full_trajectory_rms_mm", "stop_error_max_mm")}}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
