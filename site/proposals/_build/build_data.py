"""Precompute the data the five metric-view proposals show, from REAL simulation traces.

    cd ~/trajectory_tracking_agent && uv run python site/proposals/_build/build_data.py

Reads arm_motion_bench's UR5e traces (a sibling checkout, read-only), recomputes the ruler v1 metrics and gates
(OBJECTIVES.md §4) from the black box's OUTPUTS only, and writes one small `data.js` next to each proposal.

WHY outputs only (Zach, 2026-11-24): "KEY OF COURSE IS THAT THE BLACKBOX VIZ IS NOT RELATED TO THE SOLUTION ONLY
TO THE METRICS OUT". Every number here comes from the target trajectory, the measured joint states, the applied
torques, the deployment (caps, limits, floor, tool FK) and the ruler. The traces also carry controller internals
(feed-forward / feedback / integral torque splits, gains): this script never reads them, so any solution renders
through the same view.

WHY the tool point is recomputed: the traces' own `tcp_pos` is arm_motion_bench's claw stand-in (0.144 m out);
the ruler's tool point is robot_controllers' flange site `tool` (0.1 m along wrist_3), through the same FK for
target and measured joints (OBJECTIVES §2, §4).

When lane E's frozen ruler (`trajectory_tracking_agent.ruler.metrics`) exists, its functions replace the local
ones below (same signatures, CONTRACT §6), so these pages show the ruler's own numbers.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PROPOSALS = HERE.parent
REPO = PROPOSALS.parent.parent
DEFAULT_RUNS = REPO.parent / "arm_motion_bench" / "outputs" / "runs"

CONTROLLERS = ("ctc_tuned", "id_pd", "ctc_model_err", "menagerie_stock")  # every UR5e controller with all 42 dev tasks of workspace v1 at speed 1.0
ROBOT = "ur5e"
DATASET = "workspace-v1"
FEATURED_TASK = "workspace-dev-001"  # five stops (ISO 9283-style), 6.1 s: every gate has something to show
SPLIT = "dev"

# Deployment v1 (OBJECTIVES §2): caps from the UR5e datasheet; limits from arm_motion_bench robots/ur5e.py
TAU_CAP_NM = np.array([150.0, 150.0, 150.0, 28.0, 28.0, 28.0])
Q_HI = np.array([2 * math.pi, 2 * math.pi, math.pi, 2 * math.pi, 2 * math.pi, 2 * math.pi])
Q_LO = -Q_HI
QD_MAX = np.full(6, math.pi)  # 180 deg/s, UR datasheet, every joint
JOINTS = ("shoulder pan", "shoulder lift", "elbow", "wrist 1", "wrist 2", "wrist 3")
FLOOR_Z = 0.0

# OBJECTIVES §4 thresholds
MOVING_TOOL_M_S = 1e-3
MOVING_JOINT_RAD_S = math.radians(0.06)
STOP_MIN_S = 0.2
STOP_TAIL_S = 0.1
SAT_FRACTION = 0.98
GATE_STOP_MM = 1.0
GATE_SAT_PCT = 2.0
VEL_MARGIN = 1.05

GATES = ("completed", "stop_error_max_mm", "saturation_share_pct", "limit_violations", "floor_clearance")


# ── the ruler (local copy of OBJECTIVES §4 until lane E's ruler/metrics.py lands) ─────────────────────────────


def moving_mask(t, target_tool_xyz, target_qd):
    speed = np.linalg.norm(np.gradient(target_tool_xyz, t, axis=0), axis=1)
    return (speed > MOVING_TOOL_M_S) | (np.abs(target_qd) > MOVING_JOINT_RAD_S).any(axis=1)


def stop_windows(t, moving):
    windows, start = [], None
    for i, m in enumerate(moving):
        if not m and start is None:
            start = i
        if (m or i == len(moving) - 1) and start is not None:
            end = i if not m else i - 1
            if t[end] - t[start] >= STOP_MIN_S:
                windows.append((float(t[start]), float(t[end])))
            start = None
    return windows


def tool_errors_mm(target_tool_xyz, measured_tool_xyz):
    return 1e3 * np.linalg.norm(measured_tool_xyz - target_tool_xyz, axis=1)


def tool_track_rms_mm(target_tool_xyz, measured_tool_xyz, moving):
    if not moving.any():
        return float("nan")
    e = tool_errors_mm(target_tool_xyz, measured_tool_xyz)[moving]
    return float(np.sqrt(np.mean(e**2)))


def tool_track_max_mm(target_tool_xyz, measured_tool_xyz, moving):
    if not moving.any():
        return float("nan")
    return float(tool_errors_mm(target_tool_xyz, measured_tool_xyz)[moving].max())


def stop_errors_mm(t, target_tool_xyz, measured_tool_xyz, stops):
    rows = []
    for t0, t1 in stops:
        tail = (t >= t1 - STOP_TAIL_S) & (t <= t1)
        target = target_tool_xyz[tail].mean(axis=0)
        rest = measured_tool_xyz[tail].mean(axis=0)
        rows.append(float(1e3 * np.linalg.norm(rest - target)))
    return rows


def stop_error_max_mm(t, target_tool_xyz, measured_tool_xyz, stops):
    rows = stop_errors_mm(t, target_tool_xyz, measured_tool_xyz, stops)
    return max(rows) if rows else 0.0


def saturated_samples(torque, caps):
    return (np.abs(torque) >= SAT_FRACTION * caps).any(axis=1)


def saturation_share_pct(torque, caps):
    return float(100.0 * saturated_samples(torque, caps).mean())


def limit_violation_samples(q, qd, q_lo, q_hi, qd_max):
    return ((q < q_lo) | (q > q_hi) | (np.abs(qd) > VEL_MARGIN * qd_max)).any(axis=1)


def limit_violations(q, qd, q_lo, q_hi, qd_max):
    return int(limit_violation_samples(q, qd, q_lo, q_hi, qd_max).sum())


def floor_clearance_violations(points_z, floor_z=FLOOR_Z):
    return int((points_z < floor_z).any(axis=1).sum())


def gate_verdicts(kpis):
    def ok(value, test):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return False  # fail closed
        return bool(test(value))

    return {
        "completed": ok(kpis["completed"], lambda v: v is True),
        "stop_error_max_mm": ok(kpis["stop_error_max_mm"], lambda v: v <= GATE_STOP_MM),
        "saturation_share_pct": ok(kpis["saturation_share_pct"], lambda v: v <= GATE_SAT_PCT),
        "limit_violations": ok(kpis["limit_violations"], lambda v: v == 0),
        "floor_clearance": ok(kpis["floor_clearance"], lambda v: v == 0),
    }


try:  # the frozen ruler wins when it exists (CONTRACT §6)
    from trajectory_tracking_agent.ruler import metrics as _ruler  # type: ignore

    moving_mask = _ruler.moving_mask  # noqa: F811
    stop_windows = _ruler.stop_windows  # noqa: F811
    tool_track_rms_mm = _ruler.tool_track_rms_mm  # noqa: F811
    tool_track_max_mm = _ruler.tool_track_max_mm  # noqa: F811
    stop_error_max_mm = _ruler.stop_error_max_mm  # noqa: F811
    saturation_share_pct = _ruler.saturation_share_pct  # noqa: F811
    RULER_SOURCE = "trajectory_tracking_agent.ruler.metrics"
except Exception:  # noqa: BLE001
    RULER_SOURCE = "site/proposals/_build/build_data.py (OBJECTIVES §4, until ruler/metrics.py lands)"


# ── forward kinematics: the ruler's tool point and the link origins (robot_controllers' UR5e model) ──────────


class Kinematics:
    BODIES = ("shoulder_link", "upper_arm_link", "forearm_link", "wrist_1_link", "wrist_2_link", "wrist_3_link")

    def __init__(self):
        import mujoco
        from robot_controllers.bench.ur5e import TOOL_SITE, load_model

        self.mj = mujoco
        self.model = load_model(frictionloss=False)
        self.data = mujoco.MjData(self.model)
        self.site = self.model.site(TOOL_SITE).id
        self.bodies = [self.model.body(name).id for name in self.BODIES]

    def points(self, q):
        """(N, 6) rad -> (N, 8, 3) m: base, the six link origins, the tool point."""
        out = np.zeros((len(q), 8, 3))
        for i, row in enumerate(q):
            self.data.qpos[:] = row
            self.mj.mj_kinematics(self.model, self.data)
            out[i, 1:7] = self.data.xpos[self.bodies]
            out[i, 7] = self.data.site_xpos[self.site]
        return out


# ── one trace ─────────────────────────────────────────────────────────────────────────────────────────────


def tool_lag_ms(t, target_q, q, moving):
    from robot_msgs.compare import estimate_time_offset
    from robot_msgs.trajectory import JointTrajectory

    if not moving.any():
        return float("nan")
    names = tuple(f"joint{i}" for i in range(q.shape[1]))
    target = JointTrajectory(t=t, joint_names=names, positions=np.asarray(target_q, float))
    measured = JointTrajectory(t=t, joint_names=names, positions=np.asarray(q, float))
    try:
        return float(1e3 * estimate_time_offset(target, measured).offset_s)
    except ValueError:
        return float("nan")


def load_trace(path):
    """Only the black box's outputs and the target; never opt_* (controller internals) or meta gains."""
    with np.load(path, allow_pickle=False) as npz:
        meta = json.loads(str(npz["meta"]))
        return {
            "t": npz["t"].astype(float),
            "q": npz["q"].astype(float),
            "qd": npz["qd"].astype(float),
            "tau": npz["tau"].astype(float),
            "target_q": npz["target_q"].astype(float),
            "target_qd": npz["target_qd"].astype(float),
            "aborted": bool(meta.get("aborted", False)),
            "tape_s": float(meta["tape_s"]),
            "task_id": meta["task_id"],
            "controller": meta["controller"],
            "source_sha": meta["source"]["git_sha"][:10],
        }


def evaluate_trace(tr, kin):
    t, q, qd, tau = tr["t"], tr["q"], tr["qd"], tr["tau"]
    measured_pts = kin.points(q)
    target_pts = kin.points(tr["target_q"])
    tool, target_tool = measured_pts[:, 7], target_pts[:, 7]
    moving = moving_mask(t, target_tool, tr["target_qd"])
    stops = stop_windows(t, moving)
    finite = all(np.isfinite(a).all() for a in (q, qd, tau))
    completed = bool((not tr["aborted"]) and finite and t[-1] >= tr["tape_s"] - 1e-9 and bool(stops) and stops[-1][1] >= t[-1] - 1e-9)
    joint_err_deg = np.degrees(q - tr["target_q"])
    joint_rms = np.sqrt(np.mean(joint_err_deg[moving] ** 2, axis=0)) if moving.any() else np.full(6, np.nan)
    power = tau * qd
    dt = np.gradient(t)
    energy_j = float((np.clip(power, 0, None) * dt[:, None]).sum())
    stop_rows = stop_errors_mm(t, target_tool, tool, stops)
    kpis = {
        "tool_track_rms_mm": tool_track_rms_mm(target_tool, tool, moving),
        "tool_track_max_mm": tool_track_max_mm(target_tool, tool, moving),
        "completed": completed,
        "stop_error_max_mm": stop_error_max_mm(t, target_tool, tool, stops),
        "stop_error_mm": float(np.median(stop_rows)) if stop_rows else float("nan"),
        "saturation_share_pct": saturation_share_pct(tau, TAU_CAP_NM),
        "limit_violations": limit_violations(q, qd, Q_LO, Q_HI, QD_MAX),
        "floor_clearance": floor_clearance_violations(measured_pts[:, 1:, 2]),
        "joint_track_rms_deg": float(np.nanmax(joint_rms)),
        "joint_track_rms_deg_by_joint": [float(v) for v in joint_rms],
        "tool_lag_ms": tool_lag_ms(t, tr["target_q"], q, moving),
        "energy_j": energy_j,
        "min_clearance_mm": float(1e3 * measured_pts[:, 1:, 2].min()),
        "torque_peak_pct": float(100 * (np.abs(tau) / TAU_CAP_NM).max()),
        "velocity_peak_pct": float(100 * (np.abs(qd) / QD_MAX).max()),
        "duration_s": float(t[-1]),
        "samples": int(len(t)),
        "moving_samples": int(moving.sum()),
    }
    kpis["gates"] = gate_verdicts(kpis)
    kpis["passed"] = all(kpis["gates"].values())
    extras = {"measured_pts": measured_pts, "target_pts": target_pts, "moving": moving, "stops": stops,
              "stop_rows": stop_rows}
    return kpis, extras


def r(x, nd=3):
    if x is None:
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd)


def rows(a, nd):
    return np.round(np.asarray(a, float), nd).tolist()


def intervals(mask, t):
    """A boolean mask as [[i0, i1], ...] sample-index runs (inclusive)."""
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        if start is not None and (not m or i == len(mask) - 1):
            out.append([start, i if m else i - 1])
            start = None
    return out


def pooled_max(values, bins):
    """Max-pool a series into `bins` buckets, so a sparkline keeps every peak."""
    edges = np.linspace(0, len(values), bins + 1).astype(int)
    return [float(values[a:b].max()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]


# ── population ─────────────────────────────────────────────────────────────────────────────────────────────


def population(runs_dir, kin):
    """Every controller on every dev task at speed 1.0, repeat 0. Tasks whose TARGET leaves the half-space above
    the base plane are left out (kept in `excluded`): arm_motion_bench's `ur5e` cell hangs the arm over its
    workspace, so ruler v1's floor plane (ur5e_alone: z = 0 at the base) would fail them for every solution."""
    by_controller, featured, excluded = {}, {}, set()
    for controller in CONTROLLERS:
        paths = sorted(glob.glob(str(runs_dir / ROBOT / controller / DATASET / SPLIT / "*__s1.0__r0.trace.npz")))
        for path in paths:
            tr = load_trace(path)
            kpis, extras = evaluate_trace(tr, kin)
            if extras["target_pts"][:, 1:, 2].min() < FLOOR_Z:
                excluded.add(tr["task_id"])
                continue
            rel = os.path.relpath(path, runs_dir.parent.parent.parent)
            err = tool_errors_mm(extras["target_pts"][:, 7], extras["measured_pts"][:, 7])
            row = {"task": tr["task_id"], "source": rel, "source_sha": tr["source_sha"], **kpis,
                   "spark_err_mm": [r(v, 4) for v in pooled_max(np.where(extras["moving"], err, 0.0), 80)],
                   "spark_moving": [int(v > 0) for v in pooled_max(extras["moving"].astype(float), 80)]}
            by_controller.setdefault(controller, []).append(row)
            if tr["task_id"] == FEATURED_TASK:
                featured[controller] = (tr, kpis, extras, rel)
    pop = []
    for controller, tasks in by_controller.items():
        tasks.sort(key=lambda x: x["task"])
        objectives = [x["tool_track_rms_mm"] for x in tasks]
        obj = float(np.median(objectives)) if all(np.isfinite(objectives)) else float("nan")
        verdicts = [x["gates"] for x in tasks]
        gate_fail = {g: sum(1 for v in verdicts if not v[g]) for g in GATES}
        admissible = all(all(v.values()) for v in verdicts)
        pass_rate = 1 - sum(gate_fail.values()) / (len(tasks) * len(GATES))
        diag = {k: float(np.nanmedian([x[k] for x in tasks])) for k in
                ("tool_track_max_mm", "joint_track_rms_deg", "tool_lag_ms", "stop_error_mm", "saturation_share_pct",
                 "energy_j", "torque_peak_pct", "velocity_peak_pct", "min_clearance_mm")}
        pop.append({"id": controller, "objective": obj, "admissible": admissible, "gate_pass_rate": pass_rate,
                    "failed_gates": gate_fail, "tasks_passed": sum(1 for x in tasks if x["passed"]),
                    "diagnostics": diag, "tasks": tasks})
    # OBJECTIVES §4 ranking: admissible by objective, then the rest by gate pass rate, then objective
    pop.sort(key=lambda s: (not s["admissible"], 0 if s["admissible"] else -s["gate_pass_rate"], s["objective"]))
    for rank, s in enumerate(pop, 1):
        s["rank"] = rank
    return pop, featured, sorted(excluded)


TASK_KEYS = {"tool_track_rms_mm": 4, "tool_track_max_mm": 4, "stop_error_max_mm": 4, "stop_error_mm": 4,
             "saturation_share_pct": 3, "limit_violations": 0, "floor_clearance": 0, "completed": 0,
             "joint_track_rms_deg": 5, "tool_lag_ms": 2, "energy_j": 2, "torque_peak_pct": 1, "velocity_peak_pct": 1,
             "min_clearance_mm": 1, "duration_s": 3, "samples": 0, "moving_samples": 0}


def compact_population(pop):
    out = []
    for s in pop:
        out.append({
            "id": s["id"], "rank": s["rank"], "objective": r(s["objective"], 5), "admissible": s["admissible"],
            "gate_pass_rate": r(s["gate_pass_rate"], 4), "failed_gates": s["failed_gates"],
            "tasks_passed": s["tasks_passed"], "diagnostics": {k: r(v, 5) for k, v in s["diagnostics"].items()},
            "tasks": [{**{k: r(x[k], nd) for k, nd in TASK_KEYS.items()}, "task": x["task"], "gates": x["gates"],
                       "passed": x["passed"], "source": x["source"], "spark_err_mm": x["spark_err_mm"],
                       "spark_moving": x["spark_moving"]} for x in s["tasks"]],
        })
    return out


# ── one featured trace, as the views need it ─────────────────────────────────────────────────────────────


def trace_payload(tr, kpis, extras, rel, *, every=5):
    t = tr["t"]
    dt = np.diff(t)
    if not np.allclose(dt, dt[0], atol=1e-9):
        raise ValueError(f"{rel}: non-uniform time base")
    mpts, tpts = extras["measured_pts"], extras["target_pts"]
    err = tool_errors_mm(tpts[:, 7], mpts[:, 7])
    sat = saturated_samples(tr["tau"], TAU_CAP_NM)
    lim = limit_violation_samples(tr["q"], tr["qd"], Q_LO, Q_HI, QD_MAX)
    below = (mpts[:, 1:, 2] < FLOOR_Z).any(axis=1)
    idx = np.arange(0, len(t), every)
    if idx[-1] != len(t) - 1:
        idx = np.append(idx, len(t) - 1)
    lowest = mpts[:, 1:, 2].min(axis=1)
    lowest_i = int(np.argmin(lowest))
    peak_err_i = int(np.argmax(np.where(extras["moving"], err, -1)))
    return {
        "solution": tr["controller"],
        "task": tr["task_id"],
        "source": rel,
        "source_sha": tr["source_sha"],
        "t0": r(t[0], 6), "dt": r(dt[0], 6), "n": int(len(t)),
        "kpis": {k: r(kpis[k], nd) for k, nd in TASK_KEYS.items()},
        "gates": kpis["gates"], "passed": kpis["passed"],
        "joint_rms_deg": [r(v, 5) for v in kpis["joint_track_rms_deg_by_joint"]],
        "stops": [[r(a, 4), r(b, 4)] for a, b in extras["stops"]],
        "stop_errors_mm": [r(v, 4) for v in extras["stop_rows"]],
        "stop_points_mm": [  # target and mean measured tool point over each stop's last 0.1 s
            {"target": rows(1e3 * tpts[(t >= b - STOP_TAIL_S) & (t <= b), 7].mean(axis=0), 4),
             "rest": rows(1e3 * mpts[(t >= b - STOP_TAIL_S) & (t <= b), 7].mean(axis=0), 4)}
            for a, b in extras["stops"]],
        "peak_err_i": peak_err_i,
        "lowest_i": lowest_i, "lowest_link": int(np.argmin(mpts[lowest_i, 1:, 2])) + 1,
        "full": {  # every sample: what the objective and gates are computed from
            "err_mm": rows(err, 5),
            "lowest_mm": rows(1e3 * lowest, 1),
            "moving": intervals(extras["moving"], t),
            "sat": intervals(sat, t),
            "lim": intervals(lim, t),
            "below": intervals(below, t),
        },
        "every": every,
        "idx": idx.tolist(),  # the decimated samples' indices (every `every`-th, plus the last)
        "arm_mm": rows(1e3 * mpts[idx], 1),  # (k, 8, 3): base, six link origins, tool point
        "target_arm_mm": rows(1e3 * tpts[idx], 1),
        "tool_mm": rows(1e3 * mpts[idx, 7], 4),
        "target_tool_mm": rows(1e3 * tpts[idx, 7], 4),
        "q_deg": rows(np.degrees(tr["q"][idx]), 3),
        "target_q_deg": rows(np.degrees(tr["target_q"][idx]), 3),
        "err_deg": rows(np.degrees(tr["q"][idx] - tr["target_q"][idx]), 5),
        "tau_pct": rows(100 * tr["tau"][idx] / TAU_CAP_NM, 2),
        "qd_pct": rows(100 * tr["qd"][idx] / QD_MAX, 2),
        "power_w": rows((tr["tau"] * tr["qd"])[idx], 2),
    }


INPUTS = [
    ["target trajectory", "target joint positions and velocities (the task's tape, as played)"],
    ["measured joint states", "joint positions and velocities from the encoders"],
    ["applied torques", "joint torques the boards applied"],
    ["deployment", "torque caps, joint position and velocity limits, the floor plane, the tool-point FK"],
    ["ruler v1", "the objective, the five gates and their thresholds (OBJECTIVES.md §4)"],
]
NOT_USED = "controller internals: feed-forward / feedback / integral torque split, gains, models, observers"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    args = parser.parse_args()
    kin = Kinematics()
    pop, featured, excluded = population(args.runs, kin)
    for s in pop:
        print(s["rank"], s["id"], f'{s["objective"]:.4f}', s["admissible"], s["failed_gates"], s["tasks_passed"])
    fixture = {
        "generated_by": "site/proposals/_build/build_data.py",
        "ruler": "v1 (OBJECTIVES.md §4)",
        "ruler_source": RULER_SOURCE,
        "robot": "UR5e (MuJoCo Menagerie, simulated)",
        "dataset": f"arm_motion_bench {ROBOT}/workspace/v1 · {SPLIT} · speed 1.0 · repeat 0",
        "source_repo": "arm_motion_bench (outputs/runs, read-only)",
        "tasks_used": len(pop[0]["tasks"]),
        "tasks_excluded": excluded,
        "excluded_why": ("arm_motion_bench's `ur5e` cell hangs the arm over its workspace: these tasks' TARGET goes "
                         "below the base plane, so ruler v1's floor gate (ur5e_alone: floor at the base) would fail "
                         "them for every solution. Left out, not failed."),
        "caveat": ("Not yet ruler v1's own deployment: these traces are arm_motion_bench's UR5e at 500 Hz control. "
                   "The ruler's ur5e_alone dataset has only 3 traces so far (one controller). The views read only the "
                   "fields below, so lane E's scorecards and traces drop in unchanged."),
        "inputs": INPUTS,
        "not_used": NOT_USED,
        "deployment": {
            "tau_cap_nm": TAU_CAP_NM.tolist(),
            "q_limit_deg": [r(math.degrees(v), 1) for v in Q_HI],
            "qd_max_deg_s": [r(math.degrees(v), 1) for v in QD_MAX],
            "joints": list(JOINTS),
            "links": ["base", "shoulder", "upper arm", "forearm", "wrist 1", "wrist 2", "wrist 3", "tool point"],
            "floor_z_mm": 0.0,
            "tool_point": "flange site `tool`, 0.1 m along wrist 3 (robot_controllers.bench.ur5e)",
        },
        "thresholds": {"stop_error_max_mm": GATE_STOP_MM, "saturation_share_pct": GATE_SAT_PCT,
                       "sat_fraction": SAT_FRACTION, "vel_margin": VEL_MARGIN, "stop_min_s": STOP_MIN_S,
                       "stop_tail_s": STOP_TAIL_S, "moving_tool_mm_s": 1.0, "moving_joint_deg_s": 0.06},
        "featured_task": FEATURED_TASK,
        "population": compact_population(pop),
        "traces": {c: trace_payload(*featured[c]) for c in [s["id"] for s in pop]},
    }
    out = PROPOSALS / "_data"
    out.mkdir(exist_ok=True)
    text = json.dumps(fixture, separators=(",", ":"), allow_nan=False)
    (out / "fixture.js").write_text("// generated by site/proposals/_build/build_data.py: do not edit\n"
                                     f"window.FIXTURE = {text};\n")
    print(f"wrote _data/fixture.js: {len(text) / 1e6:.2f} MB, {len(fixture['traces'])} traces, "
          f"{fixture['tasks_used']} tasks, {len(excluded)} excluded")


if __name__ == "__main__":
    main()
