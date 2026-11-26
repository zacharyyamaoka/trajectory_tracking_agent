"""Verify the identity of the highest-rung workspace replays and score complete tapes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from arm_motion_bench.baselines import bam_fb_sim
from arm_motion_bench.datasets import load_dataset
from arm_motion_bench.kpi_names import GATES
from arm_motion_bench.kpis import run_kpis
from arm_motion_bench.records import Trace
from trajectory_tracking_agent.ruler import metrics


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def observation(dataset, path, task, controller, repeat, *, acquisition):
    tape = dataset.target(task.task_id, max(task.rungs))
    tcp_time, tcp_target, _ = dataset.target_tcp(task.task_id, max(task.rungs))
    trace = Trace.load(path)
    metadata = trace.meta
    identity = (metadata.get("robot"), metadata.get("dataset"), metadata.get("dataset_version"),
                metadata.get("domain"), metadata.get("controller"), metadata.get("task_id"),
                metadata.get("split"), metadata.get("rung"), metadata.get("repeat"))
    expected = ("bam_fb", task.dataset, "v2", "sim", controller, task.task_id, task.split, max(task.rungs), repeat)
    if identity != expected:
        raise ValueError(f"{path.name}: wrong acquisition identity {identity!r}")
    for name, actual, reference in (("target clock", trace.t, tape.t), ("target position", trace.target_q, tape.positions),
                                    ("target velocity", trace.target_qd, tape.velocities),
                                    ("target acceleration", trace.target_qdd, tape.accelerations),
                                    ("TCP clock", trace.t, tcp_time), ("target TCP", trace.target_tcp_pos, tcp_target)):
        if actual.shape != reference.shape or not np.allclose(actual, reference, atol=1e-9, rtol=0):
            raise ValueError(f"{path.name}: {name} differs from the complete frozen tape")
    if not np.isfinite(trace.tcp_pos).all():
        raise ValueError(f"{path.name}: measured TCP is incomplete")

    t, target = trace.t, trace.target_tcp_pos
    stops = metrics.stop_windows(t, metrics.moving_mask(t, target, trace.target_qd))
    if not stops:
        raise ValueError(f"{path.name}: no measured stop")
    position = trace.tcp_pos
    if acquisition == "synchronous-tcp":
        position = trace.optional.get("synchronous_tcp_pos")
        if position is None or position.shape != target.shape or not np.isfinite(position).all():
            raise ValueError(f"{path.name}: current-tick simulator TCP is missing")
    full_rms = metrics.tool_track_rms_mm(target, position, np.ones(len(t), dtype=bool))
    stop_error = metrics.stop_error_max_mm(t, target, position, stops)
    stock = run_kpis(trace, dataset.info)
    failed = []
    for name, (op, threshold) in GATES.items():
        value = stock.get(name, math.nan)
        comparisons = {"<=": value <= threshold, ">=": value >= threshold, "==": value == threshold}
        if not math.isfinite(value) or not comparisons[op]:
            failed.append(name)
    return {"task": task.task_id, "repeat": repeat, "stop_error_max_mm": stop_error,
            "full_trajectory_rms_mm": full_rms, "stop_count": len(stops), "samples": len(t),
            "faults": metadata.get("faults", []), "failed_gates": failed,
            "idealized": metadata.get("idealized"), "trace_sha256": digest(path),
            "controller_sha256": metadata.get("controller_sha256"), "rung": metadata["rung"],
            "bench_commit": metadata.get("source", {}).get("git_sha"),
            "arm_model_key": metadata.get("source", {}).get("arm_model_key"),
            "target_sha256": dataset.manifest["files"][f"{task.task_id}.npz"]}


def run_audit(dataset_dir, traces_dir, controller, split, repeats, acquisition):
    dataset = load_dataset(dataset_dir)
    rows, issues = [], []
    for task in dataset.tasks_in(split):
        for repeat in repeats:
            path = bam_fb_sim.trace_path(traces_dir, "bam_fb", controller, task.dataset, "v2", split, task.task_id,
                                         max(task.rungs), repeat)
            try:
                rows.append(observation(dataset, path, task, controller, repeat, acquisition=acquisition))
            except (OSError, ValueError) as error:
                issues.append({"task": task.task_id, "repeat": repeat, "reason": str(error)})
    metrics_names = ("stop_error_max_mm", "full_trajectory_rms_mm")
    revisions = {row["controller_sha256"] for row in rows}
    if len(revisions) > 1:
        raise ValueError("replay directory mixes controller revisions")
    return {"controller": controller, "split": split, "acquisition": acquisition, "rows": rows, "incomplete": issues,
            "controller_sha256": next(iter(revisions), None),
            "dataset_manifest_sha256": digest(dataset_dir / "manifest.json"),
            "requested": len(dataset.tasks_in(split)) * len(repeats),
            "worst_observed": {name: max(rows, key=lambda row: row[name]) for name in metrics_names} if rows else {}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("traces", type=Path)
    parser.add_argument("--controller", required=True)
    parser.add_argument("--split", default="dev", choices=("dev", "holdout"))
    parser.add_argument("--repeats", nargs="+", type=int, default=[0])
    parser.add_argument("--acquisition", default="encoder-fk", choices=("encoder-fk", "synchronous-tcp"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_audit(args.dataset, args.traces, args.controller, args.split, args.repeats, args.acquisition)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"{len(result['rows'])}/{result['requested']} complete, {len(result['incomplete'])} issues")
    return 1 if result["incomplete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
