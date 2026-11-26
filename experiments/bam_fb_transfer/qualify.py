"""Independently verify one locked BAM FB controller on both complete simulation corpora."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from arm_motion_bench.datasets import load_dataset
from arm_motion_bench.kpis import false_alarm, run_kpis_v2_with_notes
from arm_motion_bench.records import Trace
from arm_motion_bench.scorecard import gate_passes, gates_v2

from trajectory_tracking_agent.ruler import metrics

STOP = "stop_error_max_mm"
RMS = "full_trajectory_rms_mm"
CORPORA = {
    "workspace": ((42, 12), "145dc741e48691920478e2084839cee0cb523c5c698a31f49bf5a3cf95ef8c9b"),
    "conveyor": ((48, 16), "9e378456c94bde64ac2837c0dd3882fd141146d61e3d8809067f7b47d9553cff"),
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, explanation):
    if not condition:
        raise ValueError(explanation)


def verify_data(bench, kind):
    counts, expected = CORPORA[kind]
    path = bench / "datasets" / "bam_fb" / kind / "v2"
    manifest = path / "manifest.json"
    require(digest(manifest) == expected, f"the BAM FB {kind} target manifest changed")
    dataset = load_dataset(path)
    tasks = dataset.tasks
    require(tuple(len(dataset.tasks_in(split)) for split in ("dev", "holdout")) == counts,
            f"{kind} split is incomplete")
    require(digest(path / "tasks.jsonl") == dataset.manifest["tasks_sha256"], f"{kind} task metadata changed")
    require(all(max(task.rungs) == 1.0 for task in tasks), f"{kind} does not declare rung 1.0 as its highest")
    for filename, file_hash in dataset.manifest["files"].items():
        require(digest(dataset.tapes_dir / filename) == file_hash, f"{kind}/{filename} differs from its frozen tape digest")
    return dataset, expected


def measure(path, dataset, kind, task, lock):
    trace = Trace.load(path)
    meta = trace.meta
    identity = (meta.get("robot"), meta.get("dataset"), meta.get("dataset_version"), meta.get("domain"), meta.get("task_id"),
                meta.get("split"), meta.get("rung"), meta.get("repeat"), meta.get("controller_sha256"))
    expected = ("bam_fb", kind, "v2", "sim", task.task_id, task.split, 1.0, 0, lock["controller_sha256"])
    require(identity == expected and meta.get("idealized") is False, f"{path.name} does not match the independent controller lock")
    source = meta["source"]
    require((source["git_sha"], source["arm_model_key"]) == (lock["bench_commit"], lock["arm_model_key"]),
            f"{path.name} does not match the locked simulation model")
    target = dataset.target(task.task_id, rung=1.0)
    times, desired, rotation = dataset.target_tcp(task.task_id, rung=1.0)
    for data, frozen in ((trace.t, times), (trace.target_q, target.positions), (trace.target_qd, target.velocities),
                         (trace.target_qdd, target.accelerations), (trace.target_tcp_pos, desired), (trace.target_tcp_rot, rotation)):
        require(data.shape == frozen.shape and np.allclose(data, frozen, atol=1e-10, rtol=0),
                f"{path.name} differs from the frozen target")
    actual = trace.optional.get("synchronous_tcp_pos")
    require(actual is not None and actual.shape == desired.shape and np.isfinite(actual).all(),
            f"{path.name} does not have a complete current-tick tool trace")
    require(not meta.get("aborted"), f"{path.name} aborted before complete qualification")
    # WHY calculate in Cartesian coordinates here: the underlying plant can leave the expected assembly even when an
    # encoder-FK lookup closes its two passive hinges on the expected branch.
    rms_mm = float(np.sqrt(np.mean(np.sum((desired - actual) ** 2, axis=1))) * 1000)
    stops = metrics.stop_windows(times, metrics.moving_mask(times, desired, target.velocities))
    require(bool(stops), f"{path.name} does not measure a stop")
    errors = []
    for start, end in stops:
        tail = (times >= max(start, end - 0.1) - 1e-9) & (times <= end + 1e-9)
        require(tail.any(), f"{path.name} has an incomplete stop")
        errors.append(np.linalg.norm(np.mean(desired[tail] - actual[tail], axis=0)) * 1000)
    gate_definitions, _, _ = gates_v2(kind)
    stock, _ = run_kpis_v2_with_notes(trace, dataset.info)
    failures = [name for name in gate_definitions if not gate_passes(stock, name, gate_definitions)]
    return {"task": task.task_id, "split": task.split, "samples": len(times), "stops": len(stops),
            STOP: float(max(errors)), RMS: rms_mm, "existing_gate_failures": failures, "detector_false_alarm": false_alarm(meta),
            "trace_sha256": digest(path), "controller": meta["controller"], "bench_source": meta["source"]["git_sha"],
            "arm_model_key": meta["source"]["arm_model_key"]}


def corpus(bench, kind, traces, lock):
    dataset, dataset_hash = verify_data(bench, kind)
    required = {task.task_id: task for task in dataset.tasks}
    files = {}
    for path in traces.rglob("*.trace.npz"):
        task = path.name.split("__", 1)[0]
        require(task in required and task not in files, f"unknown or repeated {kind} recording {path.name}")
        files[task] = path
    require(set(files) == set(required), f"{kind} missing {len(required.keys() - files.keys())} frozen runs")
    rows = [measure(files[task_id], dataset, kind, task, lock) for task_id, task in required.items()]
    _, dataset_gates, _ = gates_v2(kind)
    detector = [item["detector_false_alarm"] for item in rows if item["detector_false_alarm"] is not None]
    false_alarm_pct = 100.0 * sum(detector) / len(detector) if detector else None
    return {"dataset_manifest_sha256": dataset_hash, "counts": dict(Counter(row["split"] for row in rows)),
            "worst": {metric: max(rows, key=lambda row: row[metric]) for metric in (STOP, RMS)},
            "existing_gates": {"passes": sum(not row["existing_gate_failures"] for row in rows),
                               "failures": [row for row in rows if row["existing_gate_failures"]],
                               "detector_observed": len(detector), "false_alarm_pct": false_alarm_pct,
                               "false_alarm_pass": gate_passes({"false_alarm_rate_pct": false_alarm_pct},
                                                              "false_alarm_rate_pct", dataset_gates)},
            "trace_digests": {row["task"]: row["trace_sha256"] for row in rows}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bench", "workspace", "conveyor", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--controller-lock", type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.controller_lock.read_text())
    require(lock.get("schema") == "tta.bam-fb-simulation-controller-lock/1" and lock.get("nominal_speed_rung") == 1.0
            and lock.get("holdout_scored_before_this_lock") is False, "provide the pre-holdout controller lock")
    result = {"schema": "tta.bam-fb-qualification/1", "domain": "sim", "rung": 1.0,
              "controller_sha256": lock["controller_sha256"], "controller_lock_sha256": digest(args.controller_lock),
              "corpora": {kind: corpus(args.bench, kind, getattr(args, kind), lock) for kind in CORPORA}}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
