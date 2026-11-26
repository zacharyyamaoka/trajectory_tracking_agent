"""Replay the locked BAM FB controller against the tracking plant with synthetic gear gaps."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import replace
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import mujoco
import numpy as np

from arm_motion_bench.baselines import bam_fb_sim as bench
from arm_motion_bench.datasets import load_dataset
from arm_motion_bench.records import Trace
from bam_arm_fb_sim import compose, plant
from bam_arm_fb_sim.kin import Kin
from gear_backlash.wrap import BacklashModel, LINK_SUFFIX
from sim2real.sim.homing.fullarm_plant import hidden_specs
from trajectory_tracking_agent.ruler import metrics


ROOT = Path(__file__).resolve().parents[2]
LANE = Path(__file__).resolve().parent
PANEL = {"workspace": ("workspace-dev-000", "workspace-dev-038"), "conveyor": ("conveyor-dev-018",)}
BASELINES = {
    "workspace": "bam-fb-workspace/public-calibrated-x8hold8-traces",
    "conveyor": "bam-fb-conveyor/pilots/moving-800-hold-800",
}
MODEL_PARITY_TOL_M = 1e-11
TRACE_PARITY_TOL_MM = 1e-5
SIMULATOR_WARNINGS = tuple(mujoco.mjtWarning.__members__)[:-1]


def require(condition, explanation):
    if not condition:
        raise ValueError(explanation)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def repo_revision(source_file):
    return subprocess.check_output(["git", "-C", str(Path(source_file).resolve().parent), "rev-parse", "HEAD"],
                                   text=True).strip()


def read_lock():
    folder = ROOT / "experiments/bam_fb_conveyor"
    lock = json.loads((folder / "controller-lock.json").read_text())
    frozen = ROOT / "outputs/bam-fb-conveyor/frozen-candidate"
    paths = (frozen / "candidate.py", frozen / "calibration.json", folder / "moving-800-hold-800.json")
    for path, field in zip(paths, ("controller_source", "calibration_source", "gains_source"), strict=True):
        require(digest(path) == lock[field]["sha256"], f"locked {field} changed")
    module_spec = importlib.util.spec_from_file_location("locked_bam_fb", paths[0])
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    parameters = json.loads(paths[1].read_text())
    gains = json.loads(paths[2].read_text())
    require(module.controller_sha(parameters, gains) == lock["controller_sha256"], "candidate fingerprint changed")
    return lock, module, parameters, gains


def capture_tracking_spec(nominal):
    # WHY capture the stock composition: the homing fixture has no claw site, and serializing a compiled MJB
    # would discard the original editable model and its attached CAD assets.
    captured = None
    compile_model = mujoco.MjSpec.compile

    def compile_and_retain(spec, *args, **kwargs):
        nonlocal captured
        model = compile_model(spec, *args, **kwargs)
        if model.nsite == nominal.model.nsite and model.ngeom == nominal.model.ngeom and model.npair == nominal.model.npair:
            captured = spec
        return model

    with patch.object(mujoco.MjSpec, "compile", compile_and_retain):
        compose.build_arm()
    require(captured is not None, "the original composed tracking model was not captured")
    return captured


def transfer_model(spec, nominal, gear, *, friction_on_output):
    drive_names = nominal.drive_joints
    authored = spec.copy()
    if friction_on_output and any(item.total_gap_rad > 0.0 for item in gear.values()):
        # WHY seed the joint friction before wrapping: the stock wrist adds breakaway only at runtime.
        # Wrapping a positive friction on every axis makes the stock wrapper route it to the output.
        for role, name in zip(plant.DRIVE_ORDER, drive_names, strict=True):
            truth = plant.TRUTH[role]
            if truth.sliding_nm is not None:
                authored.joint(name).frictionloss = truth.sliding_nm
    wrapped = BacklashModel(authored, gear, method="passive_joint", zero="center", output_friction=friction_on_output)
    arm = compose.arm_from_model(wrapped.model, compose.arm_meta(nominal))
    if wrapped.enabled and friction_on_output:
        tendon_ids = np.array([arm.model.tendon(name + LINK_SUFFIX).id for name in drive_names])
        solref = nominal.model.dof_solref[nominal.dadr].copy()
        solref[[plant.TRUTH[role].sliding_nm is not None for role in plant.DRIVE_ORDER]] = (0.002, 1.0)
        arm.model.tendon_solref_fri[tendon_ids] = solref
        arm.model.tendon_solimp_fri[tendon_ids] = nominal.model.dof_solimp[nominal.dadr]
    return arm, wrapped


def expanded_pose(qpos, nominal, variant):
    expanded = variant.model.qpos0.copy()
    for joint in range(nominal.model.njnt):
        name = nominal.model.joint(joint).name
        expanded[variant.model.joint(name).qposadr[0]] = qpos[nominal.model.jnt_qposadr[joint]]
    return expanded


def geometry_check(nominal, variant, wrapped, datasets):
    """Check the whole nominal geometry and the claw frame/branch at fixed route waypoints."""
    match = ("body_pos", "body_quat", "body_mass", "body_inertia", "body_ipos", "body_iquat",
             "geom_pos", "geom_quat", "geom_size", "geom_contype", "geom_conaffinity", "pair_geom1",
             "pair_geom2", "site_pos", "site_quat", "site_bodyid", "eq_objtype", "eq_type", "eq_data")
    for field in match:
        require(np.allclose(getattr(nominal.model, field), getattr(variant.model, field), atol=1e-12, rtol=0),
                f"tracking model changed {field}")
    # The passive hinges shift MuJoCo's integer IDs; the equality still names the same bodies and claw joint.
    for index, objtype in enumerate(nominal.model.eq_objtype):
        objtype = mujoco.mjtObj(objtype)
        for name in ("eq_obj1id", "eq_obj2id"):
            a, b = getattr(nominal.model, name)[index], getattr(variant.model, name)[index]
            require(mujoco.mj_id2name(nominal.model, objtype, a) == mujoco.mj_id2name(variant.model, objtype, b)
                    and (a < 0) == (b < 0), f"tracking model changed equality {index} {name}")
    require(variant.model.nq == nominal.model.nq + len(wrapped.joints), "unexpected added coordinates")
    require(variant.model.site(variant.tcp_site).name == nominal.model.site(nominal.tcp_site).name == "tcp",
            "comparison must use the stock claw site")
    original_kin, check_kin = Kin(nominal), Kin(variant)
    require(original_kin.working_branch == check_kin.working_branch != 0.0, "working branches disagree")
    largest_position, largest_rotation, largest_closure = 0.0, 0.0, 0.0
    stations = 0
    for kind, task_ids in PANEL.items():
        for task_id in task_ids:
            trajectory = datasets[kind].target(task_id, rung=1.0)
            for index in np.linspace(0, len(trajectory.positions) - 1, 11, dtype=int):
                position = trajectory.positions[index]
                qpos, residual = original_kin.pose(position)
                require(residual < 1e-7 and original_kin.branch() == original_kin.working_branch,
                        f"{task_id} waypoint {index} is off the nominal working branch")
                check_qpos = expanded_pose(qpos, nominal, variant)
                check_data = check_kin.data
                require(check_kin.branch(check_qpos) == original_kin.working_branch,
                        f"{task_id} waypoint {index} changed assembly")
                largest_closure = max(largest_closure, check_kin.residual())
                mujoco.mj_forward(variant.model, check_data)
                largest_position = max(largest_position, np.linalg.norm(
                    original_kin.data.site_xpos[nominal.tcp_site] - check_data.site_xpos[variant.tcp_site]))
                largest_rotation = max(largest_rotation, np.max(np.abs(
                    original_kin.data.site_xmat[nominal.tcp_site] - check_data.site_xmat[variant.tcp_site])))
                require(np.allclose(wrapped.link_qpos(check_data), qpos, atol=1e-12, rtol=0),
                        "zero-twist link mapping changed an original joint")
                stations += 1
    require(max(largest_position, largest_rotation) < MODEL_PARITY_TOL_M and largest_closure < 1e-7,
            "claw frame or closure differs at zero twist")
    for joint in wrapped.joints.values():
        data = check_kin.data
        pose = data.qpos.copy()
        position = data.site_xpos[variant.tcp_site].copy()
        rotation = data.site_xmat[variant.tcp_site].copy()
        angle = joint.spec.half_gap_rad * 0.5
        data.qpos[joint.motor_qpos] -= angle
        data.qpos[joint.gap_qpos] += angle
        mujoco.mj_kinematics(variant.model, data)
        require(np.allclose(data.site_xpos[variant.tcp_site], position, atol=MODEL_PARITY_TOL_M, rtol=0)
                and np.allclose(data.site_xmat[variant.tcp_site], rotation, atol=MODEL_PARITY_TOL_M, rtol=0),
                f"{joint.name} moved the claw at equal and opposite gear twist")
        data.qpos[:] = pose
        mujoco.mj_kinematics(variant.model, data)
    return {"waypoints": stations, "site": "tcp", "branch": original_kin.working_branch,
            "claw_position_delta_max_m": float(largest_position), "claw_rotation_delta_max_component": float(largest_rotation),
            "loop_closure_residual_max_m": float(largest_closure), "joint_coordinates": int(variant.model.nq)}


@contextmanager
def replay_plant(nominal, variant, wrapped, capture, friction_factor, *, friction_on_output):
    original = plant.ArmPlant
    original_bench_context = bench._bench_plants
    mj_step = mujoco.mj_step
    output_tendons = wrapped.enabled and friction_on_output

    class TransferPlant(original):
        def __init__(self, tracking_arm, gains, start_drives, **kwargs):
            super().__init__(tracking_arm, gains, start_drives, **kwargs)
            qpos = expanded_pose(self.data.qpos, nominal, variant)
            self.arm, self.model = variant, variant.model
            self.data = mujoco.MjData(self.model)
            self._qadr, self._dadr = variant.qadr, variant.dadr
            self.data.qpos[:] = qpos
            mujoco.mj_forward(self.model, self.data)
            capture["data"] = self.data
            if output_tendons:
                capture["wrist"] = np.flatnonzero(self._switched)
                capture["slide"] = self._sliding[self._switched] * friction_factor
                capture["break"] = self._breakaway[self._switched] * friction_factor
                self._switched[:] = False
            else:
                # Match the base plant's initialization on the new, equivalent compiled model.
                dofs = self._dadr[self._switched]
                self.model.dof_solref[dofs] = (0.002, 1.0)
                self.model.dof_frictionloss[dofs] = self._breakaway[self._switched]
                mujoco.mj_forward(self.model, self.data)

        def true_drives(self):
            return wrapped.link_qpos(self.data)[nominal.qadr]

        def true_tcp(self):
            point = super().true_tcp()
            capture["motor"].append(wrapped.motor_qpos(self.data)[nominal.qadr])
            capture["link"].append(self.true_drives())
            capture["branch"].append(branch_kin.branch(wrapped.link_qpos(self.data)))
            capture["clock"].append(self.data.time)
            return point

    def before_physics(model, data):
        if output_tendons and data is capture.get("data"):
            # WHY select stick/slip before mj_step: the solver copies friction loss when creating constraints.
            # Link speed includes gear twist, so an accelerating rotor alone cannot break wrist static friction.
            speed = wrapped.link_qvel(data)[nominal.dadr[capture["wrist"]]]
            model.tendon_frictionloss[tendon_ids] = np.where(
                np.abs(speed) >= plant.STICK_SPEED_RAD_S, capture["slide"], capture["break"])
        return mj_step(model, data)

    @contextmanager
    def bench_context(arm, state, perturbation, rng):
        require(rng is None, "the paired transfer experiment uses repeat 0 only")
        with original_bench_context(arm, state, perturbation, rng):
            state.contact.site = variant.tcp_site
            state.contact.drive_dofs = variant.dadr
            state.contact.jacobian = np.zeros((3, variant.model.nv))
            yield

    branch_kin = Kin(nominal)
    if output_tendons:
        tendon_ids = np.array([variant.model.tendon(variant.drive_joints[axis] + LINK_SUFFIX).id
                              for axis, role in enumerate(plant.DRIVE_ORDER) if plant.TRUTH[role].sliding_nm is not None])
    # Both shims are restricted to the simulator process. The bench still owns its private collision detector,
    # host and board loop, target encoder FK, contact response, and reference feed-forward boundary.
    with (patch.object(plant, "ArmPlant", TransferPlant),
          patch.object(bench, "_bench_plants", bench_context),
          patch.object(mujoco, "mj_step", before_physics)):
        yield


def target_datasets(bench_root, lock):
    datasets = {}
    for kind in PANEL:
        path = bench_root / "datasets" / "bam_fb" / kind / "v2"
        require(digest(path / "manifest.json") == lock["projects"][kind]["manifest_sha256"],
                f"{kind} target manifest changed")
        dataset = load_dataset(path)
        require(digest(path / "tasks.jsonl") == dataset.manifest["tasks_sha256"], f"{kind} task metadata changed")
        for task_id in PANEL[kind]:
            task = dataset.task(task_id)
            require(task.split == "dev" and max(task.rungs) == 1.0, f"{task_id} is outside the fixed dev panel")
            for filename in (f"{task_id}.npz", f"{task_id}.tcp.npz"):
                require(digest(dataset.tapes_dir / filename) == dataset.manifest["files"][filename],
                        f"{filename} differs from its frozen tape digest")
        datasets[kind] = dataset
    return datasets


def limit_errors(trace, target, windows, actual):
    require(np.isfinite(actual).all() and actual.shape == target.shape, "missing or invalid TCP samples")
    return {
        "full_rms_mm": metrics.tool_track_rms_mm(target, actual, np.ones(len(trace.t), dtype=bool)),
        "max_stop_mm": metrics.stop_error_max_mm(trace.t, target, actual, windows),
    }


def compare_archive(trace, archived):
    require(not trace.meta["faults"] and not trace.meta["aborted"], "the zero-gap replay produced faults")
    for key in ("t", "q", "qd", "tau", "target_q", "target_qd", "target_qdd", "target_tcp_pos", "tcp_pos"):
        require(np.allclose(getattr(trace, key), getattr(archived, key), atol=1e-8, rtol=0),
                f"zero-gap base replay differs from archived {key}")
    for key in ("collisions", "contacts", "collision_detected_t", "plant"):
        require(trace.meta[key] == archived.meta[key], f"zero-gap base replay differs from archived {key}")
    require(trace.stops == archived.stops, "zero-gap stop windows differ from the archive")
    delta_mm = float(np.max(np.linalg.norm(trace.optional["synchronous_tcp_pos"] -
                                           archived.optional["synchronous_tcp_pos"], axis=1)) * 1000.0)
    require(delta_mm <= TRACE_PARITY_TOL_MM, f"zero-gap claw parity {delta_mm:.6g} mm exceeds tolerance")
    return delta_mm


def run_case(bundle, dataset, kind, task_id, nominal, variant, wrapped, condition, factor, out, *, friction_on_output):
    lock, module, parameters, gains = bundle
    task = dataset.task(task_id)
    target = dataset.target(task_id, rung=1.0)
    stops = dataset.stops(task_id, rung=1.0)
    capture = {"motor": [], "link": [], "branch": [], "clock": []}
    meta = {"task_id": task_id, "dataset": kind, "split": "dev", "dataset_version": "v2"}
    with replay_plant(nominal, variant, wrapped, capture, factor, friction_on_output=friction_on_output):
        trace = module.replay(target, stops, parameters, meta=meta, task_meta=dict(task.meta), detector="armed",
                              gains=gains, repeat=0, seed=bench.task_seed(task_id), rung=1.0)
    require(trace.meta["controller_sha256"] == lock["controller_sha256"] and not trace.meta["idealized"],
            "replay did not use the locked public controller")
    source = trace.meta["source"]
    require((source["git_sha"], source["arm_model_key"]) == (lock["bench_commit"], lock["arm_model_key"]),
            "stock run source changed")
    time, desired, rotation = dataset.target_tcp(task_id, rung=1.0)
    result = {"task": task_id, "condition": condition, "target_samples": len(time), "samples": len(trace.t),
              "detector_trip_s": trace.meta["collision_detected_t"], "faults": trace.meta["faults"],
              "collisions": trace.meta["collisions"], "aborted": trace.meta["aborted"],
              "loop_stretch_max_mm": 1000.0 * trace.meta["plant"]["loop_stretch_max_m"]}
    count = len(trace.t)
    require(all(np.allclose(data, frozen[:count], atol=1e-10, rtol=0) for data, frozen in
                ((trace.t, time), (trace.target_q, target.positions), (trace.target_qd, target.velocities),
                 (trace.target_qdd, target.accelerations), (trace.target_tcp_pos, desired),
                 (trace.target_tcp_rot, rotation))), "bench target no longer matches frozen acquisition")
    branch = np.asarray(capture["branch"][:count])
    result["off_working_branch_samples"] = int(np.count_nonzero(branch != Kin(nominal).working_branch))
    result["physics_clock_max_delta_s"] = float(np.max(np.abs(np.asarray(capture["clock"][:count]) - trace.t)))
    result["mujoco_warnings"] = {name: int(capture["data"].warning[number].number)
                                 for number, name in enumerate(SIMULATOR_WARNINGS)
                                 if capture["data"].warning[number].number}
    actual = trace.optional["synchronous_tcp_pos"]
    motor, link = (np.asarray(capture[key][:count]) for key in ("motor", "link"))
    result["maximum_shaft_split_deg"] = np.degrees(np.max(np.abs(motor - link), axis=0)).tolist()
    result["archive_parity_tcp_max_mm"] = None
    if condition == "zero-gap":
        archived_path = list((ROOT / "outputs" / BASELINES[kind]).rglob(f"{task_id}__s1.0__r0.trace.npz"))
        require(len(archived_path) == 1, f"{task_id} requires one archived nominal replay")
        result["archive_parity_tcp_max_mm"] = compare_archive(trace, Trace.load(archived_path[0]))
    windows = metrics.stop_windows(time, metrics.moving_mask(time, desired, target.velocities))
    require(bool(windows), f"{task_id} contains no frozen stop windows")
    result["actual_claw"] = result["motor_encoder_fk"] = None
    if count == len(time):
        for key, position in (("actual_claw", actual), ("motor_encoder_fk", trace.tcp_pos)):
            if np.isfinite(position).all():
                result[key] = limit_errors(trace, desired, windows, position)
    actual_score = result["actual_claw"]
    result["passes_stress"] = bool(actual_score and actual_score["max_stop_mm"] < 0.5
        and actual_score["full_rms_mm"] < 1.0 and not result["faults"] and not result["aborted"]
        and not result["collisions"] and result["detector_trip_s"] is None and not result["off_working_branch_samples"]
        and not result["mujoco_warnings"] and result["physics_clock_max_delta_s"] <= 1e-8)
    trace.meta["synthetic_transfer_condition"] = condition
    trace.meta["nominal_plant_qualification_only"] = False
    trace.optional.update({"current_tick_motor_q": motor, "current_tick_link_q": link, "working_branch": branch})
    trace_path = out / f"{condition}--{task_id}.trace.npz"
    trace.save(trace_path)
    result["trace_sha256"] = digest(trace_path)
    print(json.dumps(result, allow_nan=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="retain complete, previously verified zero-gap replays")
    parser.add_argument("--motor-friction-ablation", action="store_true",
                        help="keep the stock Coulomb model on the original motor hinges while adding B2")
    args = parser.parse_args()
    if args.motor_friction_ablation and not args.resume:
        parser.error("--motor-friction-ablation requires --resume and an existing zero-gap checkpoint")
    args.output.mkdir(parents=True, exist_ok=True)
    bundle = read_lock()
    lock = bundle[0]
    datasets = target_datasets(args.bench, lock)
    nominal = bench.station().arm
    synthetic = hidden_specs("B2")
    gaps = {name: synthetic[role.upper()] for name, role in zip(nominal.drive_joints, plant.DRIVE_ORDER, strict=True)}
    zero = {name: replace(item, total_gap_rad=0.0) for name, item in gaps.items()}
    payload = {"schema": "tta.bam-fb-geared-dev/1", "mujoco": mujoco.__version__, "rung": 1.0, "repeat": 0,
               "controller_sha256": lock["controller_sha256"], "base_bench_source": lock["bench_commit"],
               "base_arm_model_key": lock["arm_model_key"], "roles": list(plant.DRIVE_ORDER),
               "composition_revision": repo_revision(compose.__file__),
               "gear_model_revision": repo_revision(importlib.util.find_spec(BacklashModel.__module__).origin),
               "synthetic_input_revision": repo_revision(importlib.util.find_spec(hidden_specs.__module__).origin),
               "input_manifests": {kind: lock["projects"][kind]["manifest_sha256"] for kind in PANEL},
               "gap_source": "synthetic Sim2Real fullarm_plant.hidden_specs('B2'), applied through gear_backlash",
               "gaps_deg": [float(np.degrees(item.total_gap_rad)) for item in gaps.values()],
               "mesh_stiffness_nm_per_rad": [item.mesh_stiffness_nm_per_rad for item in gaps.values()],
               "geometry": {}, "runs": []}
    output = args.output / "results.json"
    if args.resume:
        previous = json.loads(output.read_text())
        require(all(previous[key] == payload[key] for key in payload if key not in ("geometry", "runs")),
                "the checkpoint was acquired with different inputs")
        completed = [row for row in previous["runs"] if row["condition"] == "zero-gap"]
        require({row["task"] for row in completed if row["passes_stress"]} == set(sum(PANEL.values(), ())),
                "the checkpoint does not contain all passing zero-gap controls")
        for row in completed:
            saved = args.output / f'zero-gap--{row["task"]}.trace.npz'
            require(digest(saved) == row["trace_sha256"], "the saved zero-gap trace changed")
        payload["geometry"]["zero-gap"] = previous["geometry"]["zero-gap"]
        payload["runs"] = completed
    print("Rebuilding the stock tracking MJCF to retain its authored geometry", flush=True)
    source = capture_tracking_spec(nominal)
    conditions = (("b2", 1.0), ("b2-friction-1.25", plant.FRICTION_VARIANTS["friction_x1.25"]))
    if args.motor_friction_ablation:
        output = args.output / "motor-friction-results.json"
        conditions = (("b2-motor-friction", 1.0),)
    elif not args.resume:
        conditions = (("zero-gap", 1.0),) + conditions
    for condition, factor in conditions:
        print(f"Preparing {condition}", flush=True)
        friction_on_output = condition != "b2-motor-friction"
        if condition == "b2-friction-1.25":
            # The two B2 conditions differ only in friction. Reuse the mesh and compiled model.
            for role, name in zip(plant.DRIVE_ORDER, nominal.drive_joints, strict=True):
                if plant.TRUTH[role].sliding_nm is None:
                    tendon = variant.model.tendon(name + LINK_SUFFIX).id
                    variant.model.tendon_frictionloss[tendon] *= factor
            payload["geometry"][condition] = payload["geometry"]["b2"]
        else:
            variant, wrapped = transfer_model(source, nominal, zero if condition == "zero-gap" else gaps,
                                              friction_on_output=friction_on_output)
            payload["geometry"][condition] = geometry_check(nominal, variant, wrapped, datasets)
        for kind, tasks in PANEL.items():
            for task_id in tasks:
                row = run_case(bundle, datasets[kind], kind, task_id, nominal, variant, wrapped, condition, factor, args.output,
                               friction_on_output=friction_on_output)
                payload["runs"].append(row)
                temporary = output.with_suffix(".partial.json")
                temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
                temporary.replace(output)
                if condition == "zero-gap":
                    require(row["passes_stress"], f"{task_id} zero gap failed frame, branch or benchmark parity")
        if condition == "zero-gap":
            del variant, wrapped
            gc.collect()


if __name__ == "__main__":
    main()
