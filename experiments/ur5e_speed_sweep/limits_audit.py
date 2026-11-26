"""Audit the frozen UR5e references without starting a simulator or contacting an arm.

Pass --arm-motion-bench to verify the generator's saved native rungs as well.
The summary uses only public-repository inputs and is identical with or without that option.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from robot_msgs import load_npz

from trajectory_tracking_agent.ruler.metrics import MOVING_JOINT_SPEED_RAD_S, VELOCITY_LIMIT_ALLOWANCE


REPO = Path(__file__).resolve().parents[2]
DATASET = Path("datasets/ur5e_alone/workspace/v2")
DECILE_EDGES = np.arange(11) / 10
NUMERIC_SLACK = 1e-10
UR_MANUAL = "https://www.universal-robots.com/manuals/EN/HTML/SW5_26/Content/prod-usr-man/complianceUR5e/H_g5_sections/appendix_g5/tech_spec_sheet.htm"
UR_TECH_SHEET = "https://www.universal-robots.com/media/1807465/ur5e_e-series_datasheets_web.pdf"
UR_ROS_LIMITS = "https://github.com/UniversalRobots/Universal_Robots_ROS2_Description/blob/0eb1a861f7772fceb38510d90fa2f98ec668070c/config/ur5e/joint_limits.yaml#L9-L80"
UR_SAFETY_LIMITS = "https://www.universal-robots.com/manuals/EN/HTML/SW5_25_1/Content/prod-usr-man/complianceUR5e/H_g5_sections/firstuse/Joint_limits_g5_en.htm"
RUCKIG_WAYPOINTS = "https://docs.ruckig.com/md_pages_2__intermediate__waypoints.html"


def rounded(value):
    return np.round(value, 9).tolist()


def load_verified(path, expected_sha):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError(f"{path.name} differs from the frozen manifest")
    return load_npz(path)


def tape_stats(tape, task, limits, rate_hz, speed):
    if tuple(tape.joint_names) != limits["joint_names"]:
        raise ValueError(f"{task['task_id']} axis order differs from the station")
    q, qd, qdd = tape.positions, tape.velocities, tape.accelerations
    if not all(np.isfinite(channel).all() for channel in (q, qd, qdd)):
        raise ValueError(f"{task['task_id']} has a non-finite reference")
    intervals = np.diff(tape.t)
    np.testing.assert_allclose(intervals, 1 / rate_hz, rtol=0, atol=1e-12)
    peak_qd = np.max(np.abs(qd), axis=0)
    moving = np.max(np.abs(qd), axis=1) > MOVING_JOINT_SPEED_RAD_S
    utilization = np.max(np.abs(qd) / limits["velocity"], axis=1)
    # Keep any overspeed in the last bin. The independent velocity check counts it below.
    duration_by_decile = np.histogram(utilization[:-1], bins=np.r_[DECILE_EDGES[:-1], np.inf], weights=intervals)[0]
    return {
        "id": task["task_id"], "split": task["split"], "kind": task["kind"],
        "samples": len(tape.t), "duration_s": rounded(intervals.sum()),
        "joint_position_min_deg": rounded(np.rad2deg(q.min(axis=0))),
        "joint_position_max_deg": rounded(np.rad2deg(q.max(axis=0))),
        "joint_peak_abs_velocity_deg_s": rounded(np.rad2deg(peak_qd)),
        "joint_peak_abs_acceleration_rad_s2": rounded(np.max(np.abs(qdd), axis=0)),
        "moving_samples": int(np.count_nonzero(moving)),
        "moving_time_s": rounded(intervals[moving[:-1]].sum()),
        "max_joint_speed_decile_time_s": rounded(duration_by_decile),
        "elbow_outside_manual_range_samples": int(np.count_nonzero(np.abs(q[:, 2]) > np.deg2rad(160))),
        "planning_position_violation_samples": int(np.count_nonzero(np.any((q < limits["low"]) | (q > limits["high"]), axis=1))),
        "planning_velocity_violation_samples": int(np.count_nonzero(np.any(np.abs(qd) > speed * limits["velocity"] + NUMERIC_SLACK, axis=1))),
        "planning_acceleration_violation_samples": int(np.count_nonzero(np.any(np.abs(qdd) > speed**2 * limits["acceleration"] + NUMERIC_SLACK, axis=1))),
    }


def summarize(tapes):
    return {
        "tapes": len(tapes),
        **{field: rounded(sum(tape[field] for tape in tapes)) for field in (
            "duration_s", "moving_time_s",
        )},
        **{field: sum(tape[field] for tape in tapes) for field in (
            "samples", "moving_samples", "elbow_outside_manual_range_samples", "planning_position_violation_samples",
            "planning_velocity_violation_samples", "planning_acceleration_violation_samples",
        )},
        **{field: rounded(reduce([tape[field] for tape in tapes], axis=0)) for field, reduce in (
            ("joint_position_min_deg", np.min), ("joint_position_max_deg", np.max),
            ("joint_peak_abs_velocity_deg_s", np.max), ("joint_peak_abs_acceleration_rad_s2", np.max),
            ("max_joint_speed_decile_time_s", np.sum),
        )},
    }


def verify_upstream(checkout, tasks, manifest, limits, frozen):
    tapes = checkout / "outputs" / DATASET / "tapes"
    for speed in manifest["rungs"]:
        speed_key = f"{speed:g}"
        suffix = "" if speed == 1 else f"__s{speed_key}"
        records = []
        for task in tasks:
            name = f"{task['task_id']}{suffix}.npz"
            tape = load_verified(tapes / name, manifest["files"][name])
            records.append(tape_stats(tape, task, limits, manifest["rate_hz"], speed))
        if speed == 1 and records != frozen:
            raise ValueError("Upstream speed 1.0 does not reproduce the frozen summary")
        summary = summarize(records)
        violation_count = sum(summary[field] for field in ("planning_position_violation_samples",
                              "planning_velocity_violation_samples", "planning_acceleration_violation_samples"))
        for split in ("dev", "holdout"):
            observed = rounded(sum(record["duration_s"] for record in records if record["split"] == split))
            if observed != manifest["duration_by_rung_s"][split][speed_key]:
                raise ValueError(f"Upstream {split} speed {speed_key} duration differs from the manifest")
        print(f"Upstream {speed_key}: {summary['tapes']} tapes, {summary['duration_s']:.2f} s, "
              f"peak {max(summary['joint_peak_abs_velocity_deg_s']):.5f} deg/s, "
              f"{violation_count} planning violations, "
              f"{summary['elbow_outside_manual_range_samples']} samples outside the manual elbow range")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-motion-bench", type=Path, help="checkout containing its saved native v2 tapes under outputs/datasets")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("limits.json"))
    args = parser.parse_args()
    root = REPO / DATASET
    manifest = json.loads((root / "manifest.json").read_text())
    frozen_manifest = json.loads((root / "tapes_manifest.json").read_text())
    station = json.loads((root / "station.json").read_text())
    tasks = [json.loads(line) for line in (root / "tasks.jsonl").read_text().splitlines()]
    station_fields = {"low": "position_min_rad", "high": "position_max_rad", "velocity": "velocity_max_rad_s",
                      "acceleration": "acceleration_max_rad_s2"}
    limits = {key: np.array([joint[field] for joint in station["joints"]]) for key, field in station_fields.items()}
    limits["joint_names"] = tuple(joint["name"] for joint in station["joints"])
    jerk = manifest["time_law"]["limits"]["jerk_max_rad_s3"]
    frozen = []
    for task in tasks:
        name = f"{task['task_id']}.npz"
        relative = f"tapes/{name}"
        if frozen_manifest["files"][relative] != manifest["files"][name]:
            raise ValueError(f"{name} has conflicting checksums")
        tape = load_verified(root / relative, frozen_manifest["files"][relative])
        for field, expected in (("min_position", limits["low"]), ("max_position", limits["high"]),
                                ("max_velocity", limits["velocity"]), ("max_acceleration", limits["acceleration"]),
                                ("max_jerk", jerk)):
            np.testing.assert_array_equal(getattr(tape.limits, field), expected)
        if tape.limits.position_kind != ("software",) * len(limits["joint_names"]):
            raise ValueError(f"{name} does not declare the station's software position limits")
        frozen.append(tape_stats(tape, task, limits, manifest["rate_hz"], frozen_manifest["speed"]))
    by_split = {split: summarize([tape for tape in frozen if tape["split"] == split]) for split in ("dev", "holdout")}
    for split, summary in by_split.items():
        if summary["tapes"] != manifest["counts"][split]["total"] or summary["duration_s"] != manifest["duration_rung_1_s"][split]:
            raise ValueError(f"{split} tape count or duration differs from the manifest")
    if args.arm_motion_bench is not None:
        verify_upstream(args.arm_motion_bench, tasks, manifest, limits, frozen)
    result = {
        "format": "ur5e_reference_limits/1", "dataset": DATASET.as_posix(),
        "generator_commit": manifest["generator"]["git_sha"],
        "joint_names": limits["joint_names"],
        "source_urls": {"ur_manual": UR_MANUAL, "ur_technical_sheet": UR_TECH_SHEET, "ur_ros2_description": UR_ROS_LIMITS,
                        "ur_safety_configuration": UR_SAFETY_LIMITS, "ruckig_waypoint_optimization": RUCKIG_WAYPOINTS},
        "nominal_ur_velocity_limit_deg_s": [180] * 6,
        "nominal_ur_manual_abs_position_limit_deg": [360, 360, 160, 360, 360, 360],
        "nominal_ur_technical_sheet_abs_position_limit_deg": [360] * 6,
        "ur_ros2_planning_abs_position_limit_deg": [360, 360, 180, 360, 360, 360],
        "reference_planning": {"position_min_deg": rounded(np.rad2deg(limits["low"])),
                               "position_max_deg": rounded(np.rad2deg(limits["high"])),
                               "velocity_limit_deg_s": rounded(np.rad2deg(limits["velocity"])),
                               "local_acceleration_limit_rad_s2": rounded(limits["acceleration"]),
                               "local_jerk_limit_rad_s3": jerk},
        "simulation_gate": {"velocity_allowance_factor": VELOCITY_LIMIT_ALLOWANCE,
                            "actual_velocity_limit_deg_s": rounded(np.rad2deg(limits["velocity"]) * VELOCITY_LIMIT_ALLOWANCE),
                            "actual_position_allowance_deg": 0, "sample_domain": "all simulator physics samples",
                            "source": "src/trajectory_tracking_agent/ruler/metrics.py"},
        "measurement": {"frozen_speed_fraction": frozen_manifest["speed"], "rate_hz": manifest["rate_hz"],
                        "moving_joint_speed_threshold_deg_s": rounded(np.rad2deg(MOVING_JOINT_SPEED_RAD_S)),
                        "numeric_slack_for_rate_checks_si": NUMERIC_SLACK, "decile_edges": rounded(DECILE_EDGES),
                        "time_method": "Left-aligned intervals. Speed utilization is the largest absolute joint speed divided by its planning limit. Includes holds. Moving uses only the ruler's joint-speed threshold."},
        "planned_duration_s_by_split_and_native_fraction": manifest["duration_by_rung_s"],
        "all": summarize(frozen), "by_split": by_split,
        "tape_columns": list(frozen[0]), "tapes": [list(tape.values()) for tape in frozen],
    }
    args.output.write_text(json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n")
    print(f"Audited {len(frozen)} frozen reference tapes")


if __name__ == "__main__":
    main()
