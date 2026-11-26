"""Roll up the complete UR5e tracking goal matrix for one locked controller."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from trajectory_tracking_agent import population
from trajectory_tracking_agent.ruler.dataset import TAPES_MANIFEST, sha256, tasks

FRACTIONS = tuple(step / 10 for step in range(1, 11))
PORTAL_SHA = "4095e1ec3fdf4079bd1c56996d80d3b5b77a93f1a916c7d2eea18a77cfe62411"
METRICS = ("stop_error_max_mm", "full_trajectory_rms_mm")
COMMON_CHECKS = {"completed", "stop_error_max_mm", "saturation_share_pct", "limit_violations"}


def read(path):
    return json.loads(path.read_text())


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def exact_matrix(actual, expected, label):
    counts = Counter(actual)
    expected = set(expected)
    missing = expected - counts.keys()
    unexpected = counts.keys() - expected
    duplicates = [key for key, count in counts.items() if count > 1]
    require(not (missing or unexpected or duplicates),
            f"{label}: missing {sorted(missing)}, unexpected {sorted(unexpected)}, repeated {sorted(duplicates)}")


def row(cohort, target, fraction, stop, rms, stop_count, samples, verdicts):
    label = f"{cohort}/{target}/{fraction:.1f}"
    require(type(stop_count) is int and stop_count > 0, f"{label} has no measured stops")
    require(type(samples) is int and samples > 1, f"{label} has no measured trace")
    require(all(type(value) in (float, int) and math.isfinite(value) and value >= 0 for value in (stop, rms)),
            f"{label} is missing a finite, nonnegative measurement")
    clearance = "scene_clearance" if cohort == "portal" else "floor_clearance"
    require(set(verdicts) == COMMON_CHECKS | {clearance} and all(type(value) is bool for value in verdicts.values()),
            f"{label} is missing a gate verdict")
    return {"cohort": cohort, "target": target, "fraction": fraction, "stops": stop_count, "samples": samples,
            METRICS[0]: stop, METRICS[1]: rms, "failed_gates": sorted(name for name in verdicts if not verdicts[name])}


def upright(path, split, controller, controller_sha):
    report = read(path)
    targets = [task.id for task in tasks(split)]
    require(report.get("schema") == "tta.ur5e-speed-study/1" and report.get("split") == split
            and report.get("dataset") == "ur5e_alone/workspace/v2"
            and report.get("dataset_manifest_sha256") == sha256(TAPES_MANIFEST), f"wrong upright input for {split}")
    require(report["controller_sha256"] == {controller: controller_sha} and report["controllers"] == [controller],
            f"{split} did not use the locked controller")
    exact_matrix(report["tasks"], targets, f"{split} task declarations")
    exact_matrix(report["fractions"], FRACTIONS, f"{split} speed declarations")
    exact_matrix(((run["target"], run["fraction"]) for run in report["runs"]),
                 ((target, fraction) for target in targets for fraction in FRACTIONS), split)
    require(all(run["solution"] == controller for run in report["runs"]), f"{split} mixes controllers")
    return [row(f"upright {split}", run["target"], run["fraction"], run[METRICS[0]], run[METRICS[1]],
                run["stops"], run["samples"], run["gates"]) for run in report["runs"]]


def recording_measurements(path, expected_samples, duration):
    with np.load(path) as recording:
        time = recording["t"]
        moving = recording["moving"]
        desired = recording["target_poses"][:, :3, 3]
        actual = recording["actual_poses"][:, :3, 3]
    require(time.shape == moving.shape == (expected_samples,) and moving.dtype == np.bool_
            and desired.shape == actual.shape == (expected_samples, 3) and np.isfinite(desired).all()
            and np.isfinite(actual).all() and np.allclose(time, np.arange(expected_samples) / 100, atol=1e-9, rtol=0)
            and math.isclose(time[-1], duration, abs_tol=1e-9, rel_tol=0), f"{path.name} has an incomplete trace")
    rms = 1000 * np.sqrt(np.mean(np.sum((desired - actual) ** 2, axis=1)))
    # WHY check retained traces separately: the frozen scorer returns zero when a trace contains no recognized stop.
    boundaries = np.flatnonzero(np.diff(np.r_[False, ~moving, False]))
    errors = []
    for start, end in zip(boundaries[::2], boundaries[1::2], strict=True):
        if end - start >= 21:  # 21 samples at 100 Hz span 0.2 seconds, including both endpoints.
            final = slice(end - 11, end)
            errors.append(float(1000 * np.linalg.norm(desired[final].mean(axis=0) - actual[final].mean(axis=0))))
    require(bool(errors), f"{path.name} has no measured stops")
    return float(rms), max(errors), len(errors)


def portal(paths, manifest_path, controller, controller_sha):
    require(sha256(manifest_path) == PORTAL_SHA, "the portal manifest is not the frozen 30-pick cycle")
    manifest = read(manifest_path)
    tapes = {tape["speed_fraction"]: tape for tape in manifest["tapes"]}
    rows = []
    artifacts = []
    for path in paths:
        report = read(path)
        require(report.get("schema") == "tta.conveyor-cycle-baseline/1" and report.get("picks") == 30
                and report.get("dataset_manifest_sha256") == PORTAL_SHA and report.get("scene") == manifest["scene"],
                f"{path} does not measure the frozen portal cycle")
        require(report["controller"] == controller and report["controller_sha256"] == controller_sha,
                f"{path} did not use the locked controller")
        exact_matrix((run["speed_fraction"] for run in report["runs"]), report["requested_fractions"], path.name)
        for run in report["runs"]:
            fraction = run["speed_fraction"]
            target = f"conveyor-cycle-{round(10 * fraction):02d}"
            tape = tapes[fraction]
            require(run["source_tape_sha256"] == tape["sha256"] and run["recording"] == f"{target}.npz",
                    f"{target} did not use the frozen tape or expected recording")
            recording = path.parent / run["recording"]
            want_rms = run[METRICS[1]]
            want_stop = run["kpis"][METRICS[0]]
            rms, stop, stop_count = recording_measurements(recording, tape["samples"], run["duration_s"])
            require(math.isclose(rms, want_rms, abs_tol=1e-9, rel_tol=0)
                    and math.isclose(stop, want_stop, abs_tol=1e-9, rel_tol=0),
                    f"{target} summary differs from the recorded poses")
            rows.append(row("portal", target, fraction, want_stop, want_rms, stop_count, tape["samples"], run["verdicts"]))
            artifacts.append({"fraction": fraction, "summary_sha256": sha256(path), "tape_sha256": tape["sha256"],
                              "recording_sha256": sha256(recording)})
    exact_matrix((item["fraction"] for item in rows), FRACTIONS, "portal speed sweep")
    return rows, sorted(artifacts, key=lambda item: item["fraction"])


def summarize(rows):
    return {"runs": len(rows), "runs_passing_all_gates": sum(not item["failed_gates"] for item in rows),
            "worst": {metric: max(rows, key=lambda item: item[metric]) for metric in METRICS}}


def measure(dev, holdout, portal_paths, manifest, controller, controller_sha):
    require(population.solution_sha256(controller) == controller_sha, "working controller differs from the lock")
    development = upright(dev, "dev", controller, controller_sha)
    confirmation = upright(holdout, "holdout", controller, controller_sha)
    mounted, portal_inputs = portal(portal_paths, manifest, controller, controller_sha)
    cohorts = {"upright dev": development, "upright holdout": confirmation, "portal": mounted}
    rows = development + confirmation + mounted
    speeds = {f"{fraction:.1f}": {name: summarize([item for item in part if item["fraction"] == fraction])
                                 for name, part in cohorts.items()} for fraction in FRACTIONS}
    return {"schema": "tta.ur5e-tracking-goal/1", "controller": controller, "controller_sha256": controller_sha,
            "datasets": {"upright": sha256(TAPES_MANIFEST), "portal": PORTAL_SHA},
            "evidence": {"upright_dev_sha256": sha256(dev), "upright_holdout_sha256": sha256(holdout),
                         "portal": portal_inputs},
            "overall": summarize(rows),
            "cohorts": {name: summarize(part) for name, part in cohorts.items()}, "speeds": speeds,
            "separate_gate_failures": [item for item in rows if item["failed_gates"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upright-dev", type=Path, required=True)
    parser.add_argument("--upright-holdout", type=Path, required=True)
    parser.add_argument("--portal", type=Path, nargs="+", required=True)
    parser.add_argument("--portal-manifest", type=Path, required=True)
    parser.add_argument("--controller", required=True)
    parser.add_argument("--locked-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = measure(args.upright_dev, args.upright_holdout, args.portal, args.portal_manifest,
                       args.controller, args.locked_sha)
    args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
