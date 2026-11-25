#!/usr/bin/env python3
"""The run-record fold: a box's saved runs at a git ref -> bb-run/1 records + a state.json that lists them (CONTRACT §4, §14).

    python3 viewer/tools/fold_runs.py            # every set in viewer/scenarios/runs/runs.json
    python3 viewer/tools/fold_runs.py --check    # re-fold, compare byte for byte, write nothing

Stdlib only and read-only on the boxes, like fold_state.py: every source file through `git show <ref>:<path>`, never a
working tree, so the same ref folds to the same bytes. It writes `scenarios/runs/<set>/state.json` (the scenario's
bb-state/1 header + a `playback` slice listing the records) and one `<solution>.json` (bb-run/1) per run. What it reads
is a box's outputs only (Zach, 2026-11-24: "the blackbox viz is not related to the solution, only to the metrics out"):
the runs the box's own export saved, never a solution's code. Every number comes from those files; nothing is typed.

Three sets (runs.json):
- `tta-best-vs-failing`: trajectory_tracking_agent @ 9ead945, its saved playback (site/data/playback/, written by its
  tools/build_site.py from `tta evaluate`'s run records). The best admissible solution and p10 (the failing one the
  brief names) on the first dev task where p10 fails the most gates. Per-frame geometry is the box's own: geom poses
  its build computed natively with the deployment's MuJoCo model (the browser only plays them back).
- `rc-hero`: robot_controllers' three hero episodes as the seam lane re-ran them with robot_controllers' own code
  (blackbox_agent @ its ref: proposals/_data/rc/), labelled as re-runs, with the ledger's numbers beside them.
- `empty`: a real bb-run/1 record of a run that saved no samples and no metrics (the component's empty state).

A video beside a record (`<solution>.webm` / `.mp4`, rendered by adapters/robot_msgs/tools/render_run_video.py from the
record's own joint-angle channel) is listed in the record's `scene.video` when the file exists (its sha256 too).
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIEWER = HERE.parent
RUNS = VIEWER / "scenarios" / "runs"
SCENARIOS = VIEWER / "scenarios"
HEADER = ("schema", "box", "ref", "read_at", "ref_date", "about", "objective")
MAGIC = b"TTAPLAY1"
FOLD = "viewer/tools/fold_runs.py"


# ── reading a repo at a ref ─────────────────────────────────────────────────────────────────────────────────


class Repo:
    def __init__(self, path: str, ref: str):
        self.path = str(Path(path).expanduser())
        self.name = Path(self.path).name
        self.ref = ref
        self.read: list[str] = []

    def bytes(self, path: str) -> bytes:
        out = subprocess.run(["git", "-C", self.path, "show", f"{self.ref}:{path}"], capture_output=True)
        if out.returncode:
            raise FileNotFoundError(f"{self.name}@{self.ref}:{path}: {out.stderr.decode().strip()}")
        self.read.append(path)
        return out.stdout

    def json(self, path: str):
        return json.loads(self.bytes(path))

    def where(self, path: str) -> str:
        return f"{self.name}@{self.ref}:{path}"


# ── the trajectory_tracking_agent playback codec (site/assets/playback.js and build_site.read_playback, in stdlib) ──


def _unpack(payload: bytes, spec: dict) -> list[int]:
    size = int(spec["dtype"][1:]) // 8
    shape = spec["shape"]
    count = 1
    for s in shape:
        count *= s
    planes = payload[spec["offset"]: spec["offset"] + spec["bytes"]]
    raw = bytearray(count * size)
    for b in range(size):  # bytes split into planes, low first
        raw[b::size] = planes[b * count:(b + 1) * count]
    diffs = struct.unpack(f"<{count}{ {1: 'b', 2: 'h', 4: 'i'}[size] }", bytes(raw))
    rows = shape[0]
    cols = count // rows
    out = [0] * count  # row-major (N, cols); each column stored contiguous as its first difference along time
    for c in range(cols):
        s = 0
        for i in range(rows):
            s += diffs[c * rows + i]
            out[i * cols + c] = s
    return out


def read_playback(blob: bytes, base: dict | None = None):
    """(header, {name: (values, shape)}, {name: ints}) of one playback file."""
    data = gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob
    if data[:8] != MAGIC:
        raise ValueError("not a TTAPLAY1 playback file")
    n = struct.unpack("<I", data[8:12])[0]
    header = json.loads(data[12:12 + n])
    payload = data[12 + n:]
    ints, arrays = {}, {}
    for name, spec in header["arrays"].items():
        v = _unpack(payload, spec)
        if spec.get("base"):
            b = base[spec["base"]]
            v = [x + y for x, y in zip(v, b)]
        ints[name] = v
        arrays[name] = ([x * spec["step"] for x in v], spec["shape"])
    return header, arrays, ints


def nest(flat_shape):
    """(values, shape) -> nested lists (rows; rows of columns; rows of [k][j])."""
    values, shape = flat_shape
    if len(shape) == 1:
        return list(values)
    width = len(values) // shape[0]
    rows = [values[i * width:(i + 1) * width] for i in range(shape[0])]
    if len(shape) == 3:
        inner = shape[2]
        return [[row[g * inner:(g + 1) * inner] for g in range(shape[1])] for row in rows]
    return rows


# ── small numeric helpers (stdlib) ──────────────────────────────────────────────────────────────────────────


def rnd(x, nd):
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, (list, tuple)):
        return [rnd(v, nd) for v in x]
    x = float(x)
    if not math.isfinite(x):
        return None
    v = round(x, nd)
    return 0.0 if v == 0 else v


def intervals_to_windows(intervals, t, dt):
    """[[t0, t1]] sample-time intervals (inclusive) -> windows covering each sample's own slot."""
    return [[rnd(a, 6), rnd(b + dt, 6)] for a, b in intervals]


def mask_windows(mask, t, dt):
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = t[i]
        if start is not None and (not m or i == len(mask) - 1):
            end = t[i] if not m else t[i] + dt
            out.append([rnd(start, 6), rnd(end, 6)])
            start = None
    return out


def interp(xs, ys, x):
    """numpy.interp for one x (xs increasing; clamped at the ends)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    k = bisect.bisect_right(xs, x) - 1
    a, b = xs[k], xs[k + 1]
    f = (x - a) / (b - a) if b > a else 0.0
    return ys[k] + f * (ys[k + 1] - ys[k])


def percentile(values, q):
    """numpy.percentile's default (linear) on a list."""
    s = sorted(values)
    pos = (len(s) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def close(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def peak_of(t, values, counted=None, label="peak"):
    best = None
    for i, v in enumerate(values):
        if v is None or (counted is not None and not counted[i]):
            continue
        if best is None or v > values[best]:
            best = i
    return None if best is None else {"t": rnd(t[best], 6), "i": best, "value": values[best], "label": label}


def peak(t, values, counted=None, nd=4):
    """The worst sample (largest value) among the counted ones: {t, i, value}; the component writes its label."""
    pk = peak_of(t, values, counted, None)
    return pk and {"t": pk["t"], "i": pk["i"], "value": rnd(pk["value"], nd)}


def video_of(out_dir: Path, stem: str, note: str):
    """The scene.video block when render_run_video.py has written the files beside the record."""
    sources = []
    for ext, kind in (("webm", "video/webm"), ("mp4", "video/mp4")):
        f = out_dir / f"{stem}.{ext}"
        if f.exists():
            sources.append({"src": f.name, "type": kind, "bytes": f.stat().st_size, "sha256": sha256(f)})
    meta = out_dir / f"{stem}.video.json"
    if not sources or not meta.exists():
        return None
    m = json.loads(meta.read_text())
    return {"sources": sources, "t0": m["t0"], "rate": m["rate"], "fps": m["fps"], "width": m["width"], "height": m["height"],
            "label": m["label"], "made_by": m["made_by"], "channel": m["channel"], "note": note}


# ── trajectory_tracking_agent: ruler v1 as bb-run/1 metrics ─────────────────────────────────────────────────

def joint_label(name: str) -> str:
    """'shoulder_pan_joint' -> 'shoulder pan' (bb_run_robot_msgs.joint_label: the two agree)."""
    return name.removesuffix("_joint").replace("_", " ")


def tta_record(repo: Repo, index: dict, solution: str, task: str, label: str) -> dict:
    trow = next(r for r in index["tasks"] if r["id"] == task)
    srow = next(s for s in index["solutions"] if s["id"] == solution)
    th, ta, ti = read_playback(repo.bytes(f"site/data/playback/{trow['file']}"))
    rh, ra, _ = read_playback(repo.bytes(f"site/data/playback/{srow['tasks'][task]['file']}"), ti)
    if rh["missing"]:
        raise ValueError(f"{solution}/{task}: rows with no measurement {rh['missing']}: not handled")
    dep = index["deployment"]
    thr = dep["thresholds"]
    t = [rnd(x, 6) for x in nest(ta["t"])]
    n = len(t)
    dt = round(t[1] - t[0], 6)
    moving = [bool(x) for x in nest(ta["moving"])]
    q_t, q = nest(ta["q_target"]), nest(ra["q"])
    qd, tau = nest(ra["qd"]), nest(ra["tau"])
    tool_t, tool = nest(ta["tool_target"]), nest(ra["tool"])
    err = nest(ra["error_mm"])
    lowest = nest(ra["lowest"])
    m, gates, ex = rh["metrics"], rh["gates"], rh["explain"]
    caps, qd_max = dep["tau_cap"], dep["qd_max"]
    names = list(dep["joint_names"])
    cols = [joint_label(x) for x in names]
    deg = 180.0 / math.pi
    tau_pct = [[100 * abs(v) / c for v, c in zip(row, caps)] for row in tau]
    qd_pct = [[100 * abs(v) / c for v, c in zip(row, qd_max)] for row in qd]
    torque_peak = [max(r) for r in tau_pct]
    speed_peak = [max(r) for r in qd_pct]
    clearance = [1e3 * (p[2] - dep["floor_z"]) for p in lowest]
    joint_err = [max(abs(a - b) * deg for a, b in zip(r1, r2)) for r1, r2 in zip(q, q_t)]
    power = [sum(max(0.0, a * b) for a, b in zip(r1, r2)) for r1, r2 in zip(tau, qd)]
    # the ruler's own numbers re-read from the record: RMS over the moving samples, the stops' hold windows
    rms = math.sqrt(sum(e * e for e, mv in zip(err, moving) if mv) / max(1, sum(moving)))
    assert close(rms, m["tool_track_rms_mm"], 1e-3), f"{solution}/{task}: RMS {rms} vs ruler {m['tool_track_rms_mm']}"
    stops = ex["stops"]
    for s in stops:
        assert close(s["error_mm"], m["stop_error_max_mm"], 1e-3) or s["error_mm"] <= m["stop_error_max_mm"] + 1e-3
    windows = [{"id": f"stop-{k + 1}", "label": f"stop {k + 1}", "kind": "stop", "t0": rnd(s["t0"], 6), "t1": rnd(s["t1"], 6)}
               for k, s in enumerate(stops)]
    end = t[-1]
    settle_from = rnd(end - dep["hold_window_s"], 6)
    sat_w = intervals_to_windows(ex["saturated_intervals"], t, dt)
    lim_w = intervals_to_windows(ex["limit_intervals"], t, dt)
    floor_w = intervals_to_windows(ex["floor_intervals"], t, dt)
    worst_stop = max(stops, key=lambda s: s["error_mm"]) if stops else None
    peak_err = peak_of(t, err, moving, "peak")
    settle_mask = [x >= settle_from - 1e-9 for x in t]
    settle_peak = peak_of(t, err, settle_mask, "at the end")
    sub = ex["subset"]

    def mm(v):
        return f"{v:.3g} mm"

    metrics = [
        {"id": "tool_track_rms_mm", "label": "Tool tracking error", "kind": "objective", "value": rnd(m["tool_track_rms_mm"], 6),
         "unit": "mm", "direction": "lower", "gate": None, "passed": None,
         "rule": "RMS distance between the measured and the target tool point at the same instant, over the moving samples "
                 "(grey = at rest, not counted). The box's objective is the median of this over its dev tasks.",
         "evidence": {"channel": "tool_error", "counted": {"mask": [1 if v else 0 for v in moving]},
                      "reference": {"value": rnd(m["tool_track_rms_mm"], 6), "label": "RMS"},
                      "peak": peak_err and {**peak_err, "value": rnd(peak_err["value"], 5), "label": f"peak {mm(peak_err['value'])}"},
                      "points": "tool", "whiskers": ["tool_target", "tool"], "detail": "q"}},
        {"id": "completed", "label": "Completed", "kind": "gate", "value": bool(m["completed"]), "unit": None,
         "display": "finished, settled" if m["completed"] else "did not settle", "direction": "pass",
         "gate": {"op": "is", "threshold": True}, "passed": bool(gates["completed"]),
         "rule": f"no crash or NaN, reaches the end, and the tool settles within {thr['stop_error_max_mm'][1]:g} mm over the last "
                 f"{dep['hold_window_s']:g} s" + (f" · {rh['notes'][0]}" if rh["notes"] else ""),
         "evidence": {"channel": "tool_error", "counted": {"windows": [[settle_from, rnd(end + dt, 6)]]},
                      "threshold": thr["stop_error_max_mm"][1],
                      "flags": [] if gates["completed"] else [[settle_from, rnd(end + dt, 6)]],
                      "peak": settle_peak and {**settle_peak, "value": rnd(settle_peak["value"], 5), "label": f"{mm(settle_peak['value'])} at the end"},
                      "points": "tool"}},
        {"id": "stop_error_max_mm", "label": "Stop error", "kind": "gate", "value": rnd(m["stop_error_max_mm"], 6), "unit": "mm",
         "direction": "lower", "gate": {"op": thr["stop_error_max_mm"][0], "threshold": thr["stop_error_max_mm"][1]},
         "passed": bool(gates["stop_error_max_mm"]),
         "rule": f"≤ {thr['stop_error_max_mm'][1]:g} mm at every stop: the distance between the mean measured and the mean target "
                 f"tool point over the stop's last {dep['hold_window_s']:g} s",
         "evidence": {"channel": "tool_error", "counted": {"windows": [[rnd(s["hold"][0], 6), rnd(s["hold"][1] + dt, 6)] for s in stops]},
                      "threshold": thr["stop_error_max_mm"][1],
                      "flags": [[rnd(s["hold"][0], 6), rnd(s["hold"][1] + dt, 6)] for s in stops if s["error_mm"] > thr["stop_error_max_mm"][1]],
                      "peak": worst_stop and {"t": rnd(worst_stop["t1"], 6), "value": rnd(worst_stop["error_mm"], 5),
                                              "label": f"stop error {mm(worst_stop['error_mm'])}",
                                              "at": [rnd(1e3 * v, 3) for v in worst_stop["mean_xyz"]], "unit_at": "mm"},
                      "points": "tool"}},
        {"id": "saturation_share_pct", "label": "Torque saturation", "kind": "gate", "value": rnd(m["saturation_share_pct"], 5),
         "unit": "%", "direction": "lower", "gate": {"op": thr["saturation_share_pct"][0], "threshold": thr["saturation_share_pct"][1]},
         "passed": bool(gates["saturation_share_pct"]),
         "rule": f"≤ {thr['saturation_share_pct'][1]:g} % of physics samples ({dep['plant_rate_hz'] / 1e3:g} kHz) with any joint "
                 f"≥ {100 * dep['saturation_fraction']:g} % of its torque cap. The lane draws the {dep['record_rate_hz']:g} Hz record "
                 f"({sub['saturation_share_pct']['record_samples']} flagged samples here); the gate counts every physics sample.",
         "evidence": {"channel": "torque_peak", "counted": {"all": True}, "threshold": 100 * dep["saturation_fraction"],
                      "flags": sat_w, "peak": peak(t, torque_peak), "detail": "tau_pct", "points": "tool"}},
        {"id": "limit_violations", "label": "Joint limits", "kind": "gate", "value": int(m["limit_violations"]), "unit": "samples",
         "direction": "lower", "gate": {"op": thr["limit_violations"][0], "threshold": thr["limit_violations"][1]},
         "passed": bool(gates["limit_violations"]),
         "rule": f"0 physics samples outside a position limit or above {dep['velocity_allowance']:g} × a velocity limit "
                 f"({sub['limit_violations']['record_samples']} of the record's samples flagged; the gate counts every physics sample)",
         "evidence": {"channel": "speed_peak", "counted": {"all": True}, "threshold": 100 * dep["velocity_allowance"],
                      "flags": lim_w, "peak": peak(t, speed_peak), "detail": "qd_pct", "points": "tool"}},
        {"id": "floor_clearance", "label": "Floor clearance", "kind": "gate", "value": int(m["floor_clearance_violations"]),
         "unit": "samples", "direction": "lower", "gate": {"op": thr["floor_clearance"][0], "threshold": thr["floor_clearance"][1]},
         "passed": bool(gates["floor_clearance"]),
         "rule": "0 physics samples with the tool point or any link origin below the floor; the lane is the lowest moving point's "
                 "height above the floor",
         "evidence": {"channel": "clearance", "counted": {"all": True}, "threshold": 0.0, "flags": floor_w, "lower_is_worse": True,
                      "peak": {"t": rnd(ex["lowest"]["t"], 6), "value": rnd(1e3 * (ex["lowest"]["z"] - dep["floor_z"]), 2),
                               "label": f"lowest {1e3 * (ex['lowest']['z'] - dep['floor_z']):.0f} mm above the floor",
                               "at": [rnd(1e3 * v, 2) for v in ex["lowest"]["xyz"]], "unit_at": "mm"}}},
        {"id": "joint_track_rms_deg", "label": "Joint tracking (worst joint)", "kind": "diagnostic", "value": rnd(m["joint_track_rms_deg"], 5),
         "unit": "°", "direction": "lower", "gate": None, "passed": None,
         "rule": "RMS joint angle error over the moving samples, the worst of the six joints; the lane is the largest joint error at each sample",
         "evidence": {"channel": "joint_error", "counted": {"mask": [1 if v else 0 for v in moving]}, "detail": "q",
                      "peak": peak(t, joint_err, moving)}},
        {"id": "tool_lag_ms", "label": "Tool lag", "kind": "diagnostic", "value": rnd(m["tool_lag_ms"], 4), "unit": "ms",
         "direction": "lower", "gate": None, "passed": None,
         "rule": "how late the measured motion runs behind the target (joint trajectories cross-correlated, robot_msgs.compare)",
         "evidence": None},
        {"id": "energy_j", "label": "Motor energy", "kind": "diagnostic", "value": rnd(m["energy_j"], 4), "unit": "J",
         "direction": "lower", "gate": None, "passed": None,
         "rule": "positive mechanical work: torque × velocity where positive, summed over joints, integrated over time "
                 "(the lane is that power at the record's samples)",
         "evidence": {"channel": "power", "counted": {"all": True}, "peak": peak(t, power, None, 2)}},
    ]
    events = [{"t": w["t0"], "t1": w["t1"], "kind": "window", "label": w["label"]} for w in windows]
    failed = [mt for mt in metrics if mt["passed"] is False]
    for mt in failed:
        fl = mt["evidence"]["flags"] if mt.get("evidence") else []
        if fl:
            events.append({"t": fl[0][0], "t1": fl[0][1], "kind": "fail", "metric": mt["id"],
                           "label": f"{mt['label']} fails" + (f" ({len(fl)} spans)" if len(fl) > 1 else "")})
    events.sort(key=lambda e: (e["t"], e["kind"]))
    shapes = [{"type": {3: "capsule", 2: "sphere", 5: "cylinder", 6: "box"}[ty], "size": rnd(sz, 6), "body": b}
              for ty, sz, b in zip(index["geoms"]["type"], index["geoms"]["size"], index["geoms"]["body"])]

    def poses(pos, quat):
        return [[rnd(p + qq, 5) for p, qq in zip(fp, fq)] for fp, fq in zip(pos, quat)]

    geometry = {
        "up": "z", "unit": "m", "shapes": shapes,
        "layers": [
            {"id": "target", "label": "target", "style": "ghost", "poses": poses(nest(ta["geom_pos"]), nest(ta["geom_quat"]))},
            {"id": "measured", "label": "measured", "style": "solid", "poses": poses(nest(ra["geom_pos"]), nest(ra["geom_quat"]))},
        ],
        "paths": [{"channel": "tool_target", "label": "target tool path", "style": "dashed"},
                  {"channel": "tool", "label": "measured tool path", "style": "solid"}],
        "fit": [rnd(p, 4) for p in trow.get("fit_box") or th["fit_box"]],
        "floor": {"z": dep["floor_z"]},
        "made_by": f"{repo.name}'s tools/build_site.py: geom poses from MuJoCo mj_kinematics on the deployment's model, at each sample",
    }
    channels = [
        {"id": "tool_error", "label": "Tool error", "unit": "mm", "values": rnd(err, 5)},
        {"id": "tool_target", "label": "Target tool point", "unit": "m", "columns": ["x", "y", "z"], "role": "target", "pair": "tool",
         "values": rnd(tool_t, 7)},
        {"id": "tool", "label": "Measured tool point", "unit": "m", "columns": ["x", "y", "z"], "role": "measured", "pair": "tool_target",
         "values": rnd(tool, 7)},
        {"id": "q_target", "label": "Target joint angle", "unit": "°", "columns": cols, "names": names, "role": "target", "pair": "q",
         "values": [[rnd(v * deg, 5) for v in r] for r in q_t]},
        {"id": "q", "label": "Measured joint angle", "unit": "°", "columns": cols, "names": names, "role": "measured", "pair": "q_target",
         "values": [[rnd(v * deg, 5) for v in r] for r in q]},
        {"id": "tau_pct", "label": "Applied torque, % of cap", "unit": "%", "columns": cols, "names": names, "values": rnd(tau_pct, 2)},
        {"id": "qd_pct", "label": "Joint speed, % of limit", "unit": "%", "columns": cols, "names": names, "values": rnd(qd_pct, 2)},
        {"id": "torque_peak", "label": "Torque, highest joint, % of its cap", "unit": "%", "values": rnd(torque_peak, 2)},
        {"id": "speed_peak", "label": "Speed, fastest joint, % of its limit", "unit": "%", "values": rnd(speed_peak, 2)},
        {"id": "clearance", "label": "Lowest moving point above the floor", "unit": "mm", "values": rnd(clearance, 2)},
        {"id": "joint_error", "label": "Joint error, worst joint", "unit": "°", "values": rnd(joint_err, 5)},
        {"id": "power", "label": "Positive mechanical power", "unit": "W", "values": rnd(power, 3)},
    ]
    passed = [mt for mt in metrics if mt["passed"] is True]
    return {
        "schema": "bb-run/1",
        "id": f"{solution}/{task}",
        "title": f"{solution} on {task}",
        "subject": {"solution": solution, "task": task, "split": rh["split"], "kind": th["kind"], "label": label,
                    "verdict": f"passes all {len(passed)} gates" if not failed else f"fails {len(failed)} of {len(failed) + len(passed)} gates"},
        "source": {"by": FOLD, "from": [repo.where(f"site/data/playback/{trow['file']}"), repo.where(f"site/data/playback/{srow['tasks'][task]['file']}")],
                   "ruler": rh["ruler"], "record_schema": rh["record_schema"],
                   "note": "the box's saved outputs only (target, measured joints, applied torques, tool points, the ruler's verdicts); "
                           "never a controller's internals"},
        "time": {"unit": "s", "t": t, "rate_hz": dep["record_rate_hz"], "windows": windows},
        "channels": channels,
        "metrics": metrics,
        "events": events,
        "notes": rh["notes"],
        "scene": {"kind": "3d", "geometry": geometry},
    }


def tta_set(spec: dict, out_dir: Path):
    repo = Repo(spec["repo"], spec["ref"])
    index = repo.json("site/data/playback/index.json")
    state = json.loads((SCENARIOS / spec["header_from"] / "state.json").read_text())
    best = state["iterations"][-1]["best_holder"]  # the best admissible solution at this ref (fold_state's verdict rule)
    failing = spec["failing"]
    sols = {s["id"]: s for s in index["solutions"]}
    shared = [t["id"] for t in index["tasks"] if t["id"] in sols[best]["tasks"] and t["id"] in sols[failing]["tasks"]]

    def fails(task):
        b, _, ti = read_playback(repo.bytes(f"site/data/playback/{next(r for r in index['tasks'] if r['id'] == task)['file']}"))
        h, _, _ = read_playback(repo.bytes(f"site/data/playback/{sols[failing]['tasks'][task]['file']}"), ti)
        return sum(1 for v in h["gates"].values() if not v)

    counts = {task: fails(task) for task in shared}
    task = max(shared, key=lambda k: (counts[k], -shared.index(k)))  # the first shared task where it fails the most gates
    rank = {s["id"]: k + 1 for k, s in enumerate(sorted((s for s in index["solutions"] if s["admissible"]), key=lambda s: s["objective"]))}
    runs = []
    for sid, label in ((best, f"best admissible (#{rank.get(best, '?')} on dev)"), (failing, "a failing solution")):
        rec = tta_record(repo, index, sid, task, label)
        stem = sid
        video = video_of(out_dir, stem, "rendered from this record's measured joint-angle channel `q`")
        if video:
            rec["scene"]["video"] = video
            rec["scene"]["screens"] = [{"kind": "3d", "label": "3D replay (precomputed geometry)"},
                                       {"kind": "video", "label": "MuJoCo render (video)"}]
        runs.append((rec, stem))
    return repo, state, runs, {"rule": f"the best admissible solution ({best}) and {failing} on {task}: the first dev task both ship where "
                                       f"{failing} fails the most gates ({counts[task]} of 5)", "task": task}


# ── robot_controllers' hero episodes (re-runs by the seam lane) ─────────────────────────────────────────────


def rc_record(repo: Repo, pop: dict, cid: str, role: str, why: str) -> dict:
    run = repo.json(f"proposals/_data/rc/runs/{cid}.json")
    fr = repo.json(f"proposals/_data/rc/frames/{cid}.json")
    sol = next(s for s in pop["solutions"] if s["id"] == cid)
    box = pop["box"]
    tp, tool = run["t"], run["tool_pos"]
    sent = run["sent_t"]
    ref_tool = run["ref_tool_pos"]
    # the grade's own measure: the reference as sent at each host tick vs the plant's tool interpolated there
    meas = [[interp(tp, [p[k] for p in tool], s) for k in range(3)] for s in sent]
    err = [1e3 * math.dist(a, b) for a, b in zip(ref_tool, meas)]
    p95 = percentile(err, 95)
    rms = math.sqrt(sum(e * e for e in err) / len(err))
    rerun, ledger = run["metrics_rerun"], run["metrics_ledger"]
    # WHY 0.01 mm: the export rounds sent_t to 10 µs, and at ~0.5 m/s that alone moves an interpolated point by ~5 µm
    assert close(p95, rerun["tool_p95_mm"], 1e-2), f"{cid}: p95 from the exported fields {p95} vs re-run {rerun['tool_p95_mm']}"
    t = [rnd(x, 5) for x in sent]
    gate_rows = []
    for g in box["gates"]:
        worst = sol["gate_worst"].get(g["id"])
        gate_rows.append({
            "id": g["id"], "label": g["label"].capitalize(), "kind": "gate", "value": worst, "unit": g["unit"] or None,
            "direction": "higher" if g["op"].startswith(">") else "lower", "gate": {"op": g["op"], "threshold": g["value"]},
            "passed": sol["failed_gates"].get(g["id"], 0) == 0,
            "scope": "the worst of the grade's 20 UR5e scenarios (ledger)",
            "rule": f"{g['means']} on every scenario; this run saved no samples of it, so the lane holds the score only",
            "evidence": None})
    peak = peak_of(t, err, None, "")
    metrics = [
        {"id": "tool_p95_mm", "label": "Tool error p95", "kind": "objective", "value": ledger["tool_p95_mm"], "unit": "mm",
         "direction": "lower", "gate": None, "passed": None, "rerun": rnd(rerun["tool_p95_mm"], 6),
         "rule": f"{box['objective']['detail']}. The number is the ledger's; this replay is a re-run of the episode "
                 f"(re-run p95 {rerun['tool_p95_mm']:.4f} mm).",
         "evidence": {"channel": "tool_error", "counted": {"all": True}, "reference": {"value": rnd(p95, 5), "label": "p95 (re-run)"},
                      "peak": {"t": peak["t"], "i": peak["i"], "value": rnd(peak["value"], 4), "label": f"peak {peak['value']:.3g} mm"},
                      "points": "tool", "whiskers": ["tool_target", "tool"]}},
        {"id": "tool_rms_mm", "label": "Tool error RMS", "kind": "diagnostic", "value": ledger["tool_rms_mm"], "unit": "mm",
         "direction": "lower", "gate": None, "passed": None, "rerun": rnd(rerun["tool_rms_mm"], 6),
         "rule": f"RMS of the same distance at the host ticks (re-run {rerun['tool_rms_mm']:.4f} mm; from the saved samples {rms:.4f} mm)",
         "evidence": {"channel": "tool_error", "counted": {"all": True}, "reference": {"value": rnd(rms, 5), "label": "RMS (re-run)"},
                      "points": "tool"}},
        {"id": "tracking_p95_deg_here", "label": "Joint error p95 (this scenario)", "kind": "diagnostic", "value": ledger["tracking_p95_deg"],
         "unit": "°", "direction": "lower", "gate": None, "passed": None, "rerun": rnd(rerun["tracking_p95_deg"], 6),
         "rule": "95th percentile of the joint angle error on this scenario (ledger); the re-run saved no joint angles, so no lane trace",
         "evidence": None},
        *gate_rows,
    ]
    mpts, tpts = fr["measured"], fr["target"]
    assert len(fr["t"]) == len(t)
    geometry = {
        "up": "z", "unit": "m",
        "layers": [{"id": "target", "label": "reference", "style": "ghost",
                    "chain": {"radii": [0.05, 0.045, 0.04, 0.034, 0.03, 0.028, 0.012], "points": [rnd(f, 5) for f in tpts]}},
                   {"id": "measured", "label": "measured", "style": "solid",
                    "chain": {"radii": [0.05, 0.045, 0.04, 0.034, 0.03, 0.028, 0.012], "points": [rnd(f, 5) for f in mpts]}}],
        "paths": [{"channel": "tool_target", "label": "reference tool path", "style": "dashed"},
                  {"channel": "tool", "label": "measured tool path", "style": "solid"}],
        "floor": {"z": 0.0},
        "made_by": "the seam lane's export (blackbox_agent extract/frames.py): MuJoCo mj_kinematics on robot_controllers' UR5e at the host ticks; "
                   "the chain radii are the proposals' arm3d.js stick-and-capsule drawing",
    }
    passed = sum(1 for m in gate_rows if m["passed"])
    return {
        "schema": "bb-run/1",
        "id": f"{cid}/{pop['hero']['task']}",
        "title": f"{cid} on {pop['hero']['task']} (re-run)",
        "subject": {"solution": cid, "task": pop["hero"]["task"], "split": None, "kind": pop["hero"].get("task_kind"),
                    "label": f"{role}: {why} · re-run", "rerun": True,
                    "verdict": f"passes all {passed} gates on every scenario (ledger)" if passed == len(gate_rows)
                    else f"fails {len(gate_rows) - passed} of {len(gate_rows)} gates (ledger)"},
        "source": {"by": FOLD, "from": [repo.where(f"proposals/_data/rc/runs/{cid}.json"), repo.where(f"proposals/_data/rc/frames/{cid}.json"),
                                       repo.where("proposals/_data/rc/population.json")],
                   "note": run["source"] + ". A RE-RUN: robot_controllers' grade stores no samples, so this episode was run again with "
                           "its own code (seed 0); the scores are the ledger's, the re-run's own beside them."},
        "time": {"unit": "s", "t": t, "rate_hz": None, "windows": []},
        "channels": [
            {"id": "tool_error", "label": "Tool error (reference vs measured, host ticks)", "unit": "mm", "values": rnd(err, 5)},
            {"id": "tool_target", "label": "Reference tool point", "unit": "m", "columns": ["x", "y", "z"], "role": "target", "pair": "tool",
             "values": rnd(ref_tool, 7)},
            {"id": "tool", "label": "Measured tool point", "unit": "m", "columns": ["x", "y", "z"], "role": "measured", "pair": "tool_target",
             "values": [rnd(p, 7) for p in meas]},
        ],
        "metrics": metrics,
        "events": [],
        "notes": [run["decimated"]],
        "scene": {"kind": "3d", "geometry": geometry,
                  "screens": [{"kind": "3d", "label": "three-quarter", "view": "iso"}, {"kind": "3d", "label": "from above", "view": "top"}]},
    }


def rc_set(spec: dict, out_dir: Path):
    repo = Repo(spec["repo"], spec["ref"])
    pop = repo.json("proposals/_data/rc/population.json")
    state = json.loads((SCENARIOS / spec["header_from"] / "state.json").read_text())
    runs = []
    for pick in pop["hero"]["picks"]:
        rec = rc_record(repo, pop, pick["solution"], pick["role"], pick["why"])
        runs.append((rec, pick["solution"]))
    return repo, state, runs, {"rule": pop["hero"]["pick_rule"] + "; " + pop["hero"]["task_rule"], "task": pop["hero"]["task"]}


def empty_set(spec: dict, out_dir: Path):
    state = json.loads((SCENARIOS / spec["header_from"] / "state.json").read_text())
    rec = {"schema": "bb-run/1", "id": "empty", "title": "A run that saved nothing",
           "subject": {"solution": "none", "task": None, "split": None, "label": "no samples, no metrics"},
           "source": {"by": FOLD, "from": [], "note": "the fresh box (" + state["ref"] + ") has scored nothing: a record with no samples"},
           "time": {"unit": "s", "t": [], "windows": []}, "channels": [], "metrics": [], "events": [], "notes": [],
           "scene": {"kind": "none"}}
    return None, state, [(rec, "empty")], {"rule": "the real fresh box: zero solutions scored", "task": None}


KINDS = {"tta": tta_set, "rc": rc_set, "empty": empty_set}


def dump(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def fold_set(spec: dict) -> dict[Path, str]:
    out_dir = RUNS / spec["name"]
    repo, state, runs, why = KINDS[spec["kind"]](spec, out_dir)
    files = {}
    listed = []
    for rec, stem in runs:
        files[out_dir / f"{stem}.json"] = dump(rec)
        listed.append({"solution": rec["subject"]["solution"], "task": rec["subject"]["task"], "split": rec["subject"].get("split"),
                       "path": f"{stem}.json", "schema": "bb-run/1", "label": rec["subject"]["label"]})
    header = {k: state[k] for k in HEADER if k in state}
    out = {**header, "playback": {"runs": listed, "scene": None, "rule": why["rule"]},
           "source": {"fold": FOLD, "repo": repo.name if repo else state["about"].get("repo"), "ref": repo.ref if repo else state["ref"],
                      "read": sorted(set(repo.read)) if repo else []}}
    files[out_dir / "state.json"] = json.dumps(out, indent=1, ensure_ascii=False, allow_nan=False) + "\n"
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="re-fold and compare byte for byte; write nothing")
    ap.add_argument("--set", action="append", help="only these sets")
    args = ap.parse_args()
    listing = json.loads((RUNS / "runs.json").read_text())
    stale = []
    for spec in listing["sets"]:
        if args.set and spec["name"] not in args.set:
            continue
        for path, text in fold_set(spec).items():
            rel = path.relative_to(VIEWER)
            if args.check:
                if not path.exists() or path.read_text() != text:
                    stale.append(str(rel))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                print(f"wrote {rel} ({len(text) / 1e3:.0f} kB)")
    if args.check:
        print("stale: " + ", ".join(stale) if stale else "run records current")
        return 1 if stale else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
