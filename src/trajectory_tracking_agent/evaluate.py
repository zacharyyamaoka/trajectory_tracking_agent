"""`evaluate(solution_id, split)`: run a solution on every task of a split and score it with ruler v1 (OBJECTIVES §4).

    scorecard = evaluate("p7s", split="dev", workers=4)    # writes solutions/p7s/scorecard.json + one ledger row
    row = run_task("p7s", "workspace-dev-000")             # one task, in this process (what a worker runs)

One task (`run_task`):

1. The solution's controller is `build(task.trajectory, deployment)`; robot_controllers' host loop (`run_episode`) runs it
   on a fresh `Ur5ePlant` behind the deployment's boards, at 50 Hz over the datasheet bus (each command sent at its wake
   time: `Deployment.timing` says why), from the trajectory's first point, for the trajectory's duration plus one host
   period. Seed 0, no jitter: two runs of one solution are bit-identical. The controller is wrapped: each `tick` is timed (thread
   CPU, the solution's own `host_compute`), its command checked (a ServoCommand, every field that drives torque finite:
   a NaN `position` is robot_msgs' "no position target" and is allowed), and the task's wall-time box (10 x the
   trajectory's duration, CONTRACT §4) is checked before each tick; a breach raises inside the tick, which the host loop
   records as an abort and stops ticking.
2. **Measured** joints are the plant's joint positions (MuJoCo qpos, an ideal joint encoder) at the target's own sample
   instants (the tape's 100 Hz grid falls on the 4 kHz physics grid exactly). Both tool points come from those joint
   angles through the deployment's FK (`tool_position`), never from a simulator body pose (OBJECTIVES §4). WHY not the
   board's encoder reading: the moteus model quantises a UR5e joint to 2^14 counts (0.38 mrad, ~0.3 mm at the tool) and
   delays it 0.5 ms; that is the board's measurement error, a floor no controller can remove, not where the arm is.
3. The tracking metrics read that 100 Hz grid; the violation gates (`saturation_share_pct`, `limit_violations`,
   `floor_clearance`) read every 4 kHz physics sample up to the trajectory's end, so a spike between two target samples
   still counts.
4. `completed` holds only if: the build and every tick raised nothing, no command was non-finite, the host loop logged
   no abort and the physics did not diverge, the wall-time box held, the run reached the trajectory's end with finite
   joints, and it settled: every tool error over the trajectory's last 0.1 s (its final stop's hold window) <= 1 mm.

Then the gates (`ruler.gates`), the objective (median over tasks of `tool_track_rms_mm`) and the scorecard. Every
verdict fails closed: a task that crashed has no measurements, so it fails every gate.

A solution-agnostic run record per task goes to `outputs/runs/<solution>/<split>/<task>.json` (gitignored; schema
`RUN_RECORD_SCHEMA`): only the black box's outputs (the target, the logged joints and torques, the tool points, the
deployment's caps and limits, the metrics and gates), never anything from inside the solution.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import multiprocessing
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

import numpy as np
from robot_msgs import adopt

from trajectory_tracking_agent import files, ledger, population
from trajectory_tracking_agent.ruler import RULER_VERSION, gates, metrics
from trajectory_tracking_agent.ruler.dataset import REPO_ROOT, tasks
from trajectory_tracking_agent.ruler.deployment import deployment, package_versions

TIME_BOX_FACTOR = 10.0  # CONTRACT §4: a task over 10 x its trajectory duration in wall time fails `completed`
SETTLE_BAND_MM = 1.0  # `completed` settles within Zach's 1 mm tool band ...
SETTLE_WINDOW_S = metrics.HOLD_WINDOW_S  # ... over the trajectory's last 0.1 s
MAX_WORKERS = 4  # CONTRACT §5
GRID_TOLERANCE_S = 1e-9
RUNS_DIR = REPO_ROOT / "outputs" / "runs"
RUN_RECORD_SCHEMA = "tta.run_record/1"
TORQUE_FIELDS = ("velocity", "feedforward_effort", "stiffness", "damping", "max_effort")

__all__ = ["RUN_RECORD_SCHEMA", "TIME_BOX_FACTOR", "evaluate", "run_task"]


class TimeBoxExceeded(RuntimeError):
    """The task ran past TIME_BOX_FACTOR x its trajectory's duration in wall time."""


class WorkerLost(RuntimeError):
    """A worker process died part-way through a split: the machine ended it (the OOM killer, a SIGTERM), not the
    controller. Nothing is scored; evaluate again (the score repeats bit for bit)."""


class NonFiniteCommand(RuntimeError):
    """A command field that drives torque was NaN or infinite."""


# ── the controller as the host loop sees it ─────────────────────────────────────────────────────────────────


class _Watched:
    """The solution's controller behind the ruler's checks: every attribute but `tick` is the controller's own."""

    def __init__(self, inner: Any, joint_names: Sequence[str], deadline: float, limit_s: float) -> None:
        self._inner = inner
        self._joints = tuple(joint_names)
        self._deadline = deadline
        self._limit_s = limit_s
        self.compute_s: list[float] = []
        self.failure: str | None = None

    @property
    def status(self) -> str:
        return getattr(self._inner, "status", "running")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def tick(self, state: Any, dt: float) -> Any:
        from robot_msgs.control import ServoCommand

        if time.perf_counter() > self._deadline:
            self.failure = f"time box: wall time passed {self._limit_s:.1f} s (10 x the trajectory's duration)"
            raise TimeBoxExceeded(self.failure)
        start = time.thread_time_ns()
        try:
            result = self._inner.tick(state, dt)
        except Exception as error:
            self.failure = f"tick raised {type(error).__name__}: {error}"
            raise
        self.compute_s.append((time.thread_time_ns() - start) * 1e-9)
        try:
            command, defines = result
        except (TypeError, ValueError):
            self.failure = f"tick returned {type(result).__name__}, not (ServoCommand, defines)"
            raise TypeError(self.failure) from None
        if not isinstance(command, ServoCommand):
            self.failure = f"tick returned a {type(command).__name__}, not a robot_msgs ServoCommand"
            raise TypeError(self.failure)
        missing = [name for name in self._joints if name not in tuple(command.name)]
        if missing:
            self.failure = f"the command names no {missing}"
            raise ValueError(self.failure)
        position = np.asarray(command.position, dtype=float)
        bad = ["position"] if np.isinf(position).any() else []
        for field in TORQUE_FIELDS:
            values = getattr(command, field)
            if values is not None and not np.isfinite(np.asarray(values, dtype=float)).all():
                bad.append(field)
        if bad:
            self.failure = f"non-finite command field(s) {bad} at dt {dt:.4f} s"
            raise NonFiniteCommand(self.failure)
        return command, defines


class _SolutionSpec:
    """What `run_episode` builds a controller from (a robot_controllers ControllerSpec's `name` and `build`)."""

    def __init__(self, solution_id: str, build: Any, dep: Any, deadline: float, limit_s: float) -> None:
        self.name = solution_id
        self._build = build
        self._deployment = dep
        self._deadline = deadline
        self._limit_s = limit_s
        self.watched: _Watched | None = None
        self.failure: str | None = None

    def build(self, message: Any, **_overrides: Any) -> _Watched:
        try:
            controller = self._build(_controller_trajectory(message), self._deployment)
        except Exception as error:
            self.failure = f"build raised {type(error).__name__}: {error}"
            raise
        if not callable(getattr(controller, "tick", None)):
            self.failure = f"build returned a {type(controller).__name__} with no tick(state, dt)"
            raise TypeError(self.failure)
        self.watched = _Watched(controller, self._deployment.joint_names, self._deadline, self._limit_s)
        return self.watched


def _controller_trajectory(trajectory: Any) -> Any:
    # WHY: NumPy lets the owner of a read-only array re-enable writes. Give the controller its own message backed
    # by immutable bytes so it cannot edit the cached tape the simulator and scoring code use as their reference.
    def immutable(array: np.ndarray) -> np.ndarray:
        return adopt(np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape))

    fields = {name: immutable(trajectory[name]) for name in trajectory.sample_names if name not in trajectory.channels}
    channels = {name: immutable(array) for name, array in trajectory.channels.items()}
    return trajectory.replace(t=immutable(trajectory.t), channels=channels, **fields)


class _TaskScript:
    """The rung's input script: the task's trajectory at t = 0, nothing after (a solution cannot be replanned)."""

    def __init__(self, trajectory: Any) -> None:
        self.trajectory = trajectory

    def __call__(self, start_q: np.ndarray) -> list[tuple[float, Any]]:
        return [(0.0, self.trajectory)]

    @property
    def duration_s(self) -> float:
        return float(self.trajectory.t[-1])


def _rung(task: Any, dep: Any) -> Any:
    from robot_controllers.bench.types import Rung, Scene
    from robot_controllers.registry import JOINT_TRAJECTORY

    trajectory = task.trajectory
    return Rung(
        id=task.id,
        title=f"{task.id} ({task.kind})",
        box=JOINT_TRAJECTORY,
        family="free_space",
        description=f"ruler {RULER_VERSION}: {task.kind} on {dep.name}, speed 1.0, from its first point",
        duration_s=float(trajectory.t[-1]) + dep.host_period_s,
        inputs=_TaskScript(trajectory),
        scene=Scene(start_q=tuple(float(v) for v in trajectory.positions[0])),
        timing=dep.timing,
        gates=(),
        objective="tool_track_rms_mm",
        plant=dep.arm,
    )


# ── one task ────────────────────────────────────────────────────────────────────────────────────────────────


def _clean(value: Any) -> Any:
    """JSON-safe: NaN / inf -> None, numpy -> Python."""
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def _failed_row(task: Any, why: str, wall_s: float = math.nan) -> dict[str, Any]:
    kpis: dict[str, Any] = {"completed": False, "stop_error_max_mm": None, "saturation_share_pct": None,
                            "limit_violations": None, "floor_clearance_violations": None}
    return {
        "task": task.id,
        "kind": task.kind,
        "duration_s": task.duration_s,
        "objective": None,
        "kpis": kpis,
        "diagnostics": {},
        "verdicts": gates.gate_verdicts(kpis),
        "notes": [why],
        "wall_time_s": _clean(wall_s),
        "compute_s": [],
    }


def run_task(
    solution_id: str,
    task_id: str,
    split: str = "dev",
    *,
    record_dir: Path | None = None,
) -> dict[str, Any]:
    """Run `solution_id` on one task in this process and score it; a JSON-safe task row (see the module docstring)."""
    from robot_controllers.bench.loop import run_episode

    task = {item.id: item for item in tasks(split)}[task_id]
    dep = deployment("ur5e_alone")
    wall_start = time.perf_counter()
    trajectory = task.trajectory
    t_end = float(trajectory.t[-1])
    limit_s = TIME_BOX_FACTOR * t_end
    try:
        build = population.load_build(solution_id)
    except Exception as error:  # noqa: BLE001 - a solution that cannot load is scored, not raised
        return _failed_row(task, f"load: {type(error).__name__}: {error}", time.perf_counter() - wall_start)
    spec = _SolutionSpec(solution_id, build, dep, wall_start + limit_s, limit_s)
    try:
        log = run_episode(spec, _rung(task, dep), seed=0, plant_factory=dep.plant)
    except Exception as error:  # noqa: BLE001 - the build (or the run) failing is a finding
        why = spec.failure or f"run: {type(error).__name__}: {error}"
        return _failed_row(task, why, time.perf_counter() - wall_start)
    episode_wall_s = time.perf_counter() - wall_start
    row = _score(task, dep, log, spec, episode_wall_s, limit_s)
    row["wall_time_s"] = _clean(time.perf_counter() - wall_start)
    if record_dir is not None:
        _write_record(Path(record_dir), solution_id, split, task, dep, log, row)
    return row


def _score(task: Any, dep: Any, log: Any, spec: _SolutionSpec, episode_wall_s: float, limit_s: float) -> dict[str, Any]:
    trajectory = task.trajectory
    t = np.asarray(trajectory.t, dtype=float)
    t_end = float(t[-1])
    notes: list[str] = []
    watched = spec.watched
    physics_dt = 1.0 / float(dep.board.rate_hz)

    # the target's instants on the physics grid
    index = np.rint(t / physics_dt).astype(np.int64)
    on_grid = np.abs(index * physics_dt - t) <= GRID_TOLERANCE_S + 1e-12 * t
    reached = len(log.t) > index[-1] and float(log.t[-1]) >= t_end - GRID_TOLERANCE_S
    valid = bool(on_grid.all()) and reached
    if not valid:
        notes.append("the run did not reach the trajectory's end on the physics grid" if on_grid.all()
                     else "the target's instants are not on the 4 kHz physics grid")
        q = np.full_like(np.asarray(trajectory.positions, dtype=float), np.nan)
        qd = np.full_like(q, np.nan)
    else:
        q = np.asarray(log.q, dtype=float)[index]
        qd = np.asarray(log.qd, dtype=float)[index]
    target_q = np.asarray(trajectory.positions, dtype=float)
    target_qd = np.asarray(trajectory.velocities, dtype=float)
    target_tool = np.asarray(dep.tool_position(target_q), dtype=float)
    measured_tool = np.full_like(target_tool, np.nan)
    finite_rows = np.isfinite(q).all(axis=1)
    if finite_rows.any():
        measured_tool[finite_rows] = dep.tool_position(q[finite_rows])

    moving = metrics.moving_mask(t, target_tool, target_qd)
    stops = metrics.stop_windows(t, moving)
    objective = metrics.tool_track_rms_mm(target_tool, measured_tool, moving)

    # every physics sample up to the trajectory's end
    within = np.asarray(log.t, dtype=float) <= t_end + GRID_TOLERANCE_S
    plant_t = np.asarray(log.t, dtype=float)[within]
    plant_q = np.asarray(log.q, dtype=float)[within]
    plant_qd = np.asarray(log.qd, dtype=float)[within]
    plant_tau = np.asarray(log.tau, dtype=float)[within]
    link_z = dep.link_points(plant_q)[:, :, 2] if len(plant_q) else np.full((1, 1), np.nan)

    kpis: dict[str, Any] = {
        "stop_error_max_mm": metrics.stop_error_max_mm(t, target_tool, measured_tool, stops),
        "saturation_share_pct": metrics.saturation_share_pct(plant_tau, dep.torque_cap_nm),
        "limit_violations": metrics.limit_violations(
            plant_q, plant_qd, dep.position_min_rad, dep.position_max_rad, dep.velocity_max_rad_s
        ),
        "floor_clearance_violations": metrics.floor_clearance_violations(link_z, dep.floor_z_m),
    }

    # completed (OBJECTIVES §4): no exception, no NaN command, reaches the end, settles
    failures = []
    if spec.failure:
        failures.append(spec.failure)
    if watched is not None and watched.failure and watched.failure != spec.failure:
        failures.append(watched.failure)
    for event in log.events:
        if event.get("kind") == "abort":
            failures.append(f"abort at {float(event['t']):.3f} s: {event.get('why')}")
        elif event.get("kind") == "diverged":
            failures.append(f"physics diverged at {float(event['t']):.3f} s")
    if episode_wall_s > limit_s:
        failures.append(f"time box: the run took {episode_wall_s:.1f} s, over {limit_s:.1f} s")
    if not valid or not np.isfinite(q).all():
        failures.append("did not reach the trajectory's end with finite joints")
    errors_mm = 1e3 * metrics.tool_errors_m(target_tool, measured_tool)
    final = t >= t_end - SETTLE_WINDOW_S - GRID_TOLERANCE_S
    settle_max_mm = float(np.max(errors_mm[final])) if final.any() else math.nan
    if not (settle_max_mm <= SETTLE_BAND_MM):
        failures.append(f"did not settle: tool error up to {settle_max_mm:.3f} mm over the last 0.1 s (band 1 mm)")
    kpis["completed"] = not failures
    notes.extend(failures)
    verdicts = gates.gate_verdicts(kpis)

    compute = np.asarray(watched.compute_s if watched is not None else [], dtype=float)
    watchdogs = sum(1 for event in log.events if event.get("kind") == "watchdog")
    if watchdogs:
        notes.append(f"{watchdogs} board watchdog entries (a joint went 0.25 s without a command)")
    diagnostics = {
        "tool_track_max_mm": metrics.tool_track_max_mm(target_tool, measured_tool, moving),
        "joint_track_rms_deg": metrics.joint_track_rms_deg(target_q, q, moving),
        "tool_lag_ms": _lag_ms(t, target_q, q, dep.joint_names),
        "stop_error_mm": metrics.stop_error_median_mm(t, target_tool, measured_tool, stops),
        "saturation_share_pct": kpis["saturation_share_pct"],
        "energy_j": metrics.energy_j(plant_t, plant_tau, plant_qd),
        "tool_jerk_rms_m_s3": metrics.tool_jerk_rms_m_s3(t, measured_tool, moving),
        "host_compute_ms_p95": float(1e3 * np.percentile(compute, 95)) if compute.size else math.nan,
        "settle_error_max_mm": settle_max_mm,
        "stops": len(stops),
        "moving_samples": int(np.count_nonzero(moving)),
        "ticks": int(compute.size),
        "watchdog_entries": watchdogs,
    }
    return {
        "task": task.id,
        "kind": task.kind,
        "duration_s": t_end,
        "objective": _clean(objective),
        "kpis": _clean(kpis),
        "diagnostics": _clean(diagnostics),
        "verdicts": verdicts,
        "notes": notes,
        "wall_time_s": _clean(episode_wall_s),
        "compute_s": [float(v) for v in compute],
        "_arrays": {
            "t": t, "q_target": target_q, "qd_target": target_qd, "q": q, "qd": qd, "index": index if valid else None,
            "tool_target_xyz": target_tool, "tool_xyz": measured_tool, "moving": moving, "stops": stops,
        },
    }  # fmt: skip


def _lag_ms(t: np.ndarray, target_q: np.ndarray, q: np.ndarray, joint_names: Sequence[str]) -> float:
    """How late the run is behind the target (ms, + = behind): robot_msgs.compare.estimate_time_offset on joints."""
    if not np.isfinite(q).all():
        return math.nan
    from robot_msgs.compare import estimate_time_offset
    from robot_msgs.trajectory import JointTrajectory

    try:
        target = JointTrajectory(t=t, joint_names=tuple(joint_names), positions=target_q)
        measured = JointTrajectory(t=t, joint_names=tuple(joint_names), positions=q)
        return 1e3 * float(estimate_time_offset(target, measured).offset_s)
    except (ValueError, TypeError):
        return math.nan


# ── the run record: what a viewer reads (solution-agnostic) ─────────────────────────────────────────────────


def _rounded(array: Any, digits: int = 7) -> Any:
    values = np.asarray(array, dtype=float)
    return _clean(np.round(values, digits))


def _write_record(
    out_dir: Path, solution_id: str, split: str, task: Any, dep: Any, log: Any, row: dict[str, Any]
) -> Path:
    arrays = row["_arrays"]
    index = arrays["index"]
    tau = np.asarray(log.tau, dtype=float)[index] if index is not None else np.full_like(arrays["q"], np.nan)
    record = {
        "schema": RUN_RECORD_SCHEMA,
        "ruler": RULER_VERSION,
        "deployment": dep.name,
        "split": split,
        "task": task.id,
        "kind": task.kind,
        "solution": solution_id,
        "joint_names": list(dep.joint_names),
        "tau_cap": list(dep.torque_cap_nm),
        "q_min": list(dep.position_min_rad),
        "q_max": list(dep.position_max_rad),
        "qd_max": list(dep.velocity_max_rad_s),
        "floor_z": dep.floor_z_m,
        "units": {"t": "s", "q": "rad", "qd": "rad/s", "tau": "N·m", "xyz": "m"},
        "t": _rounded(arrays["t"], 6),
        "q_target": _rounded(arrays["q_target"]),
        "qd_target": _rounded(arrays["qd_target"]),
        "q": _rounded(arrays["q"]),
        "qd": _rounded(arrays["qd"]),
        "tau": _rounded(tau, 6),
        "tool_target_xyz": _rounded(arrays["tool_target_xyz"]),
        "tool_xyz": _rounded(arrays["tool_xyz"]),
        "moving": [bool(v) for v in arrays["moving"]],
        "stops": [[float(a), float(b)] for a, b in arrays["stops"]],
        "host_t": _rounded(log.sent_t, 6),
        "tau_command_ff": _rounded(log.cmd_feedforward, 6),
        "metrics": {"tool_track_rms_mm": row["objective"], **row["kpis"], **row["diagnostics"]},
        "gates": row["verdicts"],
        "notes": row["notes"],
        "grids": {"t": "the target's own samples (100 Hz); tau is the applied torque at those instants",
                  "violation_gates": "saturation, limits and floor are computed on every 4 kHz physics sample",
                  "host_t": "when each command went on the bus (50 Hz host ticks)"},
    }  # fmt: skip
    path = out_dir / solution_id / split / f"{task.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    files.write_text(path, json.dumps(record, separators=(",", ":"), allow_nan=False))
    return path


# ── a whole split ───────────────────────────────────────────────────────────────────────────────────────────


def _job(arguments: tuple[str, str, str, str | None]) -> dict[str, Any]:
    solution_id, task_id, split, record_dir = arguments
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    try:
        row = run_task(solution_id, task_id, split, record_dir=Path(record_dir) if record_dir else None)
    except Exception as error:  # noqa: BLE001 - a crash in the ruler's own path is still a failed task, loudly
        task = {item.id: item for item in tasks(split)}[task_id]
        row = _failed_row(task, f"evaluator: {type(error).__name__}: {error}")
    row.pop("_arrays", None)
    return row


def _run_tasks(
    solution_id: str, split: str, task_list: Sequence[Any], workers: int, record_dir: Path | None, job: Any = None
) -> list[dict]:
    job = job or _job
    jobs = [(solution_id, task.id, split, str(record_dir) if record_dir else None) for task in task_list]
    if workers == 1:
        return [job(arguments) for arguments in jobs]
    # WHY a backstop deadline on top of the in-tick time box: a tick that never returns is never checked. Generous
    # (every task's own box, run one after another), then the workers are killed and the rest fail `completed`.
    budget_s = TIME_BOX_FACTOR * sum(task.duration_s for task in task_list) + 120.0
    deadline = time.monotonic() + budget_s
    rows = []
    # WHY ProcessPoolExecutor and not multiprocessing.Pool (2026-11-25, measured under 8 % free memory): Pool replaces
    # a worker the machine kills without a word, so the lost task waited out the whole backstop deadline and was then
    # scored a failed `completed`, the machine's kill written to the ledger as the controller's failure. The executor
    # breaks at once, and a lost worker is WorkerLost: no score, and the run is evaluated again.
    executor = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("forkserver"))
    try:
        pending = [executor.submit(job, arguments) for arguments in jobs]
        for task, future in zip(task_list, pending, strict=True):
            try:
                rows.append(future.result(timeout=max(0.0, deadline - time.monotonic())))
            except TimeoutError:
                rows.append(_failed_row(task, f"time box: no result within the evaluation's {budget_s:.0f} s budget"))
            except BrokenProcessPool as error:
                raise WorkerLost(
                    f"a worker process died while {solution_id} ran on {split} (first unfinished task {task.id}): the "
                    "machine ended it (the OOM killer or a SIGTERM), so nothing is scored. Evaluate it again; the score "
                    "repeats bit for bit."
                ) from error
            except Exception as error:  # noqa: BLE001
                rows.append(_failed_row(task, f"worker: {type(error).__name__}: {error}"))
    finally:
        _stop(executor)
    return rows


def _stop(executor: ProcessPoolExecutor) -> None:
    """Kill every worker, idle or stuck in a tick that never returns (what Pool.terminate did), then free the pool."""
    processes = list((getattr(executor, "_processes", None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        if process.is_alive():
            process.kill()
    for process in processes:
        process.join(timeout=10)


def _git_commit() -> dict[str, Any]:
    try:
        commit = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                                timeout=10, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", "src", "datasets"],
                                    capture_output=True, text=True, timeout=10, check=True).stdout.strip())
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def _median(values: Sequence[Any]) -> float:
    numbers = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(np.median(numbers)) if numbers and len(numbers) == len(values) else math.nan


def _aggregate(rows: Sequence[Mapping[str, Any]], compute: np.ndarray) -> dict[str, Any]:
    """The solution's diagnostics over tasks (OBJECTIVES §4), each named for how it aggregates. NaN when any task's is."""

    def column(name: str) -> list[Any]:
        return [row["diagnostics"].get(name) if row["diagnostics"] else None for row in rows]

    def worst(name: str) -> float:
        values = column(name)
        if not values or any(v is None for v in values):
            return math.nan
        return float(max(values))

    energy = column("energy_j")
    return {
        "tool_track_max_mm": worst("tool_track_max_mm"),
        "joint_track_rms_deg": _median(column("joint_track_rms_deg")),
        "tool_lag_ms": _median(column("tool_lag_ms")),
        "stop_error_mm": _median(column("stop_error_mm")),
        "saturation_share_pct": worst("saturation_share_pct"),
        "energy_j": float(sum(energy)) if energy and all(v is not None for v in energy) else math.nan,
        "tool_jerk_rms_m_s3": _median(column("tool_jerk_rms_m_s3")),
        "host_compute_ms_p95": float(1e3 * np.percentile(compute, 95)) if compute.size else math.nan,
        "wall_time_s": float(sum(row["wall_time_s"] or 0.0 for row in rows)),
        "aggregation": "tool_track_max_mm, saturation_share_pct: worst task; energy_j, wall_time_s: sum over tasks; "
        "host_compute_ms_p95: over every tick of every task; the rest: median over tasks",
    }


def evaluate(
    solution_id: str,
    split: str = "dev",
    *,
    workers: int = 1,
    write: bool = True,
    records: bool = True,
    task_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Score `solution_id` on `split` and return its scorecard. With `write` (the default, `tta evaluate`): the scorecard
    goes to `solutions/<id>/scorecard.json` (dev) or `scorecard_holdout.json` (holdout) and one row to `ledger.jsonl`.
    `task_ids` scores a subset (never written: a partial split is not a score)."""
    if not 1 <= int(workers) <= MAX_WORKERS:
        raise ValueError(f"workers must be 1..{MAX_WORKERS} (CONTRACT §5), got {workers}")
    record = population.meta(solution_id)
    sources = population.check_source(population.solution_dir(solution_id) / "solution.py")
    if sources:
        raise PermissionError("the solution may not run:\n- " + "\n- ".join(sources))
    task_list = list(tasks(split))
    if task_ids is not None:
        wanted = set(task_ids)
        task_list = [task for task in task_list if task.id in wanted]
        if len(task_list) != len(wanted):
            raise KeyError(f"unknown task ids for {split}: {sorted(wanted - {t.id for t in task_list})}")
        write = False
    start = time.perf_counter()
    started = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    record_dir = RUNS_DIR if records else None
    rows = _run_tasks(solution_id, split, task_list, int(workers), record_dir)
    elapsed = time.perf_counter() - start
    compute = np.asarray([v for row in rows for v in row.pop("compute_s", [])], dtype=float)
    verdicts = [row["verdicts"] for row in rows]
    objective = gates.objective([row["objective"] if row["objective"] is not None else math.nan for row in rows])
    failed = {gate: sum(1 for v in verdicts if v.get(gate) is not True) for gate in gates.GATES}
    diagnostics = _aggregate(rows, compute)
    commit = _git_commit()
    scorecard = {
        "ruler": RULER_VERSION,
        "solution": solution_id,
        "split": split,
        "objective": objective,
        "objective_name": "tool_track_rms_mm (median over tasks)",
        "admissible": gates.admissible(verdicts),
        "gate_pass_rate": gates.gate_pass_rate(verdicts),
        "gates": {
            gate: {
                "op": gates.THRESHOLDS[gate][0],
                "threshold": gates.THRESHOLDS[gate][1],
                "failed_tasks": [row["task"] for row in rows if row["verdicts"].get(gate) is not True],
            }
            for gate in gates.GATES
        },
        "failed_gates": failed,
        "diagnostics": diagnostics,
        "tasks": rows,
        "deployment": deployment("ur5e_alone").record(),
        "dataset": {"name": "ur5e_alone/workspace/v2", "split": split, "tasks": len(rows), "speed": 1.0},
        "code": {
            "solution_sha256": population.solution_sha256(solution_id),
            "repo_commit": commit["commit"],
            "repo_dirty": commit["dirty"],
            **package_versions(),
        },
        "evaluated": started,
        "wall_time_s": elapsed,
        "workers": int(workers),
    }
    scorecard = _clean(scorecard)
    if write:
        name = "scorecard.json" if split == "dev" else f"scorecard_{split}.json"
        path = population.solution_dir(solution_id) / name
        files.write_text(path, json.dumps(scorecard, indent=1, allow_nan=False) + "\n")
        ledger.append({
            "t": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "solution": solution_id,
            "parent": record.get("parent"),
            "split": split,
            "ruler": RULER_VERSION,
            "objective": scorecard["objective"],
            "admissible": scorecard["admissible"],
            "gate_pass_rate": scorecard["gate_pass_rate"],
            "failed_gates": failed,
            "diagnostics": {k: v for k, v in scorecard["diagnostics"].items() if k != "aggregation"},
            "wall_time_s": scorecard["wall_time_s"],
            "repo_commit": commit["commit"],
            "proposed_by": record.get("proposed_by"),
            "change": record.get("change"),
            "task_objectives": {row["task"]: row["objective"] for row in scorecard["tasks"]},
        })  # fmt: skip
    return scorecard
