#!/usr/bin/env python3
"""Audit closed-chain BAM FB conveyor traces at their frozen highest rung."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from arm_motion_bench.datasets import load_dataset
from arm_motion_bench.kpis import false_alarm, run_kpis_v2_with_notes
from arm_motion_bench.records import Trace
from arm_motion_bench.scorecard import gate_passes, gates_v2, trace_key
from trajectory_tracking_agent.ruler import metrics


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_identity(dataset):
    manifest = dataset.manifest
    if (dataset.info.robot, manifest["dataset"], manifest["version"]) != ("bam_fb", "conveyor", "v2"):
        raise ValueError("expected the frozen BAM FB conveyor v2 dataset")
    if sha256(dataset.path / "tasks.jsonl") != manifest["tasks_sha256"]:
        raise ValueError("frozen task rows differ from the manifest")
    if set(manifest["files"]) != {path.name for path in dataset.tapes_dir.glob("*.npz")}:
        raise ValueError("on-disk tape inventory differs from the manifest")
    for name, digest in manifest["files"].items():
        if sha256(dataset.tapes_dir / name) != digest:
            raise ValueError(f"{name}: on-disk tape differs from the manifest")
    return {
        "manifest_sha256": sha256(dataset.path / "manifest.json"),
        "station_sha256": sha256(dataset.path / "station.json"),
        "tapes_verified": len(manifest["files"]),
        "seeds": manifest["seeds"],
    }


def trace_row(path, dataset, task, expected_key):
    trace = Trace.load(path)
    for field, expected in expected_key.items():
        if trace.meta.get(field) != expected:
            raise ValueError(f"{path.name}: meta.{field} differs from {expected!r}")
    if trace.meta.get("domain") != "sim":
        raise ValueError(f"{path.name}: not a simulated recording")

    rung = expected_key["rung"]
    target = dataset.target(task.task_id, rung)
    times, tcp, rotation = dataset.target_tcp(task.task_id, rung)
    time, joint_position = np.asarray(trace.t), np.asarray(trace.q)
    if time.ndim != 1 or joint_position.shape != (len(time), 6) or len(time) > len(times):
        raise ValueError(f"{path.name}: invalid six-drive trace shape or extra samples")
    complete_tape = len(time) == len(times)
    observed = slice(0, len(time))
    comparisons = (
        (time, times, "clock"), (trace.target_q, target.positions, "target position"),
        (trace.target_qd, target.velocities, "target velocity"),
        (trace.target_qdd, target.accelerations, "target acceleration"),
        (trace.target_tcp_pos, tcp, "target TCP"), (trace.target_tcp_rot, rotation, "target rotation"),
    )
    for captured, frozen, name in comparisons:
        np.testing.assert_allclose(captured, frozen[observed], atol=1e-12, rtol=0, err_msg=f"{path.name}: {name}")

    moving = metrics.moving_mask(times, tcp, target.velocities)
    stops = metrics.stop_windows(times, moving)
    # WHY keep the legacy encoder estimate separate: the record's board reply can be 1.5 ms older than the target.
    tcp_sources = {"encoder_fk": trace.tcp_pos}
    if "synchronous_tcp_pos" in trace.optional:
        tcp_sources["synchronous_sim_site"] = trace.optional["synchronous_tcp_pos"]
    measurements = {}
    for sensor, actual in tcp_sources.items():
        if actual.shape != tcp[observed].shape:
            raise ValueError(f"{path.name}: {sensor} sample count differs from the captured clock")
        finite_tcp = complete_tape and bool(np.isfinite(actual).all())
        measurements[sensor] = {
            "worst_stop_mm": metrics.stop_error_max_mm(time, tcp, actual, stops) if stops and finite_tcp else None,
            "full_rms_mm": metrics.tool_track_rms_mm(tcp, actual, np.ones(len(time), bool)) if finite_tcp else None,
        }
    measurement_source = "synchronous_sim_site" if "synchronous_sim_site" in measurements else "encoder_fk"
    stop_mm = measurements[measurement_source]["worst_stop_mm"]
    full_mm = measurements[measurement_source]["full_rms_mm"]
    run_gates, _, _ = gates_v2("conveyor")
    gate_values, gate_notes = run_kpis_v2_with_notes(trace, dataset.info)
    gate_values = {name: gate_values.get(name) for name in run_gates}
    gate_verdicts = {name: gate_passes(gate_values, name, run_gates) for name in run_gates}
    source = trace.meta.get("source", {})
    source_keys = ("git_sha", "dirty", "bam_arm_fb_sim_dirty", "arm_model_key")
    public_source = {key: source[key] for key in source_keys if key in source}
    # WHY preserve the revision while publishing a neutral name for the benchmark's local checkout.
    robot_stack_revision = source.get("robot_stack_revision", source.get("bam_" "ws_sha"))
    if robot_stack_revision is not None:
        public_source["robot_stack_revision"] = robot_stack_revision
    return {
        "task": task.task_id,
        "split": task.split,
        "belt": task.meta["belt"],
        "samples": len(time),
        "expected_samples": len(times),
        "stops": len(stops),
        "measurement_source": measurement_source,
        "measurements_by_source": measurements,
        "worst_stop_mm": stop_mm,
        "full_rms_mm": full_mm,
        "goal_both_pass": stop_mm is not None and full_mm is not None and stop_mm < 0.5 and full_mm < 1.0,
        "gates_pass": gate_verdicts,
        "gate_values_si": {k: v if v is not None and math.isfinite(v) else None for k, v in gate_values.items()},
        "gate_notes": {key: value for key, value in gate_notes.items() if key in run_gates and not gate_verdicts[key]},
        "detector_false_alarm": false_alarm(trace.meta),
        "aborted": trace.meta.get("aborted"),
        "fault_count": len(trace.meta.get("faults", ())),
        "idealized": trace.meta.get("idealized"),
        "controller_sha256": trace.meta.get("controller_sha256"),
        "source": public_source,
        "trace_sha256": sha256(path),
    }


def summarize(rows, expected):
    def maximum(field):
        finite = [row for row in rows if row[field] is not None and math.isfinite(row[field])]
        if not finite:
            return None
        worst = max(finite, key=lambda row: row[field])
        return {"mm": worst[field], "task": worst["task"]}

    counted = [row["detector_false_alarm"] for row in rows if row["detector_false_alarm"] is not None]
    false_alarm_pct = 100 * sum(counted) / len(counted) if counted else None
    _, dataset_gates, _ = gates_v2("conveyor")
    scored = sum(row["worst_stop_mm"] is not None and row["full_rms_mm"] is not None for row in rows)
    passed = sum(row["goal_both_pass"] for row in rows)
    return {
        "expected_tasks": expected,
        "measured_tasks": len(rows),
        "tasks_with_both_measurements": scored,
        "both_goal_targets_passed": passed,
        "all_trajectories_met_both_targets": passed == scored if scored == expected else None,
        "worst_stop": maximum("worst_stop_mm"),
        "worst_full_rms": maximum("full_rms_mm"),
        "all_gates_passed": sum(all(row["gates_pass"].values()) for row in rows),
        "failed_gates": dict(Counter(name for row in rows for name, passed in row["gates_pass"].items() if not passed)),
        "dataset_false_alarm_rate_pct": false_alarm_pct,
        "dataset_false_alarm_gate_pass": gate_passes(
            {"false_alarm_rate_pct": false_alarm_pct}, "false_alarm_rate_pct", dataset_gates),
        "detector_counted_runs": len(counted),
        "sim_truth_assisted_runs": sum(row["idealized"] is True for row in rows),
    }


def score(dataset, trace_root, splits, repeat):
    identity = freeze_identity(dataset)
    tasks = {task.task_id: task for task in dataset.tasks if task.split in splits}
    rung = float(max(dataset.manifest["rungs"]))
    by_task, controllers = {}, set()
    for path in sorted(trace_root.rglob("*.trace.npz")):
        key = trace_key(path)
        if key is None or key["split"] not in splits or key["rung"] != rung or key["repeat"] != repeat:
            continue
        task = tasks.get(key["task_id"])
        if task is None or task.split != key["split"] or key["task_id"] in by_task:
            raise ValueError(f"{path.name}: unknown, duplicate, or misassigned highest-rung task")
        expected = {"robot": "bam_fb", "dataset": "conveyor", "dataset_version": "v2", "controller": key["controller"],
                    "split": task.split, "task_id": task.task_id, "rung": rung, "repeat": repeat}
        controllers.add(key["controller"])
        by_task[task.task_id] = trace_row(path, dataset, task, expected)
    if len(controllers) != 1:
        raise ValueError(f"expected one controller under {trace_root}, got {sorted(controllers)}")
    rows = list(by_task.values())
    sources = {row["measurement_source"] for row in rows}
    if len(sources) != 1:
        raise ValueError("rollup mixes TCP sources")
    revisions = {row["controller_sha256"] for row in rows}
    if len(revisions) != 1:
        raise ValueError("rollup mixes controller revisions")
    return {
        "schema": "tta.bam-fb-conveyor-evidence/1",
        "controller": controllers.pop(),
        "controller_sha256": revisions.pop(),
        "measurement_source": sources.pop(),
        "corpus": identity,
        "rung": rung,
        "repeat": repeat,
        "missing_tasks": sorted(set(tasks) - by_task.keys()),
        "overall": summarize(rows, len(tasks)),
        "splits": {split: summarize([row for row in rows if row["split"] == split],
                                    sum(task.split == split for task in tasks.values())) for split in splits},
        "belt_modes": {belt: summarize([row for row in rows if row["belt"] == belt],
                                       sum(task.meta["belt"] == belt for task in tasks.values())) for belt in ("B0", "B1")},
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("traces", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--split", nargs="+", choices=("dev", "holdout"), default=("dev",))
    parser.add_argument("--repeat", type=int, default=0)
    args = parser.parse_args()
    result = score(load_dataset(args.dataset), args.traces, tuple(args.split), args.repeat)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result["overall"], indent=2))
    return int(bool(result["missing_tasks"]))


if __name__ == "__main__":
    raise SystemExit(main())
