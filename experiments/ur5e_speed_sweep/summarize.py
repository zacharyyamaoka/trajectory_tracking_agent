"""Publish compact, deterministic evidence for the matched UR5e speed sweep."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median

from trajectory_tracking_agent.population import solution_dir, solution_sha256
from trajectory_tracking_agent.ruler.dataset import DATASET_DIR, tasks

from run import CONTROLLERS, FRACTIONS


def read_json(path: Path):
    return json.loads(path.read_text())


def field_sum(results, key):
    bins = [row[key] for row in results if row[key] is not None]
    return [round(sum(column), 6) for column in zip(*bins, strict=True)] if bins else None


def joint_max(results, key):
    peaks = [row[key] for row in results if row[key] is not None]
    return [round(max(column), 6) for column in zip(*peaks, strict=True)] if peaks else None


def compact(raw):
    if raw["schema"] != "tta.ur5e-speed-study/1" or raw["split"] != "dev":
        raise ValueError("expected a UR5e dev sweep")
    targets = [task.id for task in tasks("dev")]
    if set(raw["tasks"]) != set(targets) or set(raw["controllers"]) != set(CONTROLLERS) or set(raw["fractions"]) != set(FRACTIONS):
        raise ValueError("the study must cover all declared controllers, speeds, and matched dev targets")
    rows = {(row["solution"], row["fraction"], row["target"]): row for row in raw["runs"]}
    expected = {(solution, fraction, target) for solution in CONTROLLERS for fraction in FRACTIONS for target in targets}
    if set(rows) != expected or len(rows) != len(raw["runs"]):
        raise ValueError("every controller must have exactly one run per speed and dev target")

    tracking = {}
    reported = {}
    for solution in CONTROLLERS:
        scorecard = read_json(solution_dir(solution) / "scorecard.json")
        sha = solution_sha256(solution)
        for locked in scorecard["tasks"]:
            current = rows[solution, 1.0, locked["task"]]
            if (current["tool_track_rms_mm"], current["gates"]) != (locked["objective"], locked["verdicts"]):
                raise ValueError(f"full speed did not reproduce the frozen scorecard: {solution}/{locked['task']}")
        tracking[solution] = []
        by_speed = []
        for fraction in FRACTIONS:
            results = [rows[solution, fraction, target] for target in targets]
            scores = [row["tool_track_rms_mm"] for row in results]
            tracking[solution].append(scores)
            valid = [score for score in scores if score is not None]
            gate_names = results[0]["gates"].keys()
            by_speed.append({
                "scored": len(valid), "median_mm": median(valid) if len(valid) == len(targets) else None,
                "all_gates_pass": sum(all(row["gates"].values()) for row in results),
                "gate_failures": {gate: sum(not row["gates"][gate] for row in results) for gate in gate_names},
                "sampled_velocity_runs": sum(row["measured_dwell_s"] is not None for row in results),
                "simulated_dwell_s": field_sum(results, "measured_dwell_s"),
                "simulated_peak_deg_s": joint_max(results, "measured_peak_deg_s"),
            })
        reported[solution] = {"code_sha256": sha, "by_speed": by_speed}

    nominal_tapes = []
    for fraction in FRACTIONS:
        tapes = [rows[CONTROLLERS[0], fraction, target] for target in targets]
        nominal_tapes.append({"trajectories": len(tapes), "elapsed_s": round(sum(tape["duration_s"] for tape in tapes), 6),
                              "target_dwell_s": field_sum(tapes, "target_dwell_s"),
                              "target_peak_deg_s": joint_max(tapes, "target_peak_deg_s")})
    return {
        "schema": "tta.ur5e-speed-study-summary/1", "dataset": raw["dataset"], "split": "dev",
        "scope": raw["scope"], "trials": len(rows),
        "frozen_tapes_manifest_sha256": hashlib.sha256((DATASET_DIR / "tapes_manifest.json").read_bytes()).hexdigest(),
        "joint_names": raw["joint_names"], "configured_velocity_max_deg_s": raw["configured_velocity_max_deg_s"],
        "fractions": FRACTIONS, "targets": targets, "nominal_tapes": nominal_tapes,
        "controllers": reported, "tracking_rms_mm": tracking,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(compact(read_json(args.runs)), indent=1, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
