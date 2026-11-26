"""Replay a frozen conveyor cycle in the stock portal station with the current ranked controller."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from functools import partial
from pathlib import Path

import mujoco
import numpy as np
from arm_motion_bench.robots.ur5e import JOINT_NAMES, mujoco_spec, station
from robot_controllers.bench.loop import run_episode
from robot_controllers.bench.ur5e import Ur5ePlant
from robot_msgs import load_npz

from trajectory_tracking_agent import population
from trajectory_tracking_agent.evaluate import SETTLE_BAND_MM, SETTLE_WINDOW_S, TIME_BOX_FACTOR, _SolutionSpec, _rung
from trajectory_tracking_agent.ruler import gates, metrics
from trajectory_tracking_agent.ruler.dataset import Task
from trajectory_tracking_agent.ruler.deployment import deployment

CONTROLLER = "p5s-damping185-refit"
REPO = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    pending = path.with_suffix(".tmp.json")
    pending.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    pending.replace(path)


def frozen_manifest(dataset):
    manifest = json.loads((dataset / "manifest.json").read_text())
    if manifest["schema"] != "arm_motion_bench.conveyor-cycle/1" or manifest["scene"]["id"] != "ur5e-portal-pep0032":
        raise ValueError("expected a frozen PEP 0032 conveyor cycle")
    if manifest["scene"]["moving_belt"] or manifest["scene"]["payload"]:
        raise ValueError("this replay requires the static, unloaded portal fixture")
    payloads = manifest["files"]
    for name, checksum in payloads.items():
        path = (dataset / name).resolve()
        if not path.is_relative_to(dataset.resolve()) or digest(path) != checksum:
            raise ValueError(f"dataset payload differs from its manifest: {name}")
    for tape in manifest["tapes"]:
        if tape["path"] not in payloads or tape["sha256"] != payloads[tape["path"]]:
            raise ValueError(f"tape checksum is missing or inconsistent: {tape['path']}")
    if sorted(row["speed_fraction"] for row in manifest["tapes"]) != manifest["speeds"]:
        raise ValueError("speed list and tape list disagree")
    return manifest


def portal_model(portal, payload_kg, truth):
    if payload_kg != 0:
        raise ValueError("this trial freezes the unloaded arm and the geometry-only claw stand-in")
    spec = mujoco_spec(portal)
    spec.option.timestep = truth.physics_dt_s
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    # The stock controller plant logs its tool site by name. Use the dataset station's exact TCP in the cell frame.
    spec.site("tcp").name = "tool"
    model = spec.compile()
    model.dof_armature[:] = truth.armature_kg_m2
    model.dof_frictionloss[:] = truth.frictionloss_nm
    model.dof_damping[:] = truth.damping_nm_s_rad
    # MuJoCo position actuators remain at zero input by default, which would fight the simulated board torques.
    model.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_ACTUATION
    return model


def scene_clearance(portal, times, joints):
    violations = 0
    first = None
    for timestamp, row in zip(times, joints, strict=True):
        if not np.isfinite(row).all():
            violations += 1
            if first is None:
                first = {"time_s": float(timestamp), "pairs": ["non-finite joint state"]}
            continue
        hits = portal.collisions(row)
        if hits:
            violations += 1
            if first is None:
                first = {"time_s": float(timestamp), "pairs": hits}
    return violations, first


def score(portal, dep, tape, log, elapsed_s, wall_limit_s):
    times = np.asarray(tape.t)
    indices = np.rint(times * dep.board.rate_hz).astype(int)
    if indices[-1] >= len(log.t) or not np.allclose(log.t[indices], times, rtol=0, atol=1e-9):
        raise ValueError("physics samples do not cover every frozen tape timestamp")
    end = indices[-1] + 1
    target_poses = portal.base_in_cell @ portal.fk_many(tape.positions)
    actual_poses = portal.base_in_cell @ portal.fk_many(log.q[indices])
    target_tcp = target_poses[:, :3, 3]
    actual_tcp = log.tool_pos[indices]
    np.testing.assert_allclose(actual_poses[:, :3, 3], actual_tcp, atol=1e-9, rtol=0)
    moving = metrics.moving_mask(times, target_tcp, tape.velocities)
    stops = metrics.stop_windows(times, moving)
    settle = times >= times[-1] - SETTLE_WINDOW_S - 1e-9
    settle_max = 1000.0 * float(np.max(metrics.tool_errors_m(target_tcp[settle], actual_tcp[settle])))
    notes = [event for event in log.events if event["kind"] in {"abort", "diverged"}]
    clearance_hits, first_hit = scene_clearance(portal, log.t[:end], log.q[:end])
    kpis = {
        "completed": not notes and elapsed_s <= wall_limit_s and settle_max <= SETTLE_BAND_MM,
        "stop_error_max_mm": metrics.stop_error_max_mm(times, target_tcp, actual_tcp, stops),
        "saturation_share_pct": metrics.saturation_share_pct(log.tau[:end], dep.torque_cap_nm),
        "limit_violations": metrics.limit_violations(log.q[:end], log.qd[:end], dep.position_min_rad,
                                                      dep.position_max_rad, dep.velocity_max_rad_s),
    }
    # The stock floor gate refers to the old upright bench origin. Independently use the cell's distance oracle here.
    verdicts = gates.gate_verdicts({**kpis, "floor_clearance_violations": None})
    del verdicts["floor_clearance"]
    verdicts["scene_clearance"] = clearance_hits == 0
    rms = metrics.tool_track_rms_mm(target_tcp, actual_tcp, moving)
    result = {
        "tracking_rms_mm": rms, "kpis": kpis, "verdicts": verdicts, "settle_max_mm": settle_max,
        "moving_samples": int(np.count_nonzero(moving)), "physics_samples": int(end),
        "max_error_mm": metrics.tool_track_max_mm(target_tcp, actual_tcp, moving),
        "scene_clearance_violating_samples": clearance_hits, "first_scene_violation": first_hit,
        "events": notes, "watchdog_events": sum(event["kind"] == "watchdog" for event in log.events),
    }
    for name in ("stop_error_max_mm", "saturation_share_pct"):
        if not math.isfinite(kpis[name]):
            kpis[name] = None
    for name in ("tracking_rms_mm", "settle_max_mm", "max_error_mm"):
        if not math.isfinite(result[name]):
            result[name] = None
    return result, {"t": times, "joint_names": np.asarray(tape.joint_names), "target_q": tape.positions,
                    "target_qd": tape.velocities, "target_qdd": tape.accelerations, "target_poses": target_poses,
                    "actual_q": log.q[indices], "actual_qd": log.qd[indices], "actual_poses": actual_poses,
                    "actual_torque": log.tau[indices], "moving": moving}


def run_one(dataset, tape_row, controller, target):
    tape = load_npz(dataset / tape_row["path"])
    if tuple(tape.joint_names) != JOINT_NAMES or len(tape.t) != tape_row["samples"]:
        raise ValueError("the tape differs from the frozen joint order or sample count")
    if not np.array_equal(tape.positions[0], tape.positions[-1]):
        raise ValueError("the conveyor cycle must end at the starting joint pose")
    portal = station(mount="portal")
    dep = deployment()
    fraction = tape_row["speed_fraction"]
    task = Task(f"conveyor-cycle-{round(fraction * 10):02}", "dev", "conveyor-cycle", 0, tape)
    started = time.monotonic()
    wall_limit = TIME_BOX_FACTOR * float(tape.t[-1])
    spec = _SolutionSpec(CONTROLLER, controller, dep, started + wall_limit, wall_limit)
    log = run_episode(spec, _rung(task, dep), seed=0,
                      plant_factory=lambda: Ur5ePlant(board_config=dep.board, model_factory=partial(portal_model, portal)))
    result, signals = score(portal, dep, tape, log, time.monotonic() - started, wall_limit)
    np.savez_compressed(target / f"{task.id}.npz", **signals)
    result.update(speed_fraction=fraction, duration_s=task.duration_s, source_tape_sha256=tape_row["sha256"],
                  recording=f"{task.id}.npz")
    print(f"{fraction:.1f}: {result['tracking_rms_mm']} mm RMS, {result['verdicts']}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fractions", nargs="+", type=float)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    manifest = frozen_manifest(dataset)
    fractions = args.fractions or sorted(manifest["speeds"], reverse=True)
    if len(set(fractions)) != len(fractions) or not set(fractions) <= set(manifest["speeds"]):
        parser.error("choose unique fractions present in the dataset manifest")
    args.out.mkdir(parents=True, exist_ok=True)
    controller = population.load_build(CONTROLLER)
    result = {"schema": "tta.conveyor-cycle-baseline/1", "dataset_manifest_sha256": digest(dataset / "manifest.json"),
              "controller": CONTROLLER, "controller_sha256": population.solution_sha256(CONTROLLER),
              "scene": manifest["scene"], "picks": manifest["accepted"], "requested_fractions": fractions,
              "ruler_scope": "off-score simulated transfer with unchanged upright calibration and a portal scene clearance check",
              "mujoco": mujoco.__version__,
              "runner_commit": subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip(),
              "runs": []}
    summary = args.out / "baseline.json"
    write_json(summary, result)
    rows = {row["speed_fraction"]: row for row in manifest["tapes"]}
    for fraction in fractions:
        result["runs"].append(run_one(dataset, rows[fraction], controller, args.out))
        write_json(summary, result)


if __name__ == "__main__":
    main()
