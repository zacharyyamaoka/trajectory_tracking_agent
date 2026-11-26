#!/usr/bin/env python3
"""Build a stock Trajectory Comparison report from saved full-speed conveyor traces."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
from arm_motion_bench.dashboard_models import bam_fb_robot
from arm_motion_bench.datasets import load_dataset, station_for
from arm_motion_bench.records import Trace
from traj_compare import Comparison, Insight, MetricCard, ReportPage, ReportTable, Situation, TableRow, write_comparison_report

from score import sha256


def transforms(positions, rotations):
    poses = np.broadcast_to(np.eye(4), (len(positions), 4, 4)).copy()
    poses[:, :3, 3], poses[:, :3, :3] = positions, rotations
    return poses


def trace_for(run_root, report, task_id):
    row = next(row for row in report["rows"] if row["task"] == task_id)
    name = f"{task_id}__s1.0__r{report['repeat']}.trace.npz"
    matches = list((run_root / report["controller"] / "conveyor-v2" / row["split"]).glob(name))
    if len(matches) != 1 or sha256(matches[0]) != row["trace_sha256"]:
        raise ValueError(f"could not locate the audited trace {name} for {report['controller']}")
    return Trace.load(matches[0])


def summary_cell(case):
    if case is None:
        return "Unmeasured"
    return f"{case['mm']:.3f} mm ({case['task']})"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("runs", type=Path, help="Directory containing one stock conveyor-v2 folder per controller")
    parser.add_argument("output", type=Path)
    parser.add_argument("scores", nargs="+", type=Path)
    parser.add_argument("--tasks", nargs="+", required=True, help="Matched task IDs for individual trajectory playback")
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    report_rows = [json.loads(path.read_text()) for path in args.scores]
    manifest_hash = sha256(dataset.path / "manifest.json")
    if any(report["corpus"]["manifest_sha256"] != manifest_hash for report in report_rows):
        raise ValueError("score reports do not refer to the same frozen curriculum")
    robot = bam_fb_robot()
    base_from_world = station_for(dataset).base_from_world
    # WHY transform the rendering to the station's base frame: the mesh renderer is authored in cell coordinates.
    display = replace(robot, link_fk=lambda q: base_from_world @ robot.link_fk(q))
    comparisons = []
    for task_id in args.tasks:
        task = dataset.task(task_id)
        planned = dataset.target(task_id, rung=max(task.rungs))
        t, positions, rotations = dataset.target_tcp(task_id, rung=max(task.rungs))
        target = Situation("target", "Frozen trajectory", t=t, q=planned.positions, qd=planned.velocities,
                           qdd=planned.accelerations, poses=transforms(positions, rotations))
        situations = []
        for report in report_rows:
            trace = trace_for(args.runs, report, task_id)
            tcp = trace.optional.get("synchronous_tcp_pos", trace.tcp_pos)
            situations.append(Situation(report["controller"], report["controller"], t=trace.t, q=trace.q, qd=trace.qd,
                                        tau=trace.tau, poses=transforms(tcp, trace.tcp_rot)))
        situations.append(Situation("hardware", "Physical BAM FB", note="No matched physical recording for the frozen tape"))
        comparisons.append(Comparison(title=task_id, name=task_id, joint_names=list(planned.joint_names), target=target,
                                      situations=situations, robot=display, tcp_frame="BAM FB claw TCP",
                                      description="Highest frozen rung at 100 Hz. The full-trajectory score includes holds."))
    rows = []
    for report in report_rows:
        total = report["overall"]
        rows.append(TableRow(cells=[report["controller"], f"{total['measured_tasks']}/{total['expected_tasks']}",
                                   summary_cell(total["worst_stop"]), summary_cell(total["worst_full_rms"]),
                                   total["both_goal_targets_passed"], total["all_gates_passed"], report["measurement_source"]]))
    summary = ReportPage("Summary", metrics=[MetricCard("Worst stop target", "<0.5 mm", "Final 0.1 s at stops"),
                                               MetricCard("Whole-trajectory RMS target", "<1.0 mm", "Every sample")],
                         tables=[ReportTable(title="Highest-rung development runs",
                                             columns=["Controller", "Coverage", "Worst stop", "Worst RMS",
                                                      "Both targets pass", "All run gates pass", "TCP measurement"], rows=rows)])
    insights = ReportPage("Insights", insights=[
        Insight("Measurement", "Legacy captures use encoder and closure FK. Where captured, synchronous simulated site position "
                "supplies the position measurement. Joint traces continue to show the recorded encoder values."),
        Insight("Conveyor model", "The benchmark uses a six-drive closed-chain arm and a reduced belt contact model. "
                "Planning records include the bins and rims. Payload handling and the W3 workcell are separate tests."),
        Insight("Model provenance", "Stock comparisons used the same nominal plant model for feedforward. "
                "Their measurements diagnose the baseline. Goal qualification requires an independently characterized candidate."),
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_comparison_report(comparisons, args.output, title="BAM FB conveyor tracking", summary=summary, insights=insights,
                            provenance={"dataset manifest SHA-256": manifest_hash})


if __name__ == "__main__":
    main()
