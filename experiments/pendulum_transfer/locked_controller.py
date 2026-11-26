"""Replay frozen 100 Hz G2 controller commands on the stock CAN 11 rack twin."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import mujoco
import numpy as np
from arm_motion_bench.baselines import pendulum_sim
from arm_motion_bench.datasets import load_dataset
from arm_motion_bench.robots.pendulum import TIP_LENGTH_M
from bam_rack_twin import pendulum_twin as rack
from bam_rack_twin.evidence import coulomb_feedforward_output_nm, logged_feedforward_output_nm
from robot_controllers.bench.scenarios import base_scenario
from robot_controllers.bench.types import HostTiming
from robot_msgs.sensor import JointState

from feedforward import Feedforward, IdentifiedSpec
from replay import CONTROLLER, DATASET_SHA, MODEL_SHA, RUNG, STATION, VERSION, digest, frozen_tapes, matched_target, summarize, task_scores
from trajectory_tracking_agent.evaluate import _controller_trajectory

WORKSPACE = Path(__file__).resolve().parent.parent / "pendulum_workspace"
RACK_REV = "05573c957f9c7fb073bedf9a376c30ea38715305"
CONTROLLER_REV = "04d0d58804682237ff606cf85f8958e73a2086df"
RACK_RUNNER_SHA = "344793964d75ca80e22ec48d504bd23a084ecfe4c0e0385bf5ce22d9f54a26a8"
BUS_V = 24.0


def locked_specifications(rate):
    lock = json.loads((WORKSPACE / "controller-lock.json").read_text())
    controller = lock["controller"]
    model_path = WORKSPACE / "can11-fit.json"
    model = json.loads(model_path.read_text())
    if (lock["schema"] != "tta.pendulum-controller-lock/1" or lock["dataset_manifest_sha256"] != DATASET_SHA
        or lock["top_rung"] != RUNG or model["dataset_manifest_sha256"] != DATASET_SHA
        or digest(model_path) != controller["model_sha256"]
        or digest(WORKSPACE / "feedforward.py") != controller["source_sha256"]):
        raise ValueError("the controller files differ from the original G2 lock")
    scenario = replace(base_scenario("pendulum"), host_rate_hz=rate)
    timing = HostTiming.from_bus(scenario.bus, rate, include_compute=False)
    if rate != 100.0 or timing.stalls or timing.jitter_s != 0.0:
        raise ValueError("the locked host schedule is no longer a regular 100 Hz grid")
    nominal = IdentifiedSpec(scenario, model["coefficients"])
    if nominal.name != controller["name"]:
        raise ValueError("the loaded controller differs from the lock")
    locked = replace(nominal, gain_scale=controller["gain_scale"], damping_scale=controller["damping_scale"])
    return controller, nominal, locked


def controller_ticks(tape, spec, state):
    controller = spec.build(_controller_trajectory(tape))
    rows = []
    for dt in np.diff(tape.t, prepend=tape.t[0]):
        command, defines = controller.tick(state, dt)
        if defines or command.max_effort is not None or controller.status == "aborted":
            raise ValueError("the stock rack bridge can only map the locked fixed-gain board-PD layout")
        rows.append((command.position[0], command.velocity[0], command.feedforward_effort[0],
                     command.stiffness[0], command.damping[0]))
    if controller.status != "done":
        raise ValueError("the locked controller did not finish the complete original tape clock")
    return np.asarray(rows)


def identified_commands(tape, spec, template, window, board):
    origin = template.q0
    names = tuple(tape.joint_names)
    rows = controller_ticks(tape, spec, JointState(name=names, position=(origin,), velocity=(0.0,), effort=(0.0,)))
    different_observations = JointState(name=names, position=(origin + 0.03,), velocity=(-1.0,), effort=(2.0,))
    # WHY precompile the command stream: this particular spec evaluates feedforward on the plan and feedback on
    # the board. Changing every host observation must leave the complete stream equal, so replay keeps the loop.
    np.testing.assert_array_equal(rows, controller_ticks(tape, spec, different_observations))
    position, velocity, effort, kp, kd = rows.T
    if not np.isfinite(rows).all() or not (kp == kp[0]).all() or not (kd == kd[0]).all():
        raise ValueError("rack replay needs finite commands and fixed gains")
    pid = board.output_pid()
    np.testing.assert_allclose((kp[0], kd[0]), (pid.kp / (2 * np.pi) * spec.gain_scale,
                                               pid.kd / (2 * np.pi) * spec.damping_scale), atol=1e-12, rtol=0)
    hold_effort = Feedforward(spec.coefficients, damping_lag=0.0)(origin, 0.0, 0.0)
    full_position = np.full(len(template.t), origin)
    full_velocity = np.zeros(len(template.t))
    full_effort = np.full(len(template.t), hold_effort)
    full_position[window], full_velocity[window], full_effort[window] = position, velocity, effort
    full_position[window.stop:], full_effort[window.stop:] = position[-1], effort[-1]
    return replace(template, q_target=full_position, qd_target=full_velocity, ff_model_nm=full_effort,
                   ff_coulomb_nm=0.0, ff_viscous_nm_per_rad_s=0.0, kp_scale=spec.gain_scale,
                   kd_scale=spec.damping_scale, stop_q=None, qd_cmd=None)


def run_commands(commands, board, label):
    run = rack.as_sent(rack.synthetic_run(board, commands, name=label, kind="samples", bus_v=BUS_V))
    feedforward = (coulomb_feedforward_output_nm(run.run.semantics, board, run.qd_target)
                   + logged_feedforward_output_nm(run.run.arrays, board, rows=len(run.t)))
    command_stream = np.column_stack((run.t, run.q_target, run.qd_target, feedforward))
    return run, hashlib.sha256(command_stream.astype("<f8").tobytes()).hexdigest()


def replay_case(task, tape, window, twin, commands, board, label):
    run, command_sha = run_commands(commands, board, label)
    replay = twin.replay(run, 0.0)
    np.testing.assert_array_equal(replay.t, commands.t)
    if not (replay.mode[window] == 10).all():
        raise ValueError(f"{task} {label}: left position control")
    limiter_codes = rack.limiter_codes(twin.parameters, replay.tau[window], replay.qd[window], run.maximum_torque_nm)
    encoder_q = replay.q[window]
    row = {"task": task, "command_sha256": command_sha, "twin_encoder": task_scores(tape, encoder_q),
           "limiter_counts": pendulum_sim.limiter_counts(limiter_codes)}
    if replay.q_link is not None:
        load_q = replay.q_link[window]
        row["twin_load"] = task_scores(tape, load_q)
        twist = 2000 * TIP_LENGTH_M * np.sin((load_q - encoder_q) / 2)
        row["max_encoder_to_load_mm"] = float(np.max(np.abs(twist)))
    return row


def adopted_parameters(board):
    facts = rack.load_facts() or {}
    rest, origin, _ = rack.today_rest(STATION, (facts.get("stations") or {}).get(STATION))
    if rest is None:
        raise ValueError("the rack's frame-accept record must resolve the current CAN 11 gravity frame")
    # WHY use the accepted rest frame: simulate() does the same; twin_parameters() defaults to the former calibration frame.
    _, adopted = rack.twin_parameters(STATION, VERSION, bus_v=BUS_V, board=board, rest_rad=rest)
    return adopted, {"rest_rad": rest, "source": origin, "gravity_bottom_rad": adopted.gravity_bottom_rad}


def replay_batch(arguments):
    task, tape, window, variants, board, parameters, scene_dir = arguments
    twin = rack.joint_twin(board, parameters, scene_dir=scene_dir)
    return {label: replay_case(task, tape, window, twin, commands, board, label) for label, commands in variants.items()}


def rack_template(task, tape):
    plan = pendulum_sim.plan_step(tape.positions[:, 0], CONTROLLER, label=task)
    template = rack.commands_for(rack.runner_arguments(plan), plan["origin_rad"])
    first = np.searchsorted(template.t, template.prelude_s - 1e-9)
    window = slice(first, first + len(tape.t))
    np.testing.assert_allclose(template.t[window] - template.t[first], tape.t, atol=1e-12, rtol=0)
    matched_target(task, template.q_target[window], tape)
    return template, window


def development_cases(tapes, board, parameters, scene_dir, nominal, locked, workers):
    rows = {case: [] for case in ("historical_nominal", "historical_locked_gains", "identified_nominal", "identified_locked")}
    locked_commands = {}
    batches = []
    for task, tape in tapes.items():
        template, window = rack_template(task, tape)
        identified_nominal = identified_commands(tape, nominal, template, window, board)
        identified_locked = identified_commands(tape, locked, template, window, board)
        locked_commands[task] = (window, identified_locked)
        variants = {"historical_nominal": replace(template, kp_scale=1.0, kd_scale=1.0),
                    "historical_locked_gains": replace(template, kp_scale=locked.gain_scale, kd_scale=locked.damping_scale),
                    "identified_nominal": identified_nominal, "identified_locked": identified_locked}
        batches.append((task, tape, window, variants, board, parameters, scene_dir))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for batch in pool.map(replay_batch, batches):
            for case, row in batch.items():
                rows[case].append(row)
    previous = json.loads(Path(__file__).with_name("r18a-evidence.json").read_text())
    if summarize(rows["historical_nominal"], "twin_encoder") != previous["nominal_gain_twin_encoder"]:
        raise ValueError("historical nominal processing no longer reproduces the recorded stock runner measurements")
    return rows, locked_commands


def sealed_stress(tapes, frozen_commands, board, adopted, scene_dir, workers):
    # WHY these are plant inputs: the command streams were finalized with zero access to the synthetic gap or load histories.
    stress = replace(adopted, version="can11-r18a-synthetic-gap", backlash_rad=0.002,
                     rotor_inertia_fraction=0.022, output_friction_fraction=1.0)
    twin = rack.joint_twin(board, stress, scene_dir=scene_dir)
    batches = []
    for task, tape in tapes.items():
        window, commands = frozen_commands[task]
        batches.append((task, tape, window, {stress.version: commands}, board, stress, scene_dir))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = [batch[stress.version] for batch in pool.map(replay_batch, batches)]
    assumptions = {"synthetic": True, "total_gap_rad": stress.backlash_rad,
                   "rotor_inertia_fraction": stress.rotor_inertia_fraction,
                   "output_friction_fraction": stress.output_friction_fraction,
                   "mesh_stiffness_nm_rad": "stock rack wrapper default",
                   "physics_step_s": twin.physics_dt_s}
    return rows, assumptions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if digest(rack.version_path(STATION, VERSION)) != MODEL_SHA or digest(Path(rack.__file__)) != RACK_RUNNER_SHA:
        raise ValueError("the adopted rack model or runner changed")
    dataset = load_dataset(args.dataset)
    tapes = frozen_tapes(dataset)
    lock, nominal, locked = locked_specifications(dataset.info.rate_hz)
    board = rack.record_station(STATION)
    adopted, frame = adopted_parameters(board)
    if board.output_per_board != 1.0 or adopted.encoder_pll_hz is not None or adopted.friction_lugre is None:
        raise ValueError("the locked bridge expects the CAN 11 frame and adopted LuGre twin with direct encoder output")
    scene_dir = args.output.parent / "scenes"
    twin = rack.joint_twin(board, adopted, scene_dir=scene_dir)
    rows, commands = development_cases(tapes, board, adopted, scene_dir, nominal, locked, args.workers)
    print(f"Verified {len(tapes)} development targets against the native historical baseline", flush=True)
    stress, assumptions = sealed_stress(tapes, commands, board, adopted, scene_dir, args.workers)
    if [row["command_sha256"] for row in stress] != [row["command_sha256"] for row in rows["identified_locked"]]:
        raise ValueError("the synthetic stress did not replay the exact same locked command streams")
    worst_separation = max(stress, key=lambda row: row["max_encoder_to_load_mm"])
    report = {"dataset_manifest_sha256": DATASET_SHA, "split": "dev", "rung": RUNG, "host_rate_hz": dataset.info.rate_hz,
              "bus_voltage_v": BUS_V, "rack_revision": RACK_REV, "controller_revision": CONTROLLER_REV,
              "g2_controller": lock, "mujoco": mujoco.__version__, "model_version": VERSION, "model_sha256": MODEL_SHA,
              "model_delay_s": adopted.command_delay_s, "model_physics_step_s": twin.physics_dt_s, "model_frame": frame,
              "lugre_friction": asdict(adopted.friction_lugre),
              "adopted_lugre_encoder_scores": {case: summarize(cases, "twin_encoder") for case, cases in rows.items()},
              "synthetic_gap": {"assumptions": assumptions, "twin_encoder": summarize(stress, "twin_encoder"),
                                "twin_load": summarize(stress, "twin_load"),
                                "max_encoder_to_load_mm": worst_separation["max_encoder_to_load_mm"],
                                "max_encoder_to_load_task": worst_separation["task"]}}
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.output.with_suffix(".rows.json").write_text(json.dumps({**rows, "synthetic_gap": stress}, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
