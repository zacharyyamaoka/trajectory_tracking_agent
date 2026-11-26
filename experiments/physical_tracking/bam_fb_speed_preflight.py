"""Check frozen BAM FB tapes with the stock file-only physical speed preflight."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from arm_motion_bench.datasets import load_dataset


def load_stock_checker(path):
    spec = importlib.util.spec_from_file_location("bam_fb_real_speedcap", path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker


def audit_dataset(bench, kind, checker, bundle):
    dataset = load_dataset(bench / "datasets" / "bam_fb" / kind / "v2")
    results = {}
    for rung in (checker.MAX_SPED_UP_FRACTION, 1.0):
        tasks = [task for task in dataset.tasks if rung in task.rungs]
        peaks = np.zeros(len(checker.NAMES))
        refusals = []
        plan = {"dataset_name": kind, "speed_fraction": rung}
        (bundle / "plan.json").write_text(json.dumps(plan))
        for task in tasks:
            target = dataset.target(task.task_id, rung)
            if tuple(name.lower() for name in target.joint_names) != tuple(name.lower() for name in checker.NAMES):
                raise ValueError(f"unexpected stock drive order on {task.task_id}")
            time, position, velocity = map(np.asarray, (target.t, target.positions, target.velocities))
            np.savez(bundle / "samples.npz", t=time, q_reference=position, qd_reference=velocity)
            slopes = np.diff(position, axis=0) / np.diff(time)[:, None]
            peak = np.rad2deg(np.maximum(np.abs(velocity).max(axis=0), np.abs(slopes).max(axis=0)))
            peaks = np.maximum(peaks, peak)
            reasons = checker.preflight(bundle)
            if reasons:
                refusals.append({"task": task.task_id, "reasons": reasons})
        results[str(rung)] = {
            "available": len(tasks), "by_split": dict(Counter(task.split for task in tasks)),
            "passed_stock_tape_speed_check": len(tasks) - len(refusals),
            "commanded_peak_deg_s": dict(zip(checker.NAMES, peaks.tolist(), strict=True)),
            "one_refusal_example": refusals[0] if refusals else None,
        }
    return {"frozen_routes": len(dataset.tasks),
            "manifest_sha256": hashlib.sha256((dataset.path / "manifest.json").read_bytes()).hexdigest(), "rungs": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bench", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checker_path = args.bench / "scripts/bam_fb_real_speedcap.py"
    checker = load_stock_checker(checker_path)
    with tempfile.TemporaryDirectory(prefix="tape-preflight-") as folder:
        datasets = {kind: audit_dataset(args.bench, kind, checker, Path(folder)) for kind in ("workspace", "conveyor")}
    result = {"schema": "tta.bam-fb-physical-tape-speed-preflight/1", "physical_acquisition": False,
              "scope": "stock speed preflight on frozen reference tapes. These files contain no final servo command or hardware readout.",
              "stock_checker_sha256": hashlib.sha256(checker_path.read_bytes()).hexdigest(),
              "max_sped_up_fraction": checker.MAX_SPED_UP_FRACTION,
              "joint_cap_deg_s": {drive: checker.cap_deg_s(drive) for drive in checker.NAMES}, "datasets": datasets}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
