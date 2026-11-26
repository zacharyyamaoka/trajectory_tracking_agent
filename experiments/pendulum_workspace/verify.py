"""Reconcile the locked pendulum runs with the frozen tapes and an independent tip calculation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from run import DATASET, RUNG, RMS_TARGET_MM, STOP_TARGET_MM, digest, frozen_target, inputs, require


def stop_distances(time, desired, measured, joint_speed):
    tip_speed = np.linalg.norm(np.gradient(desired, time, axis=0), axis=1)
    rests = (tip_speed <= 1e-3) & (np.abs(joint_speed) <= np.deg2rad(0.06))
    edges = np.flatnonzero(np.diff(rests, prepend=False, append=False)).reshape(-1, 2)
    for start, end in edges:
        end_time = time[end - 1]
        if end_time - time[start] >= 0.2 - 1e-9:
            tail = (time[start:end] >= end_time - 0.1 - 1e-9)
            offset = (desired[start:end] - measured[start:end])[tail]
            yield float(np.linalg.norm(offset.mean(axis=0)) * 1000)


def verify(dataset_path, dev_dir, holdout_dir, lock_path):
    dataset = inputs(dataset_path)
    lock = json.loads(lock_path.read_text())
    require(lock["schema"] == "tta.pendulum-controller-lock/1" and lock["top_rung"] == RUNG,
            "expected the highest-rung controller lock")
    verified = []
    for split, directory in (("dev", dev_dir), ("holdout", holdout_dir)):
        summary_path = directory / "summary.json"
        summary = json.loads(summary_path.read_text())
        require(summary["split"] == split and summary["domain"] == "sim" and summary["top_rung"] == RUNG,
                f"wrong {split} scope")
        require(summary["controller"] == lock["controller"] and summary["dataset_manifest_sha256"] == lock["dataset_manifest_sha256"],
                f"{split} run differs from the controller or dataset lock")
        if split == "dev":
            require(digest(summary_path) == lock["development_summary_sha256"], "the development evidence is not the locked input")
        tasks = {task.task_id: task for task in dataset.tasks_in(split)}
        rows = summary["runs"]
        require(len(tasks) == len(rows) and set(tasks) == {row["target"] for row in rows}, f"incomplete {split} corpus")
        for row in rows:
            recording = directory / row["recording"]
            require(digest(recording) == row["recording_sha256"], f"recording changed for {row['target']}")
            tape, target = frozen_target(dataset, tasks[row["target"]])
            require(row["tape_sha256"] == dataset.manifest["files"][tape], f"target hash changed for {row['target']}")
            with np.load(recording) as data:
                for key, expected in (("t", target.t), ("target_q", target.positions),
                                      ("target_qd", target.velocities), ("target_qdd", target.accelerations)):
                    np.testing.assert_array_equal(data[key], expected)
                require(len(data["t"]) == row["samples"], f"incomplete clock for {row['target']}")
                desired = data["target_pose"][:, :3, 3]
                actual = data["measured_pose"][:, :3, 3]
                offset = desired - actual
                rms = float(np.sqrt(np.einsum("ij,ij->", offset, offset) / len(offset)) * 1000)
                stops = list(stop_distances(data["t"], desired, actual, target.velocities[:, 0]))
            require(bool(stops) and len(stops) == row["stops"], f"missing stop for {row['target']}")
            np.testing.assert_allclose([rms, max(stops)], [row["full_trajectory_rms_mm"], row["stop_error_max_mm"]],
                                       rtol=0, atol=1e-10)
            require(all(row["checks"].values()), f"admission check failed for {row['target']}")
            verified.append(row)
    worst_stop = max(verified, key=lambda row: row["stop_error_max_mm"])
    worst_rms = max(verified, key=lambda row: row["full_trajectory_rms_mm"])
    require(worst_stop["stop_error_max_mm"] < STOP_TARGET_MM and worst_rms["full_trajectory_rms_mm"] < RMS_TARGET_MM,
            "the locked controller missed a performance target")
    return {"schema": "tta.pendulum-workspace-qualification/1", "domain": "sim", "top_rung": RUNG,
            "controller_lock_sha256": digest(lock_path), "controller": lock["controller"],
            "dataset_manifest_sha256": lock["dataset_manifest_sha256"], "runs": len(verified),
            "dev_summary_sha256": digest(dev_dir / "summary.json"), "holdout_summary_sha256": digest(holdout_dir / "summary.json"),
            "scored_stops": sum(row["stops"] for row in verified), "all_admission_checks_passed": True,
            "worst_stop": worst_stop, "worst_rms": worst_rms}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--dev", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.dataset, args.dev, args.holdout, args.lock), indent=2, allow_nan=False))
