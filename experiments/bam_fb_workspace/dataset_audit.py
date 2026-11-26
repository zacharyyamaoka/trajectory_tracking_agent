"""Validate the frozen BAM FB workspace inventory and its top-rung chains."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from arm_motion_bench.datasets import load_dataset

from audit import digest


def verify(path):
    dataset = load_dataset(path)
    manifest = dataset.manifest
    if (manifest["robot"], manifest["dataset"], manifest["version"]) != ("bam_fb", "workspace", "v2"):
        raise ValueError("wrong BAM FB workspace corpus")
    if digest(path / "tasks.jsonl") != manifest["tasks_sha256"]:
        raise ValueError("task list does not match its manifest")
    if {item.name for item in dataset.tapes_dir.glob("*.npz")} != set(manifest["files"]):
        raise ValueError("frozen tape and TCP-cache inventories differ")
    for name, checksum in manifest["files"].items():
        if digest(dataset.tapes_dir / name) != checksum:
            raise ValueError(f"{name} differs from its frozen SHA-256")

    results = {}
    for split in ("dev", "holdout"):
        previous = dataset.info.home_q
        sample_count = 0
        points = []
        tasks = dataset.tasks_in(split)
        if len(tasks) != manifest["counts"][split]["total"]:
            raise ValueError(f"wrong frozen {split} task count")
        for task in tasks:
            rung = max(task.rungs)
            if rung != 1.0:
                raise ValueError(f"unexpected highest rung for {task.task_id}")
            tape = dataset.target(task.task_id, rung)
            tcp_time, tcp, _ = dataset.target_tcp(task.task_id, rung)
            np.testing.assert_allclose(tape.positions[0], previous, atol=1e-9, rtol=0)
            np.testing.assert_array_equal(tape.t, tcp_time)
            if not all(np.isfinite(array).all() for array in (tape.positions, tape.velocities, tape.accelerations, tcp)):
                raise ValueError(f"{task.task_id} contains non-finite samples")
            previous = tape.positions[-1]
            points.append(tcp)
            sample_count += len(tape.t)
        np.testing.assert_allclose(previous, dataset.info.home_q, atol=1e-9, rtol=0)
        tcp_points = np.concatenate(points)
        results[split] = {"tasks": len(tasks), "samples": sample_count, "highest_rung": 1.0,
                          "tcp_bounds_m": [np.min(tcp_points, axis=0).tolist(), np.max(tcp_points, axis=0).tolist()]}
    return {"dataset_manifest_sha256": digest(path / "manifest.json"), "files_verified": len(manifest["files"]), "splits": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    print(json.dumps(verify(parser.parse_args().dataset), indent=2, allow_nan=False))
