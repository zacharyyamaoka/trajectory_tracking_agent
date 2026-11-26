"""Fit and replay a six-drive BAM FB controller using only exposed joint samples."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from arm_motion_bench.baselines import bam_fb_sim
from arm_motion_bench.datasets import load_dataset
from arm_motion_bench.records import Trace
from robot_controllers.bench.fivebar import fivebar_feedforward
from robot_controllers.bench.scenarios import base_scenario


NAME = "public-calibrated"
BAND_RAD_S = 0.025
GAIN_FIELDS = {"kp_scale", "kd_scale", "hold_kp_scale", "hold_kd_scale", "lead_s"}


class PublicModel:
    """Private to the controller. Its only inputs are the public model and the reference."""

    def __init__(self):
        error = base_scenario("bam_fivebar").model_error
        self.gravity = fivebar_feedforward("gravity", error)
        self.rigid_body = fivebar_feedforward("rigid_body", error)

    def evaluate(self, position, velocity, acceleration):
        gravity = self.gravity(position, velocity, acceleration)
        motion = self.rigid_body(position, velocity, acceleration) - gravity
        # WHY learn a gravity residual from the exposed states: the composed wrist and claw alter the stock link loads.
        pose = np.column_stack((np.ones(len(position)), np.sin(position), np.cos(position),
                                np.sin(position[:, 1:3] + position[:, 3:5]),
                                np.cos(position[:, 1:3] + position[:, 3:5])))
        static = np.concatenate((gravity[:, :, None], np.broadcast_to(pose[:, None, :], (len(position), 6, pose.shape[1]))),
                                axis=2)
        direction = np.tanh(velocity / BAND_RAD_S)
        dynamic = np.stack((motion, velocity, direction, np.abs(direction), acceleration), axis=2)
        return gravity, motion, static, dynamic


def file_sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def controller_sha(parameters, gains=None):
    authored = json.dumps({"parameters": parameters, "gains": gains or {}}, sort_keys=True, allow_nan=False)
    return hashlib.sha256(Path(__file__).read_bytes() + authored.encode()).hexdigest()


def fit(traces):
    model = PublicModel()
    observations = []
    design = []
    inputs = []
    for path in sorted(traces):
        trace = Trace.load(path)
        meta = trace.meta
        if (meta.get("robot"), meta.get("domain"), meta.get("split")) != ("bam_fb", "sim", "dev"):
            raise ValueError(f"{path.name}: calibration must use BAM FB simulation development observations")
        if meta.get("aborted") or meta.get("faults") or meta.get("collisions") or meta.get("collision_detected_t") is not None:
            raise ValueError(f"{path.name}: interrupted or contacted calibration run")
        time = np.asarray(trace.t)
        step = float(np.median(np.diff(time)))
        if len(time) < 17 or not np.allclose(np.diff(time), step, atol=1e-9, rtol=0):
            raise ValueError(f"{path.name}: incomplete or irregular acquisition")
        q = np.asarray(trace.q)
        window = np.lib.stride_tricks.sliding_window_view(q, 9, axis=0)
        polynomial = np.linalg.pinv(np.vander(np.arange(-4, 5), 4, increasing=True))
        velocity = window @ polynomial[1] / step
        acceleration = window @ polynomial[2] * (2.0 / step**2)
        gravity, motion, static, dynamic = model.evaluate(q[4:-4], velocity, acceleration)
        design.append(np.concatenate((static, dynamic), axis=-1))
        observations.append(trace.tau[4:-4] - gravity - motion)
        inputs.append({"task": meta["task_id"], "sha256": file_sha(path)})

    features, residual = np.concatenate(design), np.concatenate(observations)
    if not np.isfinite(features).all() or not np.isfinite(residual).all():
        raise ValueError("calibration includes a non-finite sample")
    coefficients = []
    for axis in range(features.shape[1]):
        matrix = features[:, axis, :]
        # WHY regularize in torque units: it keeps nearly stationary wrist features from acquiring enormous coefficients.
        scale = np.maximum(np.sqrt(np.mean(matrix**2, axis=0)), 0.1)
        normalized = matrix / scale
        weights = np.ones(len(matrix))
        for _ in range(4):
            penalty = len(matrix) * 0.005 * np.eye(matrix.shape[1])
            weighted = normalized.T * weights
            scaled = np.linalg.solve(weighted @ normalized + penalty, weighted @ residual[:, axis])
            error = np.abs(residual[:, axis] - normalized @ scaled)
            robust_scale = max(float(np.median(error)) * 2.5, 0.005)
            weights = robust_scale / np.maximum(error, robust_scale)
        coefficients.append((scaled / scale).tolist())
    return {"schema": "tta.bam-fb-calibration/1", "model": "robot_controllers stock five-bar rigid body at ±10% link mass/inertia",
            "fits": inputs, "samples": len(features), "coefficients": coefficients}


def replay(target, stops, parameters, *, meta, task_meta, repeat=0, seed=0, rung=1.0,
           name=NAME, gains=None, thresholds_nm=None, detector="armed"):
    gains = gains or {}
    if gains.keys() - GAIN_FIELDS:
        raise ValueError(f"unknown gain fields: {gains.keys() - GAIN_FIELDS}")
    if detector == "off" and meta.get("split") != "dev":
        raise ValueError("detector-off replays are restricted to development calibration")
    model = PublicModel()
    if parameters.get("schema") != "tta.bam-fb-calibration/1":
        raise ValueError("unrecognized BAM FB calibration")
    coefficients = np.asarray(parameters["coefficients"], dtype=float)

    def torque(position, velocity, acceleration):
        gravity, motion, static, dynamic = model.evaluate(position, velocity, acceleration)
        if coefficients.shape != (6, static.shape[-1] + dynamic.shape[-1]):
            raise ValueError("BAM FB calibration coefficients do not match the feedforward model")
        split = static.shape[-1]
        gravity = gravity + np.sum(static * coefficients[:, :split], axis=-1)
        motion = motion + np.sum(dynamic * coefficients[:, split:], axis=-1)
        return gravity + motion, gravity

    overrides = {**bam_fb_sim.HOLD_FRICTION_V2, "coulomb_ff_nm": (0.0,) * 6, "viscous_nm_s": None, **gains}
    trace = bam_fb_sim.run(target, stops, "hold_friction_v2", repeat=repeat, seed=seed, rung=rung, meta=meta,
                           task_meta=task_meta, detector=detector, thresholds_nm=thresholds_nm, overrides=overrides,
                           feedforward=torque, capture_synchronous_tcp=True)
    trace.meta["controller"] = name
    trace.meta["controller_sha256"] = controller_sha(parameters, gains)
    trace.meta["controller_description"] = "BAM FB calibrated public load model and friction on stock feedback"
    return trace


def run_job(job):
    dataset = load_dataset(job["path"])
    task = dataset.task(job["task"])
    rung = max(task.rungs)
    target = dataset.target(task.task_id, rung)
    stops = dataset.stops(task.task_id, rung)
    meta = {"task_id": task.task_id, "dataset": task.dataset, "split": task.split, "dataset_version": "v2"}
    filename = bam_fb_sim.trace_path(job["out"], "bam_fb", job["name"], task.dataset, "v2", task.split,
                                    task.task_id, rung, job["repeat"])
    identifier = controller_sha(job["parameters"], job["gains"])
    if filename.exists():
        previous = Trace.load(filename)
        if previous.meta.get("controller_sha256") != identifier:
            raise ValueError(f"existing file {filename.name} belongs to a different candidate")
        return f"{task.task_id} existing"
    trace = replay(target, stops, job["parameters"], meta=meta, task_meta=dict(task.meta), repeat=job["repeat"],
                   seed=bam_fb_sim.task_seed(task.task_id), rung=rung, name=job["name"], gains=job["gains"],
                   thresholds_nm=job["thresholds"], detector=job["detector"])
    filename.parent.mkdir(parents=True, exist_ok=True)
    temporary = filename.with_suffix(".partial.npz")
    trace.save(temporary)
    temporary.replace(filename)
    return f"{task.task_id} repeat {job['repeat']} acquired"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    fit_args = commands.add_parser("fit", help="learn from archived sim dev observations")
    fit_args.add_argument("traces", nargs="+", type=Path)
    fit_args.add_argument("--output", required=True, type=Path)
    run_args = commands.add_parser("run", help="score the stock highest rung for each selected tape")
    run_args.add_argument("--dataset", required=True, type=Path)
    run_args.add_argument("--parameters", required=True, type=Path)
    run_args.add_argument("--output", required=True, type=Path)
    run_args.add_argument("--split", choices=("dev", "holdout"), default="dev")
    run_args.add_argument("--tasks", nargs="+")
    run_args.add_argument("--name", default=NAME)
    run_args.add_argument("--workers", default=2, type=int)
    run_args.add_argument("--repeats", nargs="+", default=[0], type=int)
    run_args.add_argument("--gains-json", type=Path)
    run_args.add_argument("--thresholds-json", type=Path)
    run_args.add_argument("--detector", choices=("armed", "off"), default="armed")
    args = parser.parse_args()
    if args.action == "fit":
        result = fit(args.traces)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(f"Calibrated on {result['samples']} development samples from {len(result['fits'])} tape replays")
        return
    parameters = json.loads(args.parameters.read_text())
    gains = json.loads(args.gains_json.read_text()) if args.gains_json else None
    thresholds = json.loads(args.thresholds_json.read_text()) if args.thresholds_json else None
    if thresholds is not None and (len(thresholds) != 6 or any(not math.isfinite(value) or value <= 0 for value in thresholds)):
        parser.error("thresholds must be a list of six finite positive torques")
    selected = [task.task_id for task in load_dataset(args.dataset).tasks_in(args.split)]
    if args.tasks:
        if set(args.tasks) - set(selected):
            parser.error("all selected tasks must belong to the declared split")
        selected = args.tasks
    jobs = [{"path": args.dataset, "task": task, "parameters": parameters, "gains": gains, "thresholds": thresholds,
             "out": args.output, "name": args.name, "repeat": repeat, "detector": args.detector}
            for task in selected for repeat in args.repeats]
    with ProcessPoolExecutor(max_workers=args.workers) as workers:
        for progress in workers.map(run_job, jobs):
            print(progress, flush=True)


if __name__ == "__main__":
    main()
