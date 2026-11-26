"""Explain the first armed detector trigger from paired, complete BAM FB simulation captures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from arm_motion_bench.records import Trace
from bam_arm_fb_sim.plant import DRIVE_ORDER, TRUTH


def diagnose(summary, directory):
    measured = []
    zero = {}
    gaps = np.asarray(summary["gaps_deg"])
    roles = list(DRIVE_ORDER)

    for row in summary["runs"]:
        task = row["task"]
        condition = row["condition"]
        path = directory / f"{condition}--{task}.trace.npz"
        with path.open("rb") as stream:
            trace_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        if trace_sha != row["trace_sha256"]:
            raise ValueError(f"{task}: raw trace changed")
        trace = Trace.load(path)
        independent_rms = np.linalg.norm(trace.target_tcp_pos - trace.optional["synchronous_tcp_pos"]) * 1000 / np.sqrt(len(trace.t))
        np.testing.assert_allclose(independent_rms, row["actual_claw"]["full_rms_mm"], atol=1e-10, rtol=0)
        if condition == "zero-gap":
            zero[task] = trace
            continue
        if row["detector_trip_s"] is None:
            continue
        detector = trace.meta["detector"]
        trigger = int(detector["reaction"]["at_index"])
        source = zero[task]
        result = {}
        for label, candidate in (("geared", trace), ("zero_gap", source)):
            data = candidate.optional
            thresholds = np.asarray(candidate.meta["detector"]["threshold"])
            error = np.linalg.norm(candidate.target_tcp_pos[:trigger + 1] - data["synchronous_tcp_pos"][:trigger + 1], axis=1)
            residual = data["momentum_residual_nm"][trigger]
            requested = data["tau_requested"][trigger]
            shaft_split = np.degrees(data["current_tick_motor_q"][trigger] - data["current_tick_link_q"][trigger])
            crossing_axes = np.flatnonzero(np.abs(residual) > thresholds)
            result[label] = {
                "first_crossing_roles": [roles[index] for index in crossing_axes],
                "residual_nm": residual.tolist(),
                "abs_residual_over_threshold": (np.abs(residual) / thresholds).tolist(),
                "shaft_split_deg": shaft_split.tolist(),
                "crossing_roles_with_split_over_one_tenth_gap": [
                    roles[index] for index in crossing_axes if abs(shaft_split[index]) >= 0.1 * gaps[index]],
                "crossing_roles_with_request_reply_sign_mismatch": [
                    roles[index] for index in crossing_axes
                    if np.sign(requested[index]) != np.sign(candidate.tau[trigger, index])],
                "host_ff_sent_nm_previous_tick": data["tau_ff_host"][trigger - 1].tolist(),
                "host_ff_sent_nm_this_tick": data["tau_ff_host"][trigger].tolist(),
                "latched_ff_nm": data["tau_ff"][trigger].tolist(),
                "board_feedback_nm": data["tau_fb"][trigger].tolist(),
                "board_integral_nm": data["tau_integral"][trigger].tolist(),
                "board_command_nm_before_clip": data["tau_cmd"][trigger].tolist(),
                "board_requested_nm_after_clip": requested.tolist(),
                "board_reported_applied_nm": candidate.tau[trigger].tolist(),
                "pre_trip_max_claw_error_mm_including_trigger": float(np.max(error) * 1000),
                "pre_trip_max_contact_force_n_including_trigger": float(np.max(data["contact_force_n"][:trigger + 1])),
                "full_trace_claw_contact_first_s": candidate.meta["contact_first_t"],
            }
        if not detector["armed"] or not result["geared"]["first_crossing_roles"] or result["zero_gap"]["first_crossing_roles"]:
            raise ValueError(f"{task}: paired trigger capture disagrees with detector evidence")
        measured.append({"condition": condition, "task": task, "trip_index": trigger, "trip_s": float(trace.t[trigger]),
                         "reaction": detector["reaction"]["kind"], "requested_reference_interrupted": True,
                         "threshold_nm": detector["threshold"], **result})

    return {
        "schema": "tta.bam-fb-armed-detector-trip/1",
        "source_controller_sha256": summary["controller_sha256"],
        "model": "stock rigid-arm drive-space generalized-momentum observer, armed, simulated six-drive plant",
        "roles": roles,
        "clock": {
            "host_period_s": 0.01,
            "simulated_command_delay_s": [TRUTH[role].command_delay_s for role in roles],
            "simulated_reply_delay_s": [TRUTH[role].reply_delay_s for role in roles],
            "simulated_current_loop_hz": [TRUTH[role].current_loop_hz for role in roles],
            "simulated_current_loop_time_constant_s": [1 / (2 * np.pi * TRUTH[role].current_loop_hz) for role in roles],
            "per_tick_observer_torque": "mean physical motor torque over the prior host interval, integrated at the physics step",
            "per_tick_board_requested_torque": "last physics step of the host interval",
            "per_tick_board_reported_torque": "current-loop filtered and sampled at the board reply delay",
        },
        "trips": measured,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.recording_dir / "results.json").read_text())
    result = diagnose(summary, args.recording_dir)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
