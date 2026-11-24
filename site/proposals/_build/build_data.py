"""Build the five proposals' shared fixture (`../_data/fixture.js`) from the ruler's own runs.

    cd ~/trajectory_tracking_agent && uv run python site/proposals/_build/build_data.py

Sources, all written by `tta evaluate` (lane E), read-only here:
- `ledger.jsonl`: the ranking and holdout − dev (`trajectory_tracking_agent.ledger.leaderboard_rows`);
- `solutions/<id>/scorecard.json`: every solution's per-task KPIs and gate verdicts;
- `outputs/runs/<id>/dev/<task>.json` (`tta.run_record/1`): one task's samples on the target's 100 Hz grid plus the
  ruler's metrics and gates for it.

Every number shown comes from those files or from `trajectory_tracking_agent.ruler.metrics` / `.gates` applied to the
record's samples; this script asserts that the ruler, re-run on the record, gives back the record's own numbers.

WHY outputs only (Zach, 2026-11-24): "KEY OF COURSE IS THAT THE BLACKBOX VIZ IS NOT RELATED TO THE SOLUTION ONLY TO THE
METRICS OUT". Read: target, measured joint states, applied torques, deployment (caps, limits, floor, tool FK), ruler.
Never read: the record's `tau_command_ff` (a controller's feed-forward command) or anything in `solution.py`.

WHY the violation flags are drawn but not re-counted: the record is the 100 Hz target grid, while saturation, limits
and floor are scored on every 4 kHz physics sample (the record's `grids` note). The pages draw where the 100 Hz samples
cross the limits and quote the gate's own 4 kHz count.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from trajectory_tracking_agent import ledger
from trajectory_tracking_agent.ruler import gates as G
from trajectory_tracking_agent.ruler import metrics as M

HERE = Path(__file__).resolve().parent
PROPOSALS = HERE.parent
REPO = PROPOSALS.parent.parent
RUNS = REPO / "outputs" / "runs"
SOLUTIONS = REPO / "solutions"

FEATURED_TASK = "workspace-dev-029"  # via points, one stop: the best solution tracks at ~1.1 mm, p9 and p10 fail 4 gates
TRACED = ("p4s", "p2", "p1", "p9", "p10")
FEATURED_FAILING = "p10"  # fails four of the five gates on the featured task (completed, stop, saturation, limits)  # full traces shipped: the best, a weaker admissible one, and the three failing
JOINTS = ("shoulder pan", "shoulder lift", "elbow", "wrist 1", "wrist 2", "wrist 3")
LINKS = ("base", "shoulder", "upper arm", "forearm", "wrist 1", "wrist 2", "wrist 3", "tool point")


class Kinematics:
    """The deployment's FK (robot_controllers' UR5e, tool site 0.1 m along wrist 3): the tool point and link origins."""

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
        out = np.zeros((len(q), 8, 3))
        for i, row in enumerate(q):
            self.data.qpos[:] = row
            self.mj.mj_kinematics(self.model, self.data)
            out[i, 1:7] = self.data.xpos[self.bodies]
            out[i, 7] = self.data.site_xpos[self.site]
        return out


def r(x, nd=4):
    if x is None:
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    x = float(x)
    return None if not math.isfinite(x) else round(x, nd)


def rows(a, nd):
    return np.round(np.asarray(a, float), nd).tolist()


def intervals(mask):
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        if start is not None and (not m or i == len(mask) - 1):
            out.append([start, i if m else i - 1])
            start = None
    return out


def pooled_max(values, bins):
    edges = np.linspace(0, len(values), bins + 1).astype(int)
    return [float(values[a:b].max()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]


def close(a, b, rel=2e-4, abs_=1e-5):
    return a is not None and b is not None and abs(a - b) <= max(abs_, rel * abs(b))


def load_record(solution, task):
    path = RUNS / solution / "dev" / f"{task}.json"
    return json.loads(path.read_text()) if path.exists() else None


def arrays(rec):
    a = {k: np.asarray(rec[k], float) for k in ("t", "q", "qd", "tau", "q_target", "qd_target", "tool_xyz", "tool_target_xyz")}
    a["caps"] = np.asarray(rec["tau_cap"], float)
    a["q_min"], a["q_max"], a["qd_max"] = (np.asarray(rec[k], float) for k in ("q_min", "q_max", "qd_max"))
    return a


def ruler_check(rec, a):
    """Re-run the ruler on the record's samples; it must give back the record's own numbers."""
    m = rec["metrics"]
    moving = M.moving_mask(a["t"], a["tool_target_xyz"], a["qd_target"])
    assert (moving == np.asarray(rec["moving"], bool)).all(), "moving mask"
    stops = M.stop_windows(a["t"], moving)
    assert [list(map(float, s)) for s in stops] == [list(map(float, s)) for s in rec["stops"]], "stops"
    checks = {
        "tool_track_rms_mm": M.tool_track_rms_mm(a["tool_target_xyz"], a["tool_xyz"], moving),
        "tool_track_max_mm": M.tool_track_max_mm(a["tool_target_xyz"], a["tool_xyz"], moving),
        "stop_error_max_mm": M.stop_error_max_mm(a["t"], a["tool_target_xyz"], a["tool_xyz"], stops),
        "joint_track_rms_deg": M.joint_track_rms_deg(a["q_target"], a["q"], moving),
    }
    for key, value in checks.items():
        # WHY 2e-4 mm: the record stores positions rounded to 1e-7 m (0.1 µm), so a re-run on it can differ by that much
        assert close(value, m[key], rel=1e-4, abs_=2e-4), f"{rec['solution']}/{rec['task']}: {key} {value} vs {m[key]}"
    assert G.gate_verdicts(m) == rec["gates"], "gate verdicts"
    return moving, stops


def trace_payload(rec, kin):
    a = arrays(rec)
    moving, stops = ruler_check(rec, a)
    t, n = a["t"], len(a["t"])
    dt = np.diff(t)
    assert np.allclose(dt, dt[0], atol=1e-9), "uniform 100 Hz grid"
    mpts, tpts = kin.points(a["q"]), kin.points(a["q_target"])
    fk_gap = float(np.abs(mpts[:, 7] - a["tool_xyz"]).max())
    assert fk_gap < 2e-6, f"FK vs record tool point {fk_gap} m"  # the FK here is the ruler's tool point
    err = 1e3 * M.tool_errors_m(a["tool_target_xyz"], a["tool_xyz"])
    sat = (np.abs(a["tau"]) >= M.SATURATION_FRACTION * a["caps"]).any(axis=1)
    lim = ((a["q"] < a["q_min"]) | (a["q"] > a["q_max"]) | (np.abs(a["qd"]) > M.VELOCITY_LIMIT_ALLOWANCE * a["qd_max"])).any(axis=1)
    assert int(lim.sum()) == M.limit_violations(a["q"], a["qd"], a["q_min"], a["q_max"], a["qd_max"]), "100 Hz limit flags"
    assert math.isclose(100 * sat.mean(), M.saturation_share_pct(a["tau"], a["caps"]), rel_tol=1e-9), "100 Hz saturation flags"
    lowest = mpts[:, 1:, 2].min(axis=1)
    below = lowest < rec["floor_z"]
    stop_rows = M.stop_errors_mm(t, a["tool_target_xyz"], a["tool_xyz"], stops)
    joint_err = np.degrees(a["q_target"] - a["q"])
    joint_rms = np.sqrt(np.mean(joint_err[moving] ** 2, axis=0))
    assert close(float(joint_rms.max()), rec["metrics"]["joint_track_rms_deg"], rel=1e-4), "per-joint RMS"
    m = rec["metrics"]
    kpis = {
        "tool_track_rms_mm": r(m["tool_track_rms_mm"], 5), "tool_track_max_mm": r(m["tool_track_max_mm"], 5),
        "stop_error_max_mm": r(m["stop_error_max_mm"], 5), "stop_error_mm": r(m["stop_error_mm"], 5),
        "saturation_share_pct": r(m["saturation_share_pct"], 4), "limit_violations": int(m["limit_violations"]),
        "floor_clearance": int(m["floor_clearance_violations"]), "completed": bool(m["completed"]),
        "joint_track_rms_deg": r(m["joint_track_rms_deg"], 5), "tool_lag_ms": r(m["tool_lag_ms"], 3),
        "energy_j": r(m["energy_j"], 3), "settle_error_max_mm": r(m.get("settle_error_max_mm"), 4),
        "moving_samples": int(m["moving_samples"]),
        # from the 100 Hz record (display only; the gates count 4 kHz samples)
        "sat_samples_100hz": int(sat.sum()), "lim_samples_100hz": int(lim.sum()),
        "torque_peak_pct": r(100 * (np.abs(a["tau"]) / a["caps"]).max(), 2),
        "velocity_peak_pct": r(100 * (np.abs(a["qd"]) / a["qd_max"]).max(), 2),
        "min_clearance_mm": r(1e3 * (lowest.min() - rec["floor_z"]), 2),
        "duration_s": r(t[-1], 3), "samples": n,
    }
    idx = np.arange(n)
    tail = lambda b: (t >= b - M.HOLD_WINDOW_S - 1e-9) & (t <= b + 1e-9)  # noqa: E731
    return {
        "solution": rec["solution"], "task": rec["task"], "kind": rec["kind"],
        "source": f"outputs/runs/{rec['solution']}/dev/{rec['task']}.json",
        "t0": r(t[0], 6), "dt": r(dt[0], 6), "n": n,
        "kpis": kpis, "gates": rec["gates"], "passed": all(rec["gates"].values()), "notes": rec.get("notes", []),
        "joint_rms_deg": [r(v, 5) for v in joint_rms],
        "stops": [[r(x, 4), r(y, 4)] for x, y in stops],
        "stop_errors_mm": [r(v, 5) for v in stop_rows],
        "stop_points_mm": [{"target": rows(1e3 * a["tool_target_xyz"][tail(y)].mean(axis=0), 4),
                            "rest": rows(1e3 * a["tool_xyz"][tail(y)].mean(axis=0), 4)} for x, y in stops],
        "peak_err_i": int(np.argmax(np.where(moving, err, -1))),
        "lowest_i": int(np.argmin(lowest)), "lowest_link": int(np.argmin(mpts[int(np.argmin(lowest)), 1:, 2])) + 1,
        "full": {"err_mm": rows(err, 5), "lowest_mm": rows(1e3 * (lowest - rec["floor_z"]), 1),
                 "moving": intervals(moving), "sat": intervals(sat), "lim": intervals(lim), "below": intervals(below)},
        "every": 1, "idx": idx.tolist(),
        "arm_mm": rows(1e3 * mpts, 1), "target_arm_mm": rows(1e3 * tpts, 1),
        "tool_mm": rows(1e3 * a["tool_xyz"], 4), "target_tool_mm": rows(1e3 * a["tool_target_xyz"], 4),
        "q_deg": rows(np.degrees(a["q"]), 3), "target_q_deg": rows(np.degrees(a["q_target"]), 3),
        "err_deg": rows(np.degrees(a["q"] - a["q_target"]), 5),
        "tau_pct": rows(100 * a["tau"] / a["caps"], 2), "qd_pct": rows(100 * a["qd"] / a["qd_max"], 2),
        "power_w": rows(a["tau"] * a["qd"], 2),
    }


def population():
    board = ledger.leaderboard_rows()
    out = []
    for row in board:
        sid = row["solution"]
        card_path = SOLUTIONS / sid / "scorecard.json"
        if not card_path.exists():
            continue
        card = json.loads(card_path.read_text())
        meta_path = SOLUTIONS / sid / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        assert close(card["objective"], row["objective_dev"], rel=1e-9), f"{sid}: scorecard vs ledger objective"
        assert card["admissible"] == row["admissible"], f"{sid}: admissible"
        tasks = []
        for tk in card["tasks"]:
            rec = load_record(sid, tk["task"])
            spark = spark_moving = None
            if rec is not None:
                err = 1e3 * M.tool_errors_m(np.asarray(rec["tool_target_xyz"]), np.asarray(rec["tool_xyz"]))
                mv = np.asarray(rec["moving"], bool)
                spark = [r(v, 3) for v in pooled_max(np.where(mv, err, 0.0), 60)]
                spark_moving = [int(v > 0) for v in pooled_max(mv.astype(float), 60)]
            k, d = tk["kpis"], tk["diagnostics"]
            tasks.append({
                "task": tk["task"], "kind": tk.get("kind"), "duration_s": r(tk.get("duration_s"), 3),
                "tool_track_rms_mm": r(tk["objective"], 5), "tool_track_max_mm": r(d.get("tool_track_max_mm"), 4),
                "stop_error_max_mm": r(k.get("stop_error_max_mm"), 5), "saturation_share_pct": r(k.get("saturation_share_pct"), 4),
                "limit_violations": k.get("limit_violations"), "floor_clearance": k.get("floor_clearance_violations"),
                "completed": k.get("completed"), "tool_lag_ms": r(d.get("tool_lag_ms"), 3),
                "joint_track_rms_deg": r(d.get("joint_track_rms_deg"), 5), "energy_j": r(d.get("energy_j"), 3),
                "moving_samples": d.get("moving_samples"), "gates": tk["verdicts"], "passed": all(tk["verdicts"].values()),
                "notes": tk.get("notes", [])[:1], "spark_err_mm": spark, "spark_moving": spark_moving,
                "source": f"solutions/{sid}/scorecard.json",
            })
        assert G.admissible([x["gates"] for x in tasks]) == card["admissible"], f"{sid}: admissible from verdicts"
        out.append({
            "id": sid, "rank": row["rank"], "objective": r(card["objective"], 5), "admissible": card["admissible"],
            "gate_pass_rate": r(card["gate_pass_rate"], 4), "failed_gates": card["failed_gates"],
            "tasks_passed": sum(1 for x in tasks if x["passed"]), "objective_holdout": r(row["objective_holdout"], 5),
            "holdout_minus_dev": r(row["holdout_minus_dev"], 5), "change": meta.get("change", ""), "parent": meta.get("parent"),
            "evaluated": card.get("evaluated"), "tasks": tasks,
        })
    return out


INPUTS = [
    ["target trajectory", "target joint positions and velocities (the task's tape, 100 Hz)"],
    ["measured joint states", "joint positions and velocities from the encoders"],
    ["applied torques", "joint torques the boards applied"],
    ["deployment", "torque caps, joint position and velocity limits, the floor plane, the tool-point FK"],
    ["ruler v1", "the objective, the five gates and their thresholds (trajectory_tracking_agent.ruler)"],
]
NOT_USED = "controller internals: the commanded feed-forward, gains, models, observers, anything in solution.py"


def main():
    kin = Kinematics()
    pop = population()
    # the ledger's best always ships in full (a generation-1 winner included), then the fixed comparison set
    best = next(p["id"] for p in pop if p["admissible"])
    traced = [s for s in dict.fromkeys([best, *TRACED]) if load_record(s, FEATURED_TASK) is not None]
    traces = {}
    for sid in traced:
        rec = load_record(sid, FEATURED_TASK)
        traces[sid] = trace_payload(rec, kin)
    first = load_record(traced[0], FEATURED_TASK)
    card = json.loads((SOLUTIONS / traced[0] / "scorecard.json").read_text())
    dep = card["deployment"]
    fixture = {
        "generated_by": "site/proposals/_build/build_data.py",
        "ruler": "v1 (OBJECTIVES.md §4)",
        "ruler_source": "trajectory_tracking_agent.ruler.metrics and .gates (re-run on every shipped record: same numbers)",
        "robot": "UR5e (MuJoCo Menagerie, robot_controllers truth plant), simulated",
        "deployment_title": dep.get("title", "ur5e_alone"),
        "dataset": f"{card['dataset']['name']} · {card['dataset']['split']} · speed {card['dataset']['speed']}",
        "tasks_total": card["dataset"]["tasks"],
        "source_repo": "this repo: ledger.jsonl, solutions/*/scorecard.json, outputs/runs/*/dev/*.json",
        "grids": first.get("grids", {}),
        "inputs": INPUTS,
        "not_used": NOT_USED,
        "deployment": {
            "tau_cap_nm": first["tau_cap"], "q_limit_deg": [r(math.degrees(v), 1) for v in first["q_max"]],
            "qd_max_deg_s": [r(math.degrees(v), 1) for v in first["qd_max"]], "joints": list(JOINTS), "links": list(LINKS),
            "floor_z_mm": 1e3 * first["floor_z"], "host_rate_hz": dep.get("host_rate_hz"),
            "tool_point": "flange site `tool`, 0.1 m along wrist 3 (robot_controllers.bench.ur5e)",
        },
        "thresholds": {"stop_error_max_mm": G.STOP_ERROR_MAX_MM, "saturation_share_pct": G.SATURATION_SHARE_MAX_PCT,
                       "sat_fraction": M.SATURATION_FRACTION, "vel_margin": M.VELOCITY_LIMIT_ALLOWANCE,
                       "stop_min_s": M.MIN_STOP_S, "stop_tail_s": M.HOLD_WINDOW_S,
                       "moving_tool_mm_s": 1e3 * M.MOVING_TOOL_SPEED_M_S, "moving_joint_deg_s": round(math.degrees(M.MOVING_JOINT_SPEED_RAD_S), 4)},
        "featured_task": FEATURED_TASK,
        "featured_failing": FEATURED_FAILING if FEATURED_FAILING in traces else traced[-1],
        "tasks_used": card["dataset"]["tasks"],
        "ledger_rows": len(ledger.rows()),
        "population": pop,
        "traces": traces,
    }
    text = json.dumps(fixture, separators=(",", ":"), allow_nan=False)
    out = PROPOSALS / "_data" / "fixture.js"
    out.write_text("// generated by site/proposals/_build/build_data.py from the ruler's runs: do not edit\n"
                   f"window.FIXTURE = {text};\n")
    for s in pop:
        print(f'{s["rank"]:>2} {s["id"]:<8} {s["objective"]:.4f} adm={s["admissible"]} {s["tasks_passed"]}/{len(s["tasks"])} {({g: n for g, n in s["failed_gates"].items() if n})}')
    for sid, tr in traces.items():
        print(sid, tr["task"], tr["kpis"]["tool_track_rms_mm"], [g for g, v in tr["gates"].items() if not v])
    print(f"wrote {out.relative_to(REPO)}: {len(text) / 1e6:.2f} MB · {len(pop)} solutions · {len(traces)} traces")


if __name__ == "__main__":
    main()
