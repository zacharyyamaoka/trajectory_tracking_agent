"""Rescore archived real servo traces against the frozen top-rung tapes, without hardware access."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from arm_motion_bench.datasets import load_dataset

from trajectory_tracking_agent.ruler import metrics

CORPORA = (("bam_fb", "workspace"), ("bam_fb", "conveyor"), ("pendulum", "workspace"))
STOP = "stop_error_max_mm"
RMS = "full_trajectory_rms_mm"


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def score_archive(trace_path, dataset, robot, kind):
    with np.load(trace_path) as data:
        meta = json.loads(str(data["meta"]))
        declared = Path(meta.get("dataset", ""))
        identity = (meta.get("domain"), meta.get("robot"), meta.get("dataset_version"))
        if identity != ("real", robot, "v2") or (str(declared) != kind and declared.resolve() != dataset.path):
            raise ValueError("recorded device, dataset version or physical source identity differs")
        task = dataset.task(meta["task_id"])
        if meta.get("split") != task.split or meta.get("rung") != max(task.rungs):
            return None
        target = dataset.target(task.task_id, rung=max(task.rungs))
        frozen_time, frozen_xyz, _ = dataset.target_tcp(task.task_id, rung=max(task.rungs))
        rows = len(target.t)
        expected = {"t": frozen_time, "target_q": target.positions, "target_qd": target.velocities,
                    "target_qdd": target.accelerations, "target_tcp_pos": frozen_xyz}
        for name, frozen in expected.items():
            captured = data[name][:rows]
            if captured.shape != frozen.shape or not np.allclose(captured, frozen, atol=1e-9, rtol=0):
                raise ValueError(f"recorded {name} differs from the full frozen tape")
        measured = data["tcp_pos"][:rows]
        if measured.shape != frozen_xyz.shape or not np.isfinite(measured).all():
            raise ValueError("the measured trace is missing or nonfinite")
    stops = metrics.stop_windows(frozen_time, metrics.moving_mask(frozen_time, frozen_xyz, target.velocities))
    if not stops:
        raise ValueError("the recording has no measurable stop")
    stop = metrics.stop_error_max_mm(frozen_time, frozen_xyz, measured, stops)
    rms = metrics.tool_track_rms_mm(frozen_xyz, measured, np.ones(rows, dtype=bool))
    if not all(math.isfinite(value) for value in (stop, rms)):
        raise ValueError("the two scores need finite physical samples")
    real = meta.get("real", {})
    source_path = real.get("run") or meta.get("source", {}).get("run")
    return {"task": task.task_id, "split": task.split, "rung": max(task.rungs), "repeat": meta.get("repeat"),
            "trace": trace_path.name, "trace_sha256": file_sha256(trace_path), "samples": rows,
            "raw_source": bool(source_path and Path(source_path).exists()), "stops": len(stops),
            "aborted": bool(meta.get("aborted")), "faults": bool(meta.get("faults")),
            "missing_plan_ticks": real.get("missing_ticks"), STOP: stop, RMS: rms}


def audit(bench_root, trace_root):
    corpora = {}
    for robot, kind in CORPORA:
        dataset = load_dataset(bench_root / "datasets" / robot / kind / "v2")
        corpus = {"device": robot, "kind": kind, "target_count": len(dataset.tasks),
                  "dataset_manifest_sha256": file_sha256(dataset.path / "manifest.json"), "controllers": {}}
        corpora[f"{robot}/{kind}/v2"] = corpus
        for source in sorted((trace_root / robot).glob(f"*/{kind}-v2")):
            rows, rejected = [], []
            for trace_path in sorted(source.rglob("*.trace.npz")):
                try:
                    item = score_archive(trace_path, dataset, robot, kind)
                except (ValueError, KeyError, OSError) as error:
                    rejected.append({"trace": trace_path.name, "reason": str(error).splitlines()[0] or type(error).__name__})
                    continue
                if item is not None:
                    rows.append(item)
            if not rows and not rejected:
                continue
            counted = Counter(row["task"] for row in rows)
            corpus["controllers"][source.parent.name] = {
                "matched_traces": len(rows), "unique_targets": len(counted), "repeat_counts": dict(Counter(counted.values())),
                "matched_traces_with_raw_source": sum(row["raw_source"] for row in rows),
                "matched_traces_with_missing_plan_ticks": sum((row["missing_plan_ticks"] or 0) > 0 for row in rows),
                "rejected": rejected, "worst": {metric: max(rows, key=lambda row: row[metric]) for metric in (STOP, RMS)} if rows else {},
            }
    return {"schema": "tta.physical-archive-audit/1", "measurement": "paired encoder FK on the nominal plan clock",
            "qualification": "diagnostic archive scores only. Load-side tool position and reply clock were not measured in these traces.",
            "corpora": corpora}


def legacy_fivebar(trace_path, raw_run):
    """Score the historical hardware trajectory on its recorded command clock for diagnosis."""
    with np.load(trace_path) as trace:
        meta = json.loads(str(trace["meta"]))
        if meta.get("domain") != "real" or meta.get("robot") != "bam_fb" or meta.get("rung") != 1.0:
            raise ValueError("the legacy trace is not a top-rung BAM FB hardware acquisition")
        report_path = raw_run / "report.json"
        raw = json.loads(report_path.read_text())
        if raw["run_id"] != meta["source"]["run_id"] or raw["result"] != "complete":
            raise ValueError("the recorded trace has no matching completed raw acquisition")
        times, desired, actual = (trace[key] for key in ("t", "target_tcp_pos", "tcp_pos"))
        spans = [(float(times[first]), float(times[end - 1])) for first, end in trace["stops"]]
        if not spans or not np.isfinite(actual).all():
            raise ValueError("the legacy trace is incomplete")
        rms = metrics.tool_track_rms_mm(desired, actual, np.ones(len(times), dtype=bool))
        stop = metrics.stop_error_max_mm(times, desired, actual, spans)
    return {"task": meta["task_id"], "run_id": raw["run_id"], "date": raw["utc"], "command_clock": True,
            "trace_sha256": file_sha256(trace_path), "report_sha256": file_sha256(report_path),
            "planned_raw_bundle_samples": raw["plan"]["samples"], "planned_raw_bundle_sha256": raw["plan"]["samples_sha256"],
            "workspace_exchanges": len(times), "workspace_median_exchange_ms": float(np.median(np.diff(times)) * 1000),
            "workspace_late_ticks": meta["late_ticks"], "overspeed_events": len(raw.get("speed_events", [])),
            "stops": len(spans), STOP: stop, RMS: rms, "full_frozen_corpus_evidence": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bench_root", type=Path)
    parser.add_argument("--trace-root", type=Path, default=None)
    parser.add_argument("--legacy-bam", type=Path, nargs=2, metavar=("TRACE", "RAW_RUN"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = audit(args.bench_root, args.trace_root or args.bench_root / "outputs" / "runs_real")
    if args.legacy_bam:
        results["legacy_bam_workspace_run"] = legacy_fivebar(*args.legacy_bam)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
