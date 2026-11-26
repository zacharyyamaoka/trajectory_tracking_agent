"""Measure the UR5e's time-scaled dev tapes off the ranked ruler ledger."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
from robot_controllers.bench.loop import run_episode

from trajectory_tracking_agent import population
from trajectory_tracking_agent.evaluate import MAX_WORKERS, TIME_BOX_FACTOR, _failed_row, _rung, _score, _SolutionSpec
from trajectory_tracking_agent.ruler.dataset import tasks
from trajectory_tracking_agent.ruler.deployment import deployment

CONTROLLERS = ("p6s", "p5s-fric2-pass2", "p5s-kp2-pass2", "p5s-pass3", "p5s-damping185-refit")
FRACTIONS = tuple(step / 10 for step in range(1, 11))
SCORE_SAMPLE_RATE_HZ = 100


def time_scaled_tape(trajectory, fraction):
    if fraction == 1.0:
        return trajectory
    scaled = trajectory.time_scaled(1.0 / fraction)
    sample_count = math.ceil(scaled.t[-1] * SCORE_SAMPLE_RATE_HZ - 1e-9)
    sample_times = np.arange(sample_count + 1) / SCORE_SAMPLE_RATE_HZ
    # WHY resample after scaling: arbitrary fractions need not preserve the physics sample grid. A terminal hold
    # of less than one 100 Hz sample lets every scored sample land on the original 4 kHz physics grid.
    return scaled.resample(sample_times, extrapolate="clamp")


def speed_dwell(t, velocities, limits):
    """Time in seconds at rest, in (0,0.1]…(0.9,1], and above the joint speed limit."""
    utilization = np.max(np.abs(velocities[:-1]) / limits, axis=1)
    bins = np.clip(np.ceil(utilization * 10 - 1e-9).astype(int), 0, 11)
    return np.bincount(bins, weights=np.diff(t), minlength=12).tolist()


def score(arguments):
    solution, fraction, task_index = arguments
    task = tasks("dev")[task_index]
    dep = deployment("ur5e_alone")
    tape = time_scaled_tape(task.trajectory, fraction)
    case = replace(task, trajectory=tape)
    limit = TIME_BOX_FACTOR * float(tape.t[-1])
    started = time.perf_counter()
    spec = _SolutionSpec(solution, population.load_build(solution), dep, started + limit, limit)
    try:
        log = run_episode(spec, _rung(case, dep), seed=0, plant_factory=dep.plant)
    except Exception as error:
        row = _failed_row(case, spec.failure or f"{type(error).__name__}: {error}")
    else:
        row = _score(case, dep, log, spec, time.perf_counter() - started, limit)

    limits = np.asarray(dep.velocity_max_rad_s)
    target = np.asarray(tape.velocities)
    measured = row.get("_arrays", {}).get("qd")
    finite_velocity = measured is not None and np.isfinite(measured).all()
    return {
        "solution": solution, "target": task.id, "kind": task.kind, "fraction": fraction,
        "tool_track_rms_mm": row["objective"], "gates": row["verdicts"],
        "stop_error_max_mm": row["kpis"]["stop_error_max_mm"],
        "saturation_share_pct": row["kpis"]["saturation_share_pct"],
        "duration_s": float(tape.t[-1]), "target_dwell_s": speed_dwell(tape.t, target, limits),
        "measured_dwell_s": speed_dwell(tape.t, measured, limits) if finite_velocity else None,
        "target_peak_deg_s": np.rad2deg(np.max(np.abs(target), axis=0)).tolist(),
        "measured_peak_deg_s": np.rad2deg(np.max(np.abs(measured), axis=0)).tolist() if finite_velocity else None,
        "notes": row["notes"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--solutions", nargs="+", default=CONTROLLERS)
    parser.add_argument("--fractions", type=float, nargs="+", default=FRACTIONS)
    parser.add_argument("--tasks", nargs="+", help="dev task IDs for a reduced verification run")
    args = parser.parse_args()
    if args.workers < 1 or len(args.fractions) != len(set(args.fractions)) or any(f not in FRACTIONS for f in args.fractions):
        parser.error("choose positive workers and unique fractions on the 0.1–1.0 grid")

    all_tasks = tasks("dev")
    indices = [index for index, task in enumerate(all_tasks) if args.tasks is None or task.id in args.tasks]
    if not indices or (args.tasks is not None and len(indices) != len(set(args.tasks))):
        parser.error("task IDs must be in the frozen dev split")
    for name in args.solutions:
        population.meta(name)

    dep = deployment("ur5e_alone")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    progress = args.output.with_suffix(".jsonl")
    jobs = [(name, fraction, index) for fraction in args.fractions for name in args.solutions for index in indices]
    counts = Counter()
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool, progress.open("w") as stream:
        for row in pool.map(score, jobs):
            rows.append(row)
            stream.write(json.dumps(row, allow_nan=False) + "\n")
            stream.flush()
            key = (row["solution"], row["fraction"])
            counts[key] += 1
            if counts[key] == len(indices):
                print(f"{key[0]} at {key[1]:.1f}: {counts[key]} tasks | {len(rows)}/{len(jobs)} simulations", flush=True)
    result = {
        "schema": "tta.ur5e-speed-study/1", "dataset": "ur5e_alone/workspace/v2", "split": "dev",
        "scope": "off-score UR5e simulation", "fractions": list(args.fractions), "controllers": list(args.solutions),
        "joint_names": list(dep.joint_names), "configured_velocity_max_deg_s": np.rad2deg(dep.velocity_max_rad_s).tolist(),
        "tasks": [all_tasks[index].id for index in indices], "runs": rows,
    }
    temporary = args.output.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n")
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
