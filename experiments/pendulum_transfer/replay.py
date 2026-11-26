"""Compare the adopted CAN 11 MuJoCo twin with archived development encoder traces."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import mujoco
import numpy as np
from arm_motion_bench.baselines import pendulum_sim
from arm_motion_bench.datasets import load_dataset, rung_tape_name
from arm_motion_bench.robots.pendulum import TIP_LENGTH_M, tip_poses
from bam_rack_twin import pendulum_twin

from trajectory_tracking_agent.ruler import metrics

STATION = "can11"
VERSION = "can11-r18a"
DATASET_SHA = "461445be5e01ae95ff0e1623059bc21d4f2ed446581e7557470e6bca856ec85f"
MODEL_SHA = "a67a88b53838093c0176374feb64ca5026738d04c0a1630ffc12a629d93f8192"
CONTROLLER = "ff_model"
RUNG = 1.0
REPEATS = 3
TARGET_TOLERANCE_RAD = 2e-6  # The stock rack plan rounds each position and origin to 1 µrad.


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_tapes(dataset):
    if digest(dataset.path / "manifest.json") != DATASET_SHA:
        raise ValueError("expected the frozen CAN 11 workspace v2 manifest")
    tasks = dataset.tasks_in("dev")
    if len(tasks) != 40 or len({task.task_id for task in tasks}) != 40:
        raise ValueError("the 40 development targets are required exactly once")
    tapes = {}
    for task in tasks:
        filename = rung_tape_name(task.task_id, RUNG)
        if digest(dataset.tapes_dir / filename) != dataset.manifest["files"][filename]:
            raise ValueError(f"{task.task_id}: archived tape differs from the frozen manifest")
        tapes[task.task_id] = dataset.target(task.task_id, rung=RUNG)
    return tapes


def matched_target(task, commanded, tape):
    np.testing.assert_allclose(commanded, tape.positions[:, 0], rtol=0, atol=TARGET_TOLERANCE_RAD, err_msg=task)


def task_scores(tape, measured_q):
    time = tape.t
    angles = tape.positions[:, 0]
    if measured_q.shape != angles.shape or not np.isfinite(measured_q).all():
        raise ValueError("the measured angle must cover every target sample")
    desired = tip_poses(angles)[:, :3, 3]
    measured = tip_poses(measured_q)[:, :3, 3]
    rest = metrics.stop_windows(time, metrics.moving_mask(time, desired, tape.velocities))
    if not rest:
        raise ValueError("the tape has no qualifying stop")
    rms = metrics.tool_track_rms_mm(desired, measured, np.ones(len(time), dtype=bool))
    independent_chord_mm = 2000 * TIP_LENGTH_M * np.sin((measured_q - angles) / 2)
    stop = metrics.stop_error_max_mm(time, desired, measured, rest)
    independent_stop_errors = []
    for first, last in rest:
        tail = (time >= max(first, last - 0.1) - 1e-9) & (time <= last + 1e-9)
        angular_mean = np.mean(np.exp(1j * angles[tail]) - np.exp(1j * measured_q[tail]))
        independent_stop_errors.append(1000 * TIP_LENGTH_M * abs(angular_mean))
    np.testing.assert_allclose((rms, stop),
                               (np.sqrt(np.mean(independent_chord_mm**2)), max(independent_stop_errors)),
                               rtol=0, atol=1e-9)
    return {"samples": len(time), "stops": len(rest), "worst_stop_mm": stop, "full_rms_mm": rms}


def trace_groups(directory, tapes):
    groups = {}
    for path in sorted(directory.glob("workspace-dev-*__s1.0__r*.trace.npz")):
        with np.load(path) as trace:
            meta = json.loads(str(trace["meta"]))
        if (meta["robot"], meta["dataset"], meta["dataset_version"], meta["controller"], meta["split"],
                meta["rung"], meta["domain"]) != ("pendulum", "workspace", "v2", CONTROLLER, "dev", RUNG, "real"):
            raise ValueError(f"unexpected archive metadata in {path.name}")
        if meta["aborted"] or meta["faults"] or meta["real"]["missing_ticks"]:
            raise ValueError(f"incomplete top-rung archive trace {path.name}")
        group = groups.setdefault(Path(meta["real"]["run"]), {})
        task = meta["task_id"]
        if task not in tapes or task in group:
            raise ValueError(f"unexpected or duplicate archive target {task}")
        group[task] = meta["tour_rows"][0]
    if len(groups) != REPEATS or any(set(group) != set(tapes) for group in groups.values()):
        raise ValueError("expected three complete and distinct archive tours")
    return groups


def archived_pairs(tapes, directory, scene_dir):
    groups = trace_groups(directory, tapes)
    provenance, results = [], []
    for raw, tasks in groups.items():
        real, run, _, parameters, bus_v = pendulum_twin.replay_setup(STATION, raw, twin=VERSION)
        if run.station.output_per_board != 1.0:
            raise ValueError("the historical board and physical output do not share the angle units")
        with np.load(raw) as captured:
            ticks = captured["tick"]
            np.testing.assert_array_equal(captured["t"] - captured["t"][0], run.t)
        if not np.array_equal(ticks, np.arange(len(ticks))):
            raise ValueError(f"{raw.name}: the archive has a missing or repeated command tick")
        prelude = int(round(real.meta["prelude_s"] / real.meta["tick_s"]))
        played = pendulum_twin.as_sent(run)
        replayed = pendulum_twin.joint_twin(run.station, parameters, scene_dir=scene_dir).replay(played, 0.0)
        np.testing.assert_array_equal(replayed.t, run.t)
        for task, offset in tasks.items():
            tape = tapes[task]
            window = slice(prelude + offset, prelude + offset + len(tape.t))
            if not run.controlled[window].all() or not (replayed.mode[window] == 10).all():
                raise ValueError(f"{task}: a matched row is out of position control")
            matched_target(task, played.q_target[window], tape)
            real_score = task_scores(tape, run.q[window])
            twin_score = task_scores(tape, replayed.q[window])
            load_score = task_scores(tape, replayed.q_link[window]) if replayed.q_link is not None else None
            chord = 2000 * TIP_LENGTH_M * np.sin((run.q[window] - replayed.q[window]) / 2)
            results.append({"task": task, "recording": raw.name, "archive_encoder": real_score,
                            "twin_encoder": twin_score, "twin_load": load_score,
                            "encoder_model_gap_rms_mm": float(np.sqrt(np.mean(chord**2)))})
        provenance.append({"archive": raw.name, "archive_sha256": digest(raw), "metadata_sha256": digest(raw.with_suffix(".json")),
                           "board": dict(run.station.board_pid), "kp_scale": real.meta["args"]["kp_scale"],
                           "kd_scale": real.meta["args"]["kd_scale"], "bus_voltage_v": bus_v})
    return provenance, results


def nominal_gains(tapes, scene_dir):
    results = []
    for task, tape in tapes.items():
        step = pendulum_sim.plan_step(tape.positions[:, 0], CONTROLLER, label=f"{task} at {RUNG}")
        step.update(kp_scale_cmd=1.0, kd_scale_cmd=1.0)
        result = pendulum_twin.simulate(STATION, step, twin=VERSION, q0_rad=float(step["origin_rad"]), scene_dir=scene_dir)
        rows = pendulum_sim.tape_rows(result)[:len(tape.t)]
        matched_target(task, result["q_target"][rows], tape)
        if not (result["mode"][rows] == 10).all():
            raise ValueError(f"{task}: a nominal-gain row left position control")
        results.append({"task": task, "twin_encoder": task_scores(tape, result["q"][rows]),
                        "limiter_counts": pendulum_sim.limiter_counts(result["fault"][rows])})
    return results


def summarize(rows, source):
    available = [row for row in rows if row[source] is not None]
    if not available:
        return None
    result = {"runs": len(available), "passes_both": sum(row[source]["worst_stop_mm"] < 0.5 and row[source]["full_rms_mm"] < 1.0
                                                        for row in available)}
    for field in ("worst_stop_mm", "full_rms_mm"):
        worst = max(available, key=lambda row: row[source][field])
        result[field] = {"mm": worst[source][field], "task": worst["task"], "recording": worst.get("recording")}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("archive_dev_traces", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    model_path = pendulum_twin.version_path(STATION, VERSION)
    if digest(model_path) != MODEL_SHA:
        raise ValueError("the adopted model differs from the frozen revision")
    label, parameters = pendulum_twin.twin_parameters(STATION, VERSION)
    tapes = frozen_tapes(load_dataset(args.dataset))
    scene_dir = args.output.parent / "scenes"
    provenance, pairs = archived_pairs(tapes, args.archive_dev_traces, scene_dir)
    nominal = nominal_gains(tapes, scene_dir)
    report = {"dataset_manifest_sha256": DATASET_SHA, "ranked_ledger_scope": False, "rung": RUNG, "split": "dev",
              "model": {"version": VERSION, "sha256": MODEL_SHA, "label": label, "mujoco": mujoco.__version__,
                        "runner_sha256": digest(Path(pendulum_twin.__file__)),
                        "backlash_rad": parameters.backlash_rad, "gear_stiffness_nm_rad": parameters.gear_stiffness_nm_rad},
              "archive": provenance, "archive_encoder": summarize(pairs, "archive_encoder"),
              "paired_twin_encoder": summarize(pairs, "twin_encoder"), "paired_twin_load": summarize(pairs, "twin_load"),
              "paired_encoder_model_gap_max_rms_mm": max(row["encoder_model_gap_rms_mm"] for row in pairs),
              "nominal_gain_twin_encoder": summarize(nominal, "twin_encoder"),
              "nominal_gain_scale": {"kp": 1.0, "kd": 1.0}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.output.with_suffix(".rows.json").write_text(json.dumps({"paired": pairs, "nominal": nominal}, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
