"""Score the frozen CAN 11 workspace on the stock MuJoCo pendulum."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from arm_motion_bench.datasets import REPO_ROOT, load_dataset, rung_tape_name
from arm_motion_bench.robots.pendulum import station
from robot_controllers.bench.loop import run_episode
from robot_controllers.bench.population import config, config_spec
from robot_controllers.bench.scenarios import base_scenario
from robot_controllers.bench.types import HostTiming, Rung, Scene
from robot_controllers.registry import JOINT_TRAJECTORY

from trajectory_tracking_agent.evaluate import _controller_trajectory
from trajectory_tracking_agent.ruler import metrics

DATASET = REPO_ROOT / "datasets" / "pendulum" / "workspace" / "v2"
DATASET_SHA = "461445be5e01ae95ff0e1623059bc21d4f2ed446581e7557470e6bca856ec85f"
RUNG = 1.0
SPLIT_COUNTS = {"dev": 40, "holdout": 12}
STOP_TARGET_MM = 0.5
RMS_TARGET_MM = 1.0


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inputs(path):
    require(digest(path / "manifest.json") == DATASET_SHA, "expected the frozen CAN 11 workspace v2 manifest")
    dataset = load_dataset(path)
    require(digest(path / "tasks.jsonl") == dataset.manifest["tasks_sha256"], "task records differ from the manifest")
    require(dataset.info == station().info, "dataset station differs from the CAN 11 bench station")
    require(max(dataset.manifest["rungs"]) == RUNG, "the top nominal rung changed")
    require(len({task.task_id for task in dataset.tasks}) == len(dataset.tasks), "duplicate target IDs")
    for split, count in SPLIT_COUNTS.items():
        require(len(dataset.tasks_in(split)) == count, f"incomplete {split} split")
    return dataset


def frozen_target(dataset, task):
    filename = rung_tape_name(task.task_id, RUNG)
    require(digest(dataset.tapes_dir / filename) == dataset.manifest["files"][filename], f"{task.task_id}: tape hash mismatch")
    target = dataset.target(task.task_id, RUNG)
    clock = np.arange(len(target.t)) / dataset.info.rate_hz
    require(tuple(target.joint_names) == ("can11",) and np.allclose(clock, target.t, atol=1e-12, rtol=0),
            f"{task.task_id}: unexpected target clock or joints")
    limits = station().limits()
    q, qd, qdd = map(np.asarray, (target.positions, target.velocities, target.accelerations))
    require(np.isfinite(q).all() and np.isfinite(qd).all() and np.isfinite(qdd).all(), f"{task.task_id}: non-finite target")
    require(np.all(q >= limits.min_position - 1e-9) and np.all(q <= limits.max_position + 1e-9)
            and np.all(np.abs(qd) <= limits.max_velocity + 1e-9) and np.all(np.abs(qdd) <= limits.max_acceleration + 1e-9),
            f"{task.task_id}: exceeds the canonical planning envelope")
    return filename, target


def score(target, log, joint):
    indices = np.searchsorted(log.t, target.t - 1e-10)
    require(bool(np.all(indices < len(log.t))) and np.allclose(log.t[indices], target.t, atol=1e-10, rtol=0),
            "physics recording does not cover the complete target clock")
    q, qd, tau = log.q[indices], log.qd[indices], log.tau[indices]
    desired = station().fk_many(target.positions)
    measured = station().fk_many(q)
    np.testing.assert_allclose(log.tool_pos[indices], measured[:, :3, 3], atol=1e-12, rtol=0)
    reference_xyz, measured_xyz = desired[:, :3, 3], measured[:, :3, 3]
    moving = metrics.moving_mask(target.t, reference_xyz, target.velocities)
    stops = metrics.stop_windows(target.t, moving)
    require(bool(stops), "no scored stops on the complete recording")
    rms = metrics.tool_track_rms_mm(reference_xyz, measured_xyz, np.ones(len(target.t), dtype=bool))
    worst_stop = metrics.stop_error_max_mm(target.t, reference_xyz, measured_xyz, stops)
    require(math.isfinite(rms) and math.isfinite(worst_stop), "tracking measurements are not finite")
    # WHY compare a separate angular oracle: for a rigid tip, the 3D tracking distance is the chord, not arc length.
    radius = np.linalg.norm(reference_xyz[0])
    chord = 2 * radius * np.sin(0.5 * (q[:, 0] - target.positions[:, 0]))
    np.testing.assert_allclose(rms, 1000 * np.sqrt(np.mean(chord * chord)), atol=1e-10, rtol=0)
    clip = slice(None, int(indices[-1]) + 1)
    events = [item for item in log.events if item["kind"] in {"abort", "diverged", "watchdog"}
              and item.get("t", 0.0) <= target.t[-1] + 1e-10]
    saturation = metrics.saturation_share_pct(log.tau[clip], (joint.torque_cap_nm,))
    violations = metrics.limit_violations(log.q[clip], log.qd[clip], (joint.position_min_rad,), (joint.position_max_rad,),
                                          (joint.velocity_max_rad_s,))
    row = {"full_trajectory_rms_mm": rms, "stop_error_max_mm": worst_stop, "stops": len(stops), "samples": len(target.t),
           "saturation_share_pct": saturation, "limit_violations": violations, "events": events,
           "checks": {"completed": not events, "stop_error_max_mm": worst_stop <= 1.0,
                      "saturation_share_pct": saturation <= 2.0, "limit_violations": violations == 0}}
    arrays = {"t": target.t, "target_q": target.positions, "target_qd": target.velocities, "target_qdd": target.accelerations,
              "measured_q": q, "measured_qd": qd, "measured_tau": tau, "target_pose": desired, "measured_pose": measured}
    return row, arrays


def launch(dataset, task, scenario, spec):
    filename, target = frozen_target(dataset, task)
    safe_target = _controller_trajectory(target)
    timing = HostTiming.from_bus(scenario.bus, scenario.host_rate_hz, include_compute=False)
    rung = Rung(id=task.task_id, title=task.task_id, box=JOINT_TRAJECTORY, family="free_space",
                description="CAN 11 frozen workspace v2 tape at its top rung.", duration_s=float(target.t[-1]) + timing.period_s,
                inputs=lambda _start: [(0.0, safe_target)], scene=Scene(start_q=(float(target.positions[0, 0]),)),
                timing=timing, plant="pendulum")
    log = run_episode(spec, rung, plant_factory=scenario.plant_factory())
    result, arrays = score(target, log, dataset.info.joints[0])
    return {"target": task.task_id, "split": task.split, "top_rung": RUNG,
            "tape_sha256": dataset.manifest["files"][filename], **result}, arrays


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--split", choices=tuple(SPLIT_COUNTS), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    dataset = inputs(args.dataset)
    scenario = replace(base_scenario("pendulum"), host_rate_hz=dataset.info.rate_hz)
    spec = config_spec("P3s", scenario)
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    for task in dataset.tasks_in(args.split):
        row, arrays = launch(dataset, task, scenario, spec)
        recording = args.out / f"{task.task_id}.npz"
        np.savez_compressed(recording, **arrays)
        rows.append({**row, "recording": recording.name, "recording_sha256": digest(recording)})
    result = {"schema": "tta.pendulum-workspace/1", "domain": "sim", "deployment": "rack_shoulder_pendulum",
              "dataset_manifest_sha256": DATASET_SHA, "top_rung": RUNG, "split": args.split,
              "controller": asdict(config("P3s")), "scenario": asdict(scenario), "runs": rows,
              "worst_stop": max(rows, key=lambda row: row["stop_error_max_mm"]),
              "worst_rms": max(rows, key=lambda row: row["full_trajectory_rms_mm"])}
    (args.out / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"{args.split}: {len(rows)} runs, worst stop {result['worst_stop']['stop_error_max_mm']:.6f} mm, "
          f"worst RMS {result['worst_rms']['full_trajectory_rms_mm']:.6f} mm")


if __name__ == "__main__":
    main()
