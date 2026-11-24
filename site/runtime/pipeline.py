"""The page's driver: run one solution on one task with the real packages, and return what the page draws.

Runs unchanged in two places: in the browser (Pyodide; `mujoco` = runtime/mujoco_shim.py over MuJoCo's WASM build)
and natively (CPython; `mujoco` = the native 3.11.0 wheel). That is how the parity check compares them:

    python site/runtime/pipeline.py run --solution p6s --task workspace-dev-000 --out outputs/site/native.json

What it calls (all package source, unmodified):

- `run(...)`: the ruler's own one-task evaluation, `trajectory_tracking_agent.evaluate.run_task` (the solution's
  `build`, robot_controllers' host loop on the deployment's UR5e plant, the ruler's metrics and gates). The number on
  every score card is the one `run_task` returned. To draw *how* each number was computed the page also needs the
  4 kHz plant log `run_task` scored; a pass-through wrapper around `run_episode` keeps a reference to the log it
  returns (it changes no argument and no result). The arrays drawn are then derived with the ruler's own functions
  and constants (`metrics.tool_errors_m`, `metrics.stop_errors_mm`, `SATURATION_FRACTION`, ...), and each one is
  checked against the ruler's number (`checks`), so a drawing that disagreed with its card would say so.
- `run_robot_controllers_path(...)`: robot_controllers' own UR5e target under one population config (the phase-1
  runtime spike, kept as a second parity case that needs nothing from this repo).

No physics, no control law and no metric is written here.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from typing import Any

import numpy as np

RENDER_HZ = 60.0  # frames the 3D view gets (the plant itself runs at 4 kHz)
PLOT_HZ = 200.0  # 4 kHz plant signals are bucketed to this rate for the 2D plots (min/max per bucket kept)


# ── what ran ───────────────────────────────────────────────────────────────────────────────────────────────


def _runtime() -> dict[str, Any]:
    import mujoco
    import robot_controllers
    import robot_msgs

    try:
        from importlib.metadata import version

        versions = {name: version(name) for name in ("robot-controllers", "robot-msgs")}
    except Exception:  # noqa: BLE001
        versions = {}
    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "numpy": np.__version__,
        "mujoco": mujoco.__version__,
        "mujoco_binding": "wasm (runtime/mujoco_shim.py)" if hasattr(mujoco, "_mj") else "native",
        "robot_controllers": versions.get("robot-controllers", getattr(robot_controllers, "__version__", "")),
        "robot_msgs": versions.get("robot-msgs", getattr(robot_msgs, "__version__", "")),
    }


# ── 3D frames: MuJoCo's own forward kinematics on the bare UR5e ───────────────────────────────────────────


def _geoms() -> dict[str, Any]:
    """The UR5e's drawable geoms (the vendored model's capsules: type, size, body)."""
    from robot_controllers.bench.ur5e import load_model

    model = load_model()
    return {"type": model.geom_type.tolist(), "size": model.geom_size.tolist(), "body": model.geom_bodyid.tolist(),
            "count": int(model.ngeom), "bodies": int(model.nbody)}


def _frames(q_rows: np.ndarray) -> dict[str, list]:
    """Geom poses, body origins and the tool point for each row of joint angles (mj_kinematics): what three.js draws."""
    import mujoco
    from robot_controllers.bench.ur5e import TOOL_SITE, load_model

    model = load_model(frictionloss=False)
    data = mujoco.MjData(model)
    site = model.site(TOOL_SITE).id
    pos, mat, tool, bodies = [], [], [], []
    for row in q_rows:
        data.qpos[:] = row
        mujoco.mj_kinematics(model, data)
        pos.append(data.geom_xpos.copy())
        mat.append(data.geom_xmat.copy())
        tool.append(data.site_xpos[site].copy())
        bodies.append(data.xpos.copy())
    return {
        "geom_xpos": np.round(np.asarray(pos), 6).tolist(),
        "geom_xmat": np.round(np.asarray(mat), 6).tolist(),
        "tool": np.round(np.asarray(tool), 7).tolist(),
        "body_xpos": np.round(np.asarray(bodies), 6).tolist(),
    }


def _point_names() -> list[str]:
    """Names of the points the floor gate reads (deployment.link_points: every body but the world, then the tool)."""
    from robot_controllers.bench.ur5e import TOOL_SITE, load_model

    model = load_model(frictionloss=False)
    return [model.body(index).name for index in range(1, model.nbody)] + [TOOL_SITE]


def _buckets(t: np.ndarray, values: np.ndarray, rate_hz: float) -> dict[str, list]:
    """4 kHz rows -> PLOT_HZ buckets keeping each bucket's min and max (a spike between buckets is never hidden)."""
    if len(t) == 0:
        return {"t": [], "min": [], "max": []}
    width = max(1, int(round((t[1] - t[0] if len(t) > 1 else 1.0) ** -1 / rate_hz)))
    count = int(math.ceil(len(t) / width))
    pad = count * width - len(t)
    padded = np.concatenate([values, np.repeat(values[-1:], pad, axis=0)]) if pad else values
    shaped = padded.reshape(count, width, *values.shape[1:])
    return {"t": np.round(t[::width], 5).tolist(), "min": np.round(shaped.min(axis=1), 6).tolist(),
            "max": np.round(shaped.max(axis=1), 6).tolist()}


def _intervals(t: np.ndarray, mask: np.ndarray) -> list[list[float]]:
    """Runs of True in `mask` as [t_start, t_end] (the samples' own times)."""
    out, start = [], None
    for index, flag in enumerate(mask):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            out.append([float(t[start]), float(t[index - 1])])
            start = None
    if start is not None:
        out.append([float(t[start]), float(t[-1])])
    return out


def preview(task_id: str = "workspace-dev-000", split: str = "dev") -> dict[str, Any]:
    """The task's target alone (MuJoCo kinematics on the tape): what the 3D view shows before a run returns."""
    from trajectory_tracking_agent.ruler.dataset import tasks
    from trajectory_tracking_agent.ruler.deployment import deployment

    task = {item.id: item for item in tasks(split)}[task_id]
    dep = deployment("ur5e_alone")
    t = np.asarray(task.trajectory.t, dtype=float)
    q = np.asarray(task.trajectory.positions, dtype=float)
    frame_t = np.arange(0.0, t[-1] + 1e-9, 1.0 / RENDER_HZ)
    frame_q = np.array([np.interp(frame_t, t, q[:, j]) for j in range(q.shape[1])]).T
    return {"task": {"id": task.id, "kind": task.kind, "duration_s": float(t[-1])},
            "tool_target": np.round(dep.tool_position(q), 7).tolist(), "t": t.tolist(),
            "render": {"t": np.round(frame_t, 5).tolist(), "geoms": _geoms(), "target": _frames(frame_q)}}


# ── the page's run: the ruler's run_task, observed ────────────────────────────────────────────────────────


def run(solution_id: str = "p2", task_id: str = "workspace-dev-000", split: str = "dev", *,
        render: bool = True, pin_calibration: bool = False) -> dict[str, Any]:
    """`run_task(solution_id, task_id, split)` (the ruler's one-task evaluation, exactly as `tta evaluate` runs it) plus
    what the page draws. The ruler sends each command at its wake time (deployment.timing, include_compute=False).

    A solution whose build() calibrates its lookahead (robot_controllers' "calibrated" configs) also runs
    robot_controllers' own calibration episodes, which send at wake + the tick's measured CPU time: their result, and so
    the solution's, depends on the host (a browser's tick is slower and its clock resolves 0.1 ms). `pin_calibration`
    (the parity check only, on both sides alike) sends those episodes at their wake time too and clears the cached
    calibration before and after, so the comparison isolates the runtime from the host."""
    import robot_controllers.bench.loop as loop
    from trajectory_tracking_agent import evaluate
    from trajectory_tracking_agent.ruler import gates, metrics
    from trajectory_tracking_agent.ruler import deployment as deployment_module

    dep = deployment_module.deployment("ur5e_alone")
    captured: list[Any] = []
    original_run_episode = loop.run_episode

    def observed(spec: Any, rung: Any, *args: Any, **kwargs: Any) -> Any:
        # pass-through: keeps a reference to the log, changes nothing (unless pin_calibration, see above)
        if pin_calibration and rung.timing.include_compute:
            rung = dataclasses.replace(rung, timing=dataclasses.replace(rung.timing, include_compute=False))
        log = original_run_episode(spec, rung, *args, **kwargs)
        captured.append(log)
        return log

    from robot_controllers.bench.population import scenario_calibration

    loop.run_episode = observed
    if pin_calibration:
        scenario_calibration.cache_clear()
    wall = time.perf_counter()
    try:
        row = evaluate.run_task(solution_id, task_id, split)
    finally:
        loop.run_episode = original_run_episode
        if pin_calibration:
            scenario_calibration.cache_clear()
    wall_s = time.perf_counter() - wall

    arrays = row.pop("_arrays", None)
    compute = np.asarray(row.pop("compute_s", []), dtype=float)
    out: dict[str, Any] = {
        "runtime": _runtime(),
        "setup": {"solution": solution_id, "task": task_id, "split": split,
                  "include_compute": bool(dep.timing.include_compute), "pin_calibration": pin_calibration,
                  "episodes": len(captured)},
        "wall": {"run_task_s": wall_s},
        "row": row,
        "host_compute_ms": {"p50": float(1e3 * np.median(compute)) if compute.size else None,
                            "p95": float(1e3 * np.percentile(compute, 95)) if compute.size else None,
                            "ticks": int(compute.size)},
    }
    if arrays is None or not captured:
        out["explain"] = None
        return out
    log = captured[-1]  # the task's own episode (a calibrated config's calibration runs return first, inside build)

    t = np.asarray(arrays["t"], dtype=float)
    t_end = float(t[-1])
    target_tool = np.asarray(arrays["tool_target_xyz"], dtype=float)
    tool = np.asarray(arrays["tool_xyz"], dtype=float)
    moving = np.asarray(arrays["moving"], dtype=bool)
    stops = [(float(a), float(b)) for a, b in arrays["stops"]]
    errors_mm = 1e3 * metrics.tool_errors_m(target_tool, tool)
    stop_errors = [float(v) for v in metrics.stop_errors_mm(t, target_tool, tool, stops)] if stops else []

    # the 4 kHz plant rows the violation gates read (every sample up to the trajectory's end, as the ruler)
    plant_t = np.asarray(log.t, dtype=float)
    within = plant_t <= t_end + evaluate.GRID_TOLERANCE_S
    plant_t, plant_q = plant_t[within], np.asarray(log.q, dtype=float)[within]
    plant_qd, plant_tau = np.asarray(log.qd, dtype=float)[within], np.asarray(log.tau, dtype=float)[within]
    caps = np.asarray(dep.torque_cap_nm, dtype=float)
    saturated = np.abs(plant_tau) >= metrics.SATURATION_FRACTION * caps  # (N, 6), the ruler's constant
    q_lo, q_hi = np.asarray(dep.position_min_rad), np.asarray(dep.position_max_rad)
    qd_max = np.asarray(dep.velocity_max_rad_s)
    over_position = (plant_q < q_lo) | (plant_q > q_hi)
    over_velocity = np.abs(plant_qd) > metrics.VELOCITY_LIMIT_ALLOWANCE * qd_max
    points = dep.link_points(plant_q)  # (N, bodies + tool, 3): what the floor gate reads
    lowest_z = points[:, :, 2].min(axis=1)
    below = lowest_z < dep.floor_z_m
    # WHY the points that move apart: the base origin sits on the floor plane (z = 0) and the shoulder and upper-arm
    # origins stay at a fixed height whatever the joints do, so the lowest point overall never changes; what a viewer
    # wants to see is how close the moving arm comes (the gate itself reads every point, as the ruler does)
    heights = points[:, :, 2]
    varies = (np.ptp(heights, axis=0) > 1e-6) if len(heights) else np.zeros(points.shape[1], dtype=bool)
    if not varies.any():
        varies[:] = True
    moving_points = np.flatnonzero(varies)
    moving_z = heights[:, moving_points]
    lowest_moving = moving_z.min(axis=1)
    lowest_index = int(np.argmin(lowest_moving)) if len(lowest_moving) else 0
    lowest_point = int(moving_points[np.argmin(moving_z[lowest_index])]) if len(lowest_moving) else 0

    # utilisation per joint (%), what the saturation and limit explanations tint and plot
    mid, half = 0.5 * (q_hi + q_lo), 0.5 * (q_hi - q_lo)
    tau_use = 100.0 * np.abs(plant_tau) / caps
    position_use = 100.0 * np.abs(plant_q - mid) / half
    velocity_use = 100.0 * np.abs(plant_qd) / (metrics.VELOCITY_LIMIT_ALLOWANCE * qd_max)
    target_q = np.asarray(arrays["q_target"], dtype=float)

    kpis = row["kpis"]
    checks = {  # each drawing vs the ruler's number (a mismatch is shown on the page, never hidden)
        "tool_track_rms_mm": [row["objective"], float(np.sqrt(np.mean(errors_mm[moving] ** 2))) if moving.any() else None],
        "stop_error_max_mm": [kpis.get("stop_error_max_mm"), max(stop_errors) if stop_errors else 0.0],
        "saturation_share_pct": [kpis.get("saturation_share_pct"),
                                 100.0 * float(np.count_nonzero(saturated.any(axis=1))) / max(len(plant_t), 1)],
        "limit_violations": [kpis.get("limit_violations"),
                             int(np.count_nonzero((over_position | over_velocity).any(axis=1)))],
        "floor_clearance": [kpis.get("floor_clearance_violations", kpis.get("floor_clearance")),
                            int(np.count_nonzero(below))],
    }
    hold = metrics.HOLD_WINDOW_S
    stop_rows = []
    for (start, end), error in zip(stops, stop_errors, strict=False):
        window = (t >= end - hold - metrics.TIME_TOLERANCE_S) & (t <= end + metrics.TIME_TOLERANCE_S)
        stop_rows.append({"t0": start, "t1": end, "hold": [end - hold, end], "error_mm": error,
                          "mean_xyz": tool[window].mean(axis=0).tolist(), "target_xyz": target_tool[window][-1].tolist(),
                          "samples": int(np.count_nonzero(window))})
    out["explain"] = {
        "t": t.tolist(),
        "q_target": np.asarray(arrays["q_target"]).tolist(),
        "q": np.asarray(arrays["q"]).tolist(),
        "tool_target": target_tool.tolist(),
        "tool": tool.tolist(),
        "moving": moving.tolist(),
        "error_mm": np.round(errors_mm, 6).tolist(),
        "stops": stop_rows,
        "plant_rate_hz": float(dep.board.rate_hz),
        "plant_samples": int(len(plant_t)),
        "tau": _buckets(plant_t, plant_tau, PLOT_HZ),
        "tau_use_pct": _buckets(plant_t, tau_use, PLOT_HZ),
        "position_use_pct": _buckets(plant_t, position_use, PLOT_HZ),
        "velocity_use_pct": _buckets(plant_t, velocity_use, PLOT_HZ),
        "joint_error_deg": np.round(np.degrees(np.asarray(arrays["q"], dtype=float) - target_q), 7).tolist(),
        "point_names": _point_names(),
        "tau_cap": caps.tolist(),
        "saturation_fraction": metrics.SATURATION_FRACTION,
        "saturated_intervals": _intervals(plant_t, saturated.any(axis=1)),
        "saturated_per_joint": np.count_nonzero(saturated, axis=0).tolist(),
        "q_plant": _buckets(plant_t, plant_q, PLOT_HZ),
        "qd_plant": _buckets(plant_t, plant_qd, PLOT_HZ),
        "q_min": q_lo.tolist(), "q_max": q_hi.tolist(), "qd_max": qd_max.tolist(),
        "velocity_allowance": metrics.VELOCITY_LIMIT_ALLOWANCE,
        "limit_intervals": _intervals(plant_t, (over_position | over_velocity).any(axis=1)),
        "lowest_z": _buckets(plant_t, lowest_moving, PLOT_HZ),
        "lowest": {"t": float(plant_t[lowest_index]) if len(plant_t) else None,
                   "z": float(lowest_moving[lowest_index]) if len(plant_t) else None,
                   "point": lowest_point, "points": int(points.shape[1]),
                   "xyz": points[lowest_index, lowest_point].tolist() if len(plant_t) else None,
                   "fixed_points": {int(i): float(heights[0, i]) for i in np.flatnonzero(~varies)} if len(plant_t) else {},
                   "moving_points": moving_points.tolist()},
        "floor_z": dep.floor_z_m,
        "floor_intervals": _intervals(plant_t, below),
        "thresholds": {gate: list(gates.THRESHOLDS[gate]) for gate in gates.GATES},
        "checks": checks,
        "joint_names": list(dep.joint_names),
    }
    if render:
        step = max(1, int(round(float(dep.board.rate_hz) / RENDER_HZ)))
        frame_t = plant_t[::step]
        frame_q = plant_q[::step]
        frame_points = dep.link_points(frame_q)[:, moving_points, :]  # the points that move (see above)
        frame_lowest = frame_points[np.arange(len(frame_q)), np.argmin(frame_points[:, :, 2], axis=1)]
        frame_target_q = np.array([np.interp(frame_t, t, target_q[:, j]) for j in range(target_q.shape[1])]).T
        out["render"] = {"t": np.round(frame_t, 5).tolist(), "geoms": _geoms(),
                         "measured": _frames(frame_q), "target": _frames(frame_target_q),
                         "lowest": np.round(frame_lowest, 6).tolist()}
    return out


# ── the phase-1 spike: robot_controllers' own UR5e target ─────────────────────────────────────────────────


def run_robot_controllers_path(config_id: str = "P2", *, include_compute: bool = False, seed: int = 0) -> dict[str, Any]:
    """robot_controllers' own UR5e target (`ur5e/path@nominal`, its base scenario: 50 Hz, datasheet bus, 10 % model
    error) under population config `config_id`, through `run_episode`; `include_compute=False` makes it
    deterministic (see `run`). The tool error is per host tick at the send time (this repo's ruler is not used)."""
    from robot_controllers.bench.loop import run_episode
    from robot_controllers.bench.population import config_spec
    from robot_controllers.bench.scenarios import base_scenario
    from robot_controllers.bench.ur5e import UR5E_TRUTH

    wall = time.perf_counter()
    scenario = base_scenario("ur5e")
    spec = config_spec(config_id, scenario)
    rung = scenario.rung()
    rung = dataclasses.replace(rung, timing=dataclasses.replace(rung.timing, include_compute=include_compute))
    log = run_episode(spec, rung, seed=seed, plant_factory=scenario.plant_factory())
    wall_s = time.perf_counter() - wall
    dt = UR5E_TRUTH.physics_dt_s
    rows = np.clip(np.rint(np.asarray(log.sent_t) / dt).astype(int), 0, len(log.t) - 1)
    error_mm = 1e3 * np.linalg.norm(np.asarray(log.tool_pos)[rows] - np.asarray(log.ref_tool_pos), axis=1)
    return {
        "runtime": _runtime(),
        "setup": {"config": config_id, "scenario": scenario.id, "spec": spec.name, "seed": seed,
                  "include_compute": include_compute},
        "wall": {"episode_s": wall_s},
        "metrics": {"tick_tool_error_rms_mm": float(np.sqrt(np.mean(error_mm ** 2)))},
        "full": {"q": np.asarray(log.q).tolist(), "tool_pos": np.asarray(log.tool_pos).tolist()},
    }


# ── JSON over the boundary ─────────────────────────────────────────────────────────────────────────────────


def _clean(value: Any) -> Any:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    return value


def dumps(result: Any) -> str:
    """JSON for the page: a non-finite float becomes null (JSON has no NaN); floats round-trip exactly (repr)."""
    return json.dumps(_clean(result), allow_nan=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("what", choices=("run", "path"))
    parser.add_argument("--solution", default="p2")
    parser.add_argument("--task", default="workspace-dev-000")
    parser.add_argument("--config", default="P2")
    parser.add_argument("--deterministic", action="store_true", help="path only: send at the wake time")
    parser.add_argument("--pin-calibration", action="store_true", help="run only: calibration episodes at wake time")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.what == "run":
        result = run(args.solution, args.task, render=False, pin_calibration=args.pin_calibration)
    else:
        result = run_robot_controllers_path(args.config, include_compute=not args.deterministic)
    with open(args.out, "w") as handle:
        handle.write(dumps(result))
    summary = {key: result[key] for key in ("runtime", "setup", "wall") if key in result}
    summary["objective"] = result.get("row", {}).get("objective", result.get("metrics"))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
