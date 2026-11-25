"""W3 loaded check: does tracking survive a Robotiq 2F-85 and a 60 g object on the UR5e's flange? (off-score)

    uv run python experiments/w3_loaded_ur5e_2f85/loaded_check.py            # every case below -> results.json
    uv run python experiments/w3_loaded_ur5e_2f85/loaded_check.py --table    # print README's tables from results.json

WHY (W3, 2026-11-25): ruler v1 scores the bare UR5e (`Ur5ePlant`, payload 0 kg). p5s-pass3's 0.031 mm says nothing about
the arm carrying the tool it will pick with. This measures it, as a labelled side check: the frozen ruler, its dataset,
its score and every solution stay untouched. Nothing here is a solution or a ledger row.

What is loaded (both point masses, children of wrist_3, so the vendored links' own inertials stay as they are):

- **Gripper 0.925 kg** (robotparts `parts/robotiq-2f-85/part.py` `mass`: Robotiq manual Table 5-1, 925 g with coupling)
  at **39.55 mm** out along the tool axis from the flange face: the open hand's centre of mass in robotparts'
  `files/2f-85.xml` (MuJoCo Menagerie robotiq_2f85_v4, every mass Menagerie's, 0.900 kg, coupling face at z = 0),
  computed with MuJoCo at the open pose (0.07 mm off axis, ignored). Robotiq's own centre-of-mass table is not in
  robotparts (`com_z_m: None`), so this is Menagerie's mass distribution with the maker's total mass. The hand's own
  rotational inertia about its centre (<= 1.05e-3 kg m^2, the same model) is left out as asked ("a point mass"): it is
  1.3 % of one wrist joint's armature (0.08 kg m^2).
- **Object 0.06 kg** at the dataset's TCP, flange + 0.144 m along the same axis (the tapes' `tcp_pos`; checked to 5e-16 m
  against this model's FK). Robotiq states its TCP at 174 mm; the tapes carry 144 mm, so the object sits there.

Total 0.985 kg on wrist_3. In the plain loaded cases the controller's models are never told (the honest test):
p5s-pass3 keeps the given `rigid_body` model (no payload, 10 % link error) and its model.json identified on the bare arm;
p1 has no model. Labelled cases give p5s-pass3's feed-forward part of the load exactly (the arm's links still 10 %
wrong), the one-line change a solution would make (`feedforward = payload-aware rigid_body`), injected here without
editing it: `+model-knows` the whole payload; `+model-knows-gripper` the gripper only, the object unmodelled (what a
real picker runs: the gripper is fixed and known, each object's weight is not), with the 60 g object and with a 0.3 kg
one (HEAVY_OBJECT_KG). A case is (solution, `plant_load`, `model_load`, splits); a load is a name in LOADS. The break
sweep (`run_sweep`, dev, summaries only) runs that gripper-known case at each object mass in SWEEP_OBJECT_KG.

How a task runs: exactly the ruler's run (`evaluate._rung`, `run_episode`, seed 0, the deployment's boards, bus and
timing; scored by `evaluate._score`, the ruler's own metrics and gates) with two changes: the plant's MjModel is the
loaded one (`LoadedUr5ePlant._stopped_model`, the hook a plant's reset passes its model through), and the episode runs
EXTRA_HOLD_S past the trajectory's end so the settle time can be measured. The ruler's metrics read only samples up to
the trajectory's end, so the extra hold changes no ruler number: the bare case must reproduce each solution's committed
scorecard task by task, bit for bit, or the script stops (`--allow-mismatch` to override).

Added here (not the ruler's): `settle_s`, the first instant after which the tool stays within SETTLE_BAND_MM of the
trajectory's final target until EXTRA_HOLD_S after the end (None = not settled by then), on the ruler's tool point and
on the TCP; `target_settle_s`, the same instant for the target itself (what a perfect tracker achieves; every tape ends
with a hold, so it is before the commanded end); `overrun_s` = settle_s - target_settle_s; the TCP
(flange + 0.144 m) tracking RMS and stop errors with the ruler's definitions; each joint's peak |torque| / cap.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import json
import math
import sys
import time
import types
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results.json"

GRIPPER_KG = 0.925  # robotparts robotiq-2f-85 `mass` (Robotiq manual Table 5-1)
GRIPPER_COM_M = 0.0395523  # open-hand centre of mass along the tool axis, robotparts files/2f-85.xml (Menagerie v4)
OBJECT_KG = 0.06
TCP_OFFSET_M = 0.144  # the dataset's TCP: flange + 0.144 m along the tool axis
FLANGE_Y_M = 0.1  # the tool site (flange face) is 0.1 m along wrist_3's +y (the tool axis)
EXTRA_HOLD_S = 2.0  # run this long past the trajectory's end to measure the settle time
SETTLE_BAND_MM = 1.0  # Zach's 1 mm tool band (the ruler's stop gate and `completed` settle band)
SETTLE_GRID_S = 0.001  # settle time resolution: every 4th 4 kHz physics sample
PAYLOAD_INERTIA = "1e-9 1e-9 1e-9"  # a point mass (robot_controllers' payload hook does the same)
HEAVY_OBJECT_KG = 0.3  # the heavier item: how heavy before the stop gate breaks with the gripper known

# A load is the point masses on wrist_3 (load_loaded_model's arguments); None = the bare arm (the ruler's plant)
LOADS: dict[str, dict[str, float]] = {
    "gripper+object": {"gripper_kg": GRIPPER_KG, "object_kg": OBJECT_KG},
    "gripper": {"gripper_kg": GRIPPER_KG, "object_kg": 0.0},
    "gripper+0.3kg-object": {"gripper_kg": GRIPPER_KG, "object_kg": HEAVY_OBJECT_KG},
}
# The break sweep (dev, summaries only): the same case as `0.3kg-object+model-knows-gripper` (gripper known, object
# not) at each object mass, to find how heavy an item can be before the stop gate breaks
SWEEP_OBJECT_KG: tuple[float, ...] = (0.06, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.5)
for _kg in SWEEP_OBJECT_KG:
    LOADS.setdefault(f"gripper+{_kg:g}kg-object", {"gripper_kg": GRIPPER_KG, "object_kg": _kg})
DEV_HOLDOUT = ("dev", "holdout")
CASES: dict[str, dict[str, Any]] = {
    # case id: solution, what the plant carries, what the controller's model is told it carries, splits
    "p5s-pass3/bare": {"solution": "p5s-pass3", "plant_load": None, "model_load": None, "splits": DEV_HOLDOUT},
    "p5s-pass3/loaded": {"solution": "p5s-pass3", "plant_load": "gripper+object", "model_load": None,
                         "splits": DEV_HOLDOUT},
    "p5s-pass3/loaded+model-knows": {"solution": "p5s-pass3", "plant_load": "gripper+object",
                                     "model_load": "gripper+object", "splits": ("dev",)},
    "p5s-pass3/loaded+model-knows-gripper": {"solution": "p5s-pass3", "plant_load": "gripper+object",
                                             "model_load": "gripper", "splits": DEV_HOLDOUT},
    "p5s-pass3/0.3kg-object+model-knows-gripper": {"solution": "p5s-pass3", "plant_load": "gripper+0.3kg-object",
                                                   "model_load": "gripper", "splits": DEV_HOLDOUT},
    "p1/bare": {"solution": "p1", "plant_load": None, "model_load": None, "splits": ("dev",)},
    "p1/loaded": {"solution": "p1", "plant_load": "gripper+object", "model_load": None, "splits": ("dev",)},
}


# ── the loaded model ────────────────────────────────────────────────────────────────────────────────────────


def loaded_xml(
    gripper_kg: float = GRIPPER_KG, gripper_com_m: float = GRIPPER_COM_M, object_kg: float = OBJECT_KG,
    object_m: float = TCP_OFFSET_M,
) -> str:
    """The vendored UR5e MJCF with the gripper's and the object's point masses as children of wrist_3 (no geoms)."""
    from robot_controllers.bench.ur5e import MODEL_PATH

    text = MODEL_PATH.read_text()
    anchor = '<site name="tool" pos="0 0.1 0"'
    if text.count(anchor) != 1:
        raise RuntimeError(f"{MODEL_PATH.name}: the tool site moved; the payload would land in the wrong place")
    bodies = ""
    for name, mass, out in (("gripper_2f85", gripper_kg, gripper_com_m), ("object", object_kg, object_m)):
        if mass > 0.0:
            bodies += (f'<body name="{name}" pos="0 {FLANGE_Y_M + out:.12g} 0"><inertial mass="{mass:.12g}" '
                       f'pos="0 0 0" diaginertia="{PAYLOAD_INERTIA}"/></body>\n                  ')
    return text.replace(anchor, bodies + anchor)


def load_loaded_model(*, frictionloss: bool = True, **masses: float) -> Any:
    """As robot_controllers' `load_model`, on `loaded_xml(**masses)`: the truth's armature, damping, frictionloss."""
    import mujoco
    from robot_controllers.bench.ur5e import UR5E_TRUTH

    model = mujoco.MjModel.from_xml_string(loaded_xml(**masses))
    model.dof_armature[:] = UR5E_TRUTH.armature_kg_m2
    model.dof_damping[:] = UR5E_TRUTH.damping_nm_s_rad
    model.dof_frictionloss[:] = UR5E_TRUTH.frictionloss_nm if frictionloss else 0.0
    return model


def _plant_class() -> type:
    from robot_controllers.bench.ur5e import Ur5ePlant

    class LoadedUr5ePlant(Ur5ePlant):
        """`Ur5ePlant` (the ruler's plant, every line of its reset and advance) on a given MjModel. `model=None` is the
        ruler's own bare model. The model goes in through `_stopped_model`, which reset passes its model through."""

        def __init__(self, model: Any = None, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._given_model = model

        def _stopped_model(self, model: Any, scene: Any, joint_ids: Any, start_q: Any) -> Any:
            return super()._stopped_model(model if self._given_model is None else self._given_model, scene, joint_ids,
                                          start_q)

    return LoadedUr5ePlant


# ── the "model knows the payload" variant ───────────────────────────────────────────────────────────────────


class _PrivateLoaded:
    """robot_controllers' `_Private` (the nominal model a feed-forward runs mj_inverse on) with `load` added:
    no frictionloss, the arm's jointed links scaled by the given model error, the payload bodies (no joint) exact."""

    __slots__ = ("model", "data")

    def __init__(self, model_error: Any, load: str) -> None:
        import mujoco
        from robot_controllers.bench.ur5e import jointed_bodies

        self.model = load_loaded_model(frictionloss=False, **LOADS[load])
        if model_error is not None:
            bodies = jointed_bodies(self.model)
            if len(bodies) != 6:
                raise RuntimeError(f"expected the 6 arm links to carry joints, got {len(bodies)}")
            for body, factor in zip(bodies, model_error.link_factors(len(bodies)), strict=True):
                self.model.body_mass[body] *= factor
                self.model.body_inertia[body] *= factor
            self.model.dof_damping[:] *= model_error.friction_factor
        self.data = mujoco.MjData(self.model)


def payload_aware_feedforward(terms: str, model_error: Any = None, *, load: str = "gripper+object") -> Any:
    """`ur5e_feedforward(terms, model_error)` whose private model carries `load` (a name in LOADS)."""
    from robot_controllers.bench.ur5e import Ur5eFeedforward

    feedforward = Ur5eFeedforward(terms, model_error)
    feedforward._private = _PrivateLoaded(feedforward.model_error, load)
    return feedforward


def build_knowing_payload(build: Any, load: str = "gripper+object") -> Any:
    """The solution's own `build`, with `registered_arm(...)` handing it a feed-forward that knows `load`: the one line
    a solution would change, done here without editing the solution (its module is untouched)."""
    from robot_controllers.bench.arms import arm as registered_arm

    if "registered_arm" not in build.__code__.co_names:
        raise RuntimeError("this solution's build does not take its feed-forward from registered_arm(...)")

    def arm_knowing_payload(name: str) -> Any:
        return dataclasses.replace(registered_arm(name),
                                   feedforward=functools.partial(payload_aware_feedforward, load=load))

    namespace = {**build.__globals__, "registered_arm": arm_knowing_payload}
    return types.FunctionType(build.__code__, namespace, build.__name__, build.__defaults__, build.__closure__)


# ── kinematics of the TCP ───────────────────────────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _tcp_kinematics() -> tuple[Any, Any, int]:
    import mujoco
    from robot_controllers.bench.ur5e import load_model

    model = load_model(frictionloss=False)
    return model, mujoco.MjData(model), model.body("wrist_3_link").id


def tcp_position(q: Any) -> np.ndarray:
    """The dataset's TCP (flange + 0.144 m along wrist_3's +y) for joint angles: (N, 6) -> (N, 3)."""
    import mujoco

    model, data, body = _tcp_kinematics()
    rows = np.atleast_2d(np.asarray(q, dtype=float))
    out = np.full((len(rows), 3), np.nan)
    offset = np.array([0.0, FLANGE_Y_M + TCP_OFFSET_M, 0.0])
    for row, joints in enumerate(rows):
        if not np.isfinite(joints).all():
            continue
        data.qpos[:] = joints
        mujoco.mj_kinematics(model, data)
        out[row] = data.xpos[body] + data.xmat[body].reshape(3, 3) @ offset
    return out


# ── one task ────────────────────────────────────────────────────────────────────────────────────────────────


def settle_time(t: np.ndarray, points: np.ndarray, final: np.ndarray, band_mm: float = SETTLE_BAND_MM) -> float | None:
    """The first instant after which every point stays within `band_mm` of `final`; None if the last one is outside."""
    error_mm = 1e3 * np.linalg.norm(points - final, axis=1)
    outside = np.flatnonzero(~(error_mm <= band_mm))  # NaN counts as outside (fail closed)
    if outside.size == 0:
        return float(t[0])
    if outside[-1] == len(t) - 1:
        return None
    return float(t[outside[-1] + 1])


def run_case_task(
    solution_id: str, task: Any, *, plant_load: str | None = None, model_load: str | None = None,
    keep_log: bool = False,
) -> dict:
    """One task, run as the ruler runs it (see the module docstring), the plant carrying `plant_load` and the
    controller's feed-forward told `model_load` (names in LOADS; None = nothing); a JSON-safe row (+ `_log`)."""
    from robot_controllers.bench.loop import run_episode

    from trajectory_tracking_agent import population
    from trajectory_tracking_agent.evaluate import TIME_BOX_FACTOR, _clean, _rung, _score, _SolutionSpec
    from trajectory_tracking_agent.ruler import metrics
    from trajectory_tracking_agent.ruler.deployment import deployment

    dep = deployment("ur5e_alone")
    build = population.load_build(solution_id)
    if model_load is not None:
        build = build_knowing_payload(build, model_load)
    model = None if plant_load is None else load_loaded_model(**LOADS[plant_load])
    plant_class = _plant_class()
    trajectory = task.trajectory
    t = np.asarray(trajectory.t, dtype=float)
    t_end = float(t[-1])
    limit_s = TIME_BOX_FACTOR * t_end
    wall_start = time.perf_counter()
    spec = _SolutionSpec(solution_id, build, dep, wall_start + limit_s, limit_s)
    rung = dataclasses.replace(_rung(task, dep), duration_s=t_end + dep.host_period_s + EXTRA_HOLD_S)
    log = run_episode(spec, rung, seed=0, plant_factory=lambda: plant_class(model, board_config=dep.board))
    wall_s = time.perf_counter() - wall_start
    row = _score(task, dep, log, spec, wall_s, limit_s)
    arrays = row.pop("_arrays")
    row.pop("compute_s", None)

    # the extended run on a 1 kHz grid, up to EXTRA_HOLD_S past the end
    log_t = np.asarray(log.t, dtype=float)
    log_q = np.asarray(log.q, dtype=float)
    step = int(round(SETTLE_GRID_S * float(dep.board.rate_hz)))
    grid = np.arange(0, len(log_t), step)
    reached_s = float(log_t[-1]) if len(log_t) else math.nan
    q_ext, t_ext = log_q[grid], log_t[grid]
    tool_ext = np.full((len(grid), 3), np.nan)
    finite = np.isfinite(q_ext).all(axis=1)
    if finite.any():
        tool_ext[finite] = dep.tool_position(q_ext[finite])
    tcp_ext = tcp_position(q_ext)
    target_tool = arrays["tool_target_xyz"]
    target_tcp = tcp_position(arrays["q_target"])
    full_hold = reached_s >= t_end + EXTRA_HOLD_S - 0.01
    settle = settle_time(t_ext, tool_ext, target_tool[-1]) if full_hold else None
    settle_tcp = settle_time(t_ext, tcp_ext, target_tcp[-1]) if full_hold else None
    target_settle = settle_time(t, target_tool, target_tool[-1])

    # the TCP with the ruler's own definitions (moving mask and stops from the TCP target)
    measured_tcp = tcp_position(arrays["q"])
    moving_tcp = metrics.moving_mask(t, target_tcp, arrays["qd_target"])
    stops_tcp = metrics.stop_windows(t, moving_tcp)

    within = log_t <= t_end + 1e-9
    tau = np.asarray(log.tau, dtype=float)[within]
    caps = np.asarray(dep.torque_cap_nm, dtype=float)
    peak_ratio = (np.nanmax(np.abs(tau), axis=0) / caps).tolist() if len(tau) else [None] * len(caps)

    row["extra"] = {
        "settle_s": settle,
        "target_settle_s": target_settle,
        # WHY against the target's own settle instant, not the commanded end: every tape ends with a hold, so a perfect
        # tracker is inside the band before t_end; this is the time the controller adds over a perfect one
        "overrun_s": None if settle is None else settle - target_settle,
        "tcp_settle_s": settle_tcp,
        "tcp_target_settle_s": settle_time(t, target_tcp, target_tcp[-1]),
        "tcp_track_rms_mm": metrics.tool_track_rms_mm(target_tcp, measured_tcp, moving_tcp),
        "tcp_stop_error_max_mm": metrics.stop_error_max_mm(t, target_tcp, measured_tcp, stops_tcp),
        "tcp_stop_error_median_mm": metrics.stop_error_median_mm(t, target_tcp, measured_tcp, stops_tcp),
        "final_error_mm": float(1e3 * np.linalg.norm(tool_ext[-1] - target_tool[-1])),
        "tcp_final_error_mm": float(1e3 * np.linalg.norm(tcp_ext[-1] - target_tcp[-1])),
        "peak_torque_over_cap": peak_ratio,
        "ran_to_s": reached_s,
    }
    row["all_gates_pass"] = all(row["verdicts"].values())
    row = _clean(row)
    if keep_log:
        row["_log"] = {"t": log_t, "q": log_q, "q_target": arrays["q_target"], "t_target": t}
    return row


# ── aggregate ───────────────────────────────────────────────────────────────────────────────────────────────


def _finite(values: list[Any]) -> list[float]:
    return [float(v) for v in values if v is not None and math.isfinite(float(v))]


def summarize(rows: list[dict]) -> dict:
    """Per case and split: the ruler's aggregation (objective = median over tasks) plus the W3 numbers."""
    objectives = [row["objective"] for row in rows]
    stop_max = [row["kpis"]["stop_error_max_mm"] for row in rows]
    stop_median = [row["diagnostics"].get("stop_error_mm") for row in rows]
    saturation = [row["kpis"]["saturation_share_pct"] for row in rows]
    settles = [row["extra"]["settle_s"] for row in rows]
    unsettled = [row["task"] for row in rows if row["extra"]["settle_s"] is None]
    commanded = sum(row["duration_s"] for row in rows)
    failed = {gate: sum(1 for row in rows if not row["verdicts"][gate]) for gate in rows[0]["verdicts"]}
    peak = np.array([[np.nan if v is None else v for v in row["extra"]["peak_torque_over_cap"]] for row in rows])

    def worst(key: Any, n: int = 3) -> list[dict]:
        # a missing value (a crash, never settled) ranks worst: fail closed
        scored = [(key(row), row) for row in rows]
        ordered = sorted(scored, key=lambda item: -math.inf if item[0] is None else -item[0])
        return [{"task": row["task"], "kind": row["kind"], "duration_s": row["duration_s"], "value": value,
                 "stop_error_max_mm": row["kpis"]["stop_error_max_mm"], "settle_s": row["extra"]["settle_s"],
                 "saturation_share_pct": row["kpis"]["saturation_share_pct"]} for value, row in ordered[:n]]

    return {
        "tasks": len(rows),
        "objective_tool_track_rms_mm": float(np.median(_finite(objectives))) if len(_finite(objectives)) == len(rows)
        else None,
        "gate_pass_count": sum(1 for row in rows if row["all_gates_pass"]),
        "failed_gates": failed,
        "stop_error_median_mm": float(np.median(_finite(stop_median))) if _finite(stop_median) else None,
        "stop_error_worst_mm": max(_finite(stop_max)) if _finite(stop_max) else None,
        "saturation_share_pct_worst": max(_finite(saturation)) if _finite(saturation) else None,
        "saturation_share_pct_mean": float(np.mean(_finite(saturation))) if _finite(saturation) else None,
        "peak_torque_over_cap_by_joint": np.nanmax(peak, axis=0).round(4).tolist(),
        "commanded_s": commanded,
        "target_settle_sum_s": sum(row["extra"]["target_settle_s"] for row in rows),
        "achieved_s": sum(_finite(settles)) if not unsettled else None,
        "achieved_settled_tasks_s": sum(_finite(settles)),
        "unsettled_tasks": unsettled,
        "overrun_worst_s": max(_finite([row["extra"]["overrun_s"] for row in rows])) if _finite(settles) else None,
        "tcp_track_rms_mm": float(np.median(_finite([row["extra"]["tcp_track_rms_mm"] for row in rows]))),
        "tcp_stop_error_median_mm": float(np.median(_finite([row["extra"]["tcp_stop_error_median_mm"] for row in rows]))),
        "tcp_stop_error_worst_mm": max(_finite([row["extra"]["tcp_stop_error_max_mm"] for row in rows])),
        "tcp_stop_gate_pass_count": sum(1 for row in rows if (row["extra"]["tcp_stop_error_max_mm"] or math.inf) <= 1.0),
        "tcp_achieved_s": (sum(_finite([row["extra"]["tcp_settle_s"] for row in rows]))
                           if all(row["extra"]["tcp_settle_s"] is not None for row in rows) else None),
        "tcp_unsettled_tasks": [row["task"] for row in rows if row["extra"]["tcp_settle_s"] is None],
        "worst_by_overrun": worst(lambda row: row["extra"]["overrun_s"] if row["extra"]["settle_s"] is not None
                                  else math.inf),
        "worst_by_stop_error": worst(lambda row: row["kpis"]["stop_error_max_mm"]),
        "worst_by_saturation": worst(lambda row: row["kpis"]["saturation_share_pct"]),
    }


def check_reproduces(solution_id: str, split: str, rows: list[dict]) -> dict:
    """The bare case against the solution's committed scorecard, task by task (objective, kpis, verdicts)."""
    name = "scorecard.json" if split == "dev" else f"scorecard_{split}.json"
    path = Path("solutions") / solution_id / name
    from trajectory_tracking_agent.ruler.dataset import REPO_ROOT

    card = json.loads((REPO_ROOT / path).read_text())
    reference = {row["task"]: row for row in card["tasks"]}
    mismatches = []
    worst = 0.0
    for row in rows:
        ref = reference[row["task"]]
        if ref["objective"] is not None and row["objective"] is not None:
            worst = max(worst, abs(ref["objective"] - row["objective"]))
        if row["objective"] != ref["objective"] or row["kpis"] != ref["kpis"] or row["verdicts"] != ref["verdicts"]:
            mismatches.append(row["task"])
    return {"scorecard": str(path), "card_objective": card["objective"], "max_abs_task_objective_diff": worst,
            "mismatched_tasks": mismatches, "bit_identical": not mismatches}


def self_check_hook() -> dict:
    """Our model path against robot_controllers' own payload hook (`Scene.payload_kg`, a point mass at the tool site):
    the same mass at the same place must give the same run, bit for bit. One dev task, p5s-pass3."""
    from robot_controllers.bench.loop import run_episode

    from trajectory_tracking_agent import population
    from trajectory_tracking_agent.evaluate import _rung, _SolutionSpec
    from trajectory_tracking_agent.ruler.dataset import tasks
    from trajectory_tracking_agent.ruler.deployment import deployment

    dep = deployment("ur5e_alone")
    task = tasks("dev")[0]
    mass = GRIPPER_KG + OBJECT_KG
    runs = []
    for ours in (True, False):
        spec = _SolutionSpec("p5s-pass3", population.load_build("p5s-pass3"), dep, time.perf_counter() + 1e3, 1e3)
        rung = _rung(task, dep)
        if ours:
            model = load_loaded_model(gripper_kg=mass, gripper_com_m=0.0, object_kg=0.0)
            log = run_episode(spec, rung, seed=0, plant_factory=lambda: _plant_class()(model, board_config=dep.board))
        else:
            rung = dataclasses.replace(rung, scene=dataclasses.replace(rung.scene, payload_kg=mass))
            log = run_episode(spec, rung, seed=0, plant_factory=dep.plant)
        runs.append(np.asarray(log.q, dtype=float))
    same = runs[0].shape == runs[1].shape and bool(np.array_equal(runs[0], runs[1]))
    return {"task": task.id, "payload_kg": mass, "bit_identical_to_robot_controllers_payload_hook": same}


# ── main ────────────────────────────────────────────────────────────────────────────────────────────────────


def run_all(allow_mismatch: bool = False) -> dict:
    from trajectory_tracking_agent.ruler.dataset import tasks
    from trajectory_tracking_agent.ruler.deployment import package_versions

    started = time.perf_counter()
    hook = self_check_hook()
    print(f"self-check vs robot_controllers payload hook: {hook}", flush=True)
    if not hook["bit_identical_to_robot_controllers_payload_hook"] and not allow_mismatch:
        raise SystemExit("our loaded-model path does not match robot_controllers' payload hook; stopping")
    out: dict[str, Any] = {
        "schema": "tta.w3_loaded_check/1",
        "what": "off-score: ruler v1's run on a UR5e carrying a Robotiq 2F-85 (point mass) and a 60 g or 0.3 kg object",
        "load": {
            "gripper_kg": GRIPPER_KG, "gripper_com_along_tool_axis_from_flange_m": GRIPPER_COM_M,
            "object_kg": OBJECT_KG, "object_along_tool_axis_from_flange_m": TCP_OFFSET_M,
            "total_kg": GRIPPER_KG + OBJECT_KG,
            "sources": {
                "gripper_mass": "robotparts parts/robotiq-2f-85/part.py `mass` (Robotiq manual Table 5-1, 925 g)",
                "gripper_com": "robotparts parts/robotiq-2f-85/files/2f-85.xml (Menagerie robotiq_2f85_v4), open pose",
                "object_point": "the dataset's TCP (tapes' tcp_pos): flange + 0.144 m along wrist_3 +y",
            },
            "controller_knows": "each case's model_load: what p5s-pass3's feed-forward is told, exactly (its arm links "
                                "stay 10 % wrong); None = nothing",
        },
        "loads": LOADS,
        "extra_hold_s": EXTRA_HOLD_S,
        "settle_band_mm": SETTLE_BAND_MM,
        "settle_grid_s": SETTLE_GRID_S,
        "packages": package_versions(),
        "self_check": hook,
        "cases": {},
    }
    for case, config in CASES.items():
        for split in config["splits"]:
            rows = []
            for task in tasks(split):
                rows.append(run_case_task(config["solution"], task, plant_load=config["plant_load"],
                                          model_load=config["model_load"]))
            entry: dict[str, Any] = {**{k: v for k, v in config.items() if k != "splits"}, "split": split,
                                     "summary": summarize(rows), "tasks": rows}
            if config["plant_load"] is None:
                entry["reproduces_scorecard"] = check_reproduces(config["solution"], split, rows)
                print(f"{case} {split}: reproduces scorecard: {entry['reproduces_scorecard']}", flush=True)
                if not entry["reproduces_scorecard"]["bit_identical"] and not allow_mismatch:
                    raise SystemExit(f"{case} {split} does not reproduce its committed scorecard; stopping")
            summary = entry["summary"]
            print(f"{case} {split}: objective {summary['objective_tool_track_rms_mm']} mm, gates "
                  f"{summary['gate_pass_count']}/{summary['tasks']}, stop worst {summary['stop_error_worst_mm']} mm, "
                  f"achieved {summary['achieved_s']} s of {summary['commanded_s']:.2f} s", flush=True)
            out["cases"][f"{case}@{split}"] = entry
    out["sweep"] = run_sweep()
    out["wall_time_s"] = time.perf_counter() - started
    return out


def run_sweep(solution_id: str = "p5s-pass3", split: str = "dev") -> dict:
    """The break sweep: SWEEP_OBJECT_KG on the plant, the gripper (only) in the controller's model; summaries only."""
    from trajectory_tracking_agent.ruler.dataset import tasks

    out: dict[str, Any] = {"what": "object mass sweep: the gripper known to the feed-forward, the object not",
                           "solution": solution_id, "model_load": "gripper", "split": split, "rows": []}
    for kg in SWEEP_OBJECT_KG:
        load = f"gripper+{kg:g}kg-object"
        rows = [run_case_task(solution_id, task, plant_load=load, model_load="gripper") for task in tasks(split)]
        summary = summarize(rows)
        out["rows"].append({
            "object_kg": kg, "plant_load": load,
            **{key: summary[key] for key in ("tasks", "objective_tool_track_rms_mm", "gate_pass_count", "failed_gates",
                                              "stop_error_median_mm", "stop_error_worst_mm", "saturation_share_pct_worst",
                                              "tcp_track_rms_mm", "tcp_stop_error_worst_mm", "tcp_stop_gate_pass_count")},
            "failed_tasks": [row["task"] for row in rows if not row["all_gates_pass"]],
            "tcp_stop_over_1mm_tasks": [row["task"] for row in rows
                                        if not (row["extra"]["tcp_stop_error_max_mm"] or math.inf) <= 1.0],
        })
        last = out["rows"][-1]
        print(f"sweep object {kg:g} kg: gates {last['gate_pass_count']}/{last['tasks']}, stop worst "
              f"{last['stop_error_worst_mm']:.3f} mm, TCP stops <= 1 mm {last['tcp_stop_gate_pass_count']}/{last['tasks']}",
              flush=True)
    return out


def _rounded(value: Any, digits: int = 6) -> Any:
    """`digits` significant digits for every float (results.json stays reviewable; nothing here is a ruler number)."""
    if isinstance(value, dict):
        return {key: _rounded(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item, digits) for item in value]
    if isinstance(value, float) and math.isfinite(value) and value != 0.0:
        return round(value, digits - 1 - int(math.floor(math.log10(abs(value)))))
    return value


KEPT_DIAGNOSTICS = ("tool_track_max_mm", "stop_error_mm", "tool_lag_ms", "settle_error_max_mm", "stops")


def dump(results: dict) -> str:
    """results.json: floats to 6 significant digits, the ruler diagnostics this check reads, one task row per line.

    WHY round only the file: the reproduction check compared full-precision numbers before this runs."""
    slim = _rounded(results)
    rows: list[str] = []
    for entry in slim["cases"].values():
        for row in entry["tasks"]:
            row["diagnostics"] = {key: row["diagnostics"].get(key) for key in KEPT_DIAGNOSTICS}
            rows.append(json.dumps(row, separators=(", ", ": ")))
        entry["tasks"] = [f"@@row{len(rows) - len(entry['tasks']) + index}@@" for index in range(len(entry["tasks"]))]
    text = json.dumps(slim, indent=1)
    for index, row in enumerate(rows):
        text = text.replace(f'"@@row{index}@@"', row, 1)
    json.loads(text)  # still JSON
    return text + "\n"


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def table(results: dict) -> str:
    """README's tables, from results.json."""
    lines = [
        "| Case | Split | Tool RMS (mm, ruler objective) | Stop error median / worst (mm) | Saturation worst task (%) "
        "| Gates passed | Commanded (s) | Achieved: settled ≤ 1 mm (s) | Perfect tracker (s) | Worst task overrun (ms) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, entry in results["cases"].items():
        case, split = key.split("@")
        s = entry["summary"]
        achieved = _fmt(s["achieved_s"], 2) if s["achieved_s"] is not None else (
            f"{s['achieved_settled_tasks_s']:.2f} over {s['tasks'] - len(s['unsettled_tasks'])} tasks; "
            f"{len(s['unsettled_tasks'])} never settle")
        lines.append(
            f"| {case} | {split} | {_fmt(s['objective_tool_track_rms_mm'], 4)} | {_fmt(s['stop_error_median_mm'])} / "
            f"{_fmt(s['stop_error_worst_mm'])} | {_fmt(s['saturation_share_pct_worst'], 3)} | "
            f"{s['gate_pass_count']}/{s['tasks']} | {s['commanded_s']:.2f} | {achieved} | {s['target_settle_sum_s']:.2f} | "
            f"{_fmt(None if s['overrun_worst_s'] is None else 1e3 * s['overrun_worst_s'], 0)} |")
    lines += [
        "",
        "At the TCP (flange + 0.144 m, where the object is; the ruler's definitions, not the ruler's point):",
        "",
        "| Case | Split | TCP RMS (mm) | TCP stop error median / worst (mm) | Tasks with TCP stops ≤ 1 mm | "
        "TCP achieved (s) |",
        "|---|---|---|---|---|---|",
    ]
    for key, entry in results["cases"].items():
        case, split = key.split("@")
        s = entry["summary"]
        tcp_achieved = _fmt(s["tcp_achieved_s"], 2) if s["tcp_achieved_s"] is not None else (
            f"{len(s['tcp_unsettled_tasks'])} never settle")
        lines.append(f"| {case} | {split} | {_fmt(s['tcp_track_rms_mm'], 4)} | {_fmt(s['tcp_stop_error_median_mm'])} / "
                     f"{_fmt(s['tcp_stop_error_worst_mm'])} | {s['tcp_stop_gate_pass_count']}/{s['tasks']} | "
                     f"{tcp_achieved} |")
    lines += ["", "Worst 3 tasks per case: by stop error (ruler point), then by overrun (settle time minus a perfect tracker's):", ""]
    for key, entry in results["cases"].items():
        s = entry["summary"]
        stops = "; ".join(f"{w['task']} ({w['kind']}) {_fmt(w['value'])} mm" for w in s["worst_by_stop_error"])
        overrun = "; ".join(
            f"{w['task']} " + ("never settles" if w["settle_s"] is None else f"{w['value'] * 1e3:+.0f} ms")
            for w in s["worst_by_overrun"])
        lines.append(f"- **{key}**: stop error {stops}. Overrun {overrun}.")
    sweep = results.get("sweep")
    if sweep:
        lines += ["", f"Object mass sweep ({sweep['solution']}, {sweep['split']}; the gripper known to the feed-forward, "
                  "the object not):", "",
                  "| Object (kg) | Tool RMS (mm) | Stop error median / worst (mm) | Gates passed | Saturation worst task (%) "
                  "| TCP stop error worst (mm) | Tasks with TCP stops ≤ 1 mm |",
                  "|---|---|---|---|---|---|---|"]
        for row in sweep["rows"]:
            lines.append(f"| {row['object_kg']:g} | {_fmt(row['objective_tool_track_rms_mm'], 4)} | "
                         f"{_fmt(row['stop_error_median_mm'])} / {_fmt(row['stop_error_worst_mm'])} | "
                         f"{row['gate_pass_count']}/{row['tasks']} | {_fmt(row['saturation_share_pct_worst'])} | "
                         f"{_fmt(row['tcp_stop_error_worst_mm'])} | {row['tcp_stop_gate_pass_count']}/{row['tasks']} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", action="store_true", help="print README's tables from results.json and exit")
    parser.add_argument("--allow-mismatch", action="store_true", help="keep going if the bare case does not reproduce")
    args = parser.parse_args(argv)
    if args.table:
        print(table(json.loads(RESULTS.read_text())))
        return 0
    results = run_all(args.allow_mismatch)
    RESULTS.write_text(dump(results))
    print(table(results))
    print(f"wrote {RESULTS.relative_to(HERE.parents[1])} in {results['wall_time_s']:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
