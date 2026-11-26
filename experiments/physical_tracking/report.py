"""Render saved BAM FB and CAN 11 trajectories with the hardware archive audit."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

import numpy as np
from arm_motion_bench.dashboard_models import bam_fb_robot, pendulum_robot
from arm_motion_bench.records import Trace
from traj_compare import (BarChart, BarSeries, Comparison, Insight, MetricCard, ReportPage, ReportTable,
                          Situation, TableRow, write_comparison_report)


def poses(positions, rotations):
    result = np.broadcast_to(np.eye(4), (len(positions), 4, 4)).copy()
    result[:, :3, 3], result[:, :3, :3] = positions, rotations
    return result


def build(qualification, archive, simulated_path, physical_path, output, bam_evidence=None, bam_sources=None, base=None):
    sim = json.loads(qualification.read_text())
    physical = json.loads(archive.read_text())
    target_id = sim["worst_rms"]["target"]
    with np.load(simulated_path) as recording, np.load(physical_path) as saved:
        rows = len(recording["t"])
        measured = json.loads(str(saved["meta"]))
        if (measured["domain"], measured["task_id"], measured["rung"]) != ("real", target_id, sim["top_rung"]):
            raise ValueError("the archived recording is not the same physical tape")
        for target, reference in (("t", "t"), ("target_q", "target_q"), ("target_qd", "target_qd"),
                                  ("target_qdd", "target_qdd")):
            np.testing.assert_allclose(recording[target], saved[reference][:rows], atol=1e-9, rtol=0)
        nominal = recording["t"]
        target = Situation("target", "Frozen CAN 11 reference", t=nominal, q=recording["target_q"],
                           qd=recording["target_qd"], qdd=recording["target_qdd"], poses=recording["target_pose"])
        simulated = Situation("sim", "Locked simulation controller", t=nominal, q=recording["measured_q"],
                              qd=recording["measured_qd"], tau=recording["measured_tau"], poses=recording["measured_pose"])
        encoder_fk = Situation("archive", "Nov 20 hardware encoder estimate", t=nominal, q=saved["q"][:rows],
                               qd=saved["qd"][:rows], tau=saved["tau"][:rows],
                               poses=poses(saved["tcp_pos"][:rows], saved["tcp_rot"][:rows]))
    comparison = Comparison(title="CAN 11 at rung 1.0", name="can11-rung-1", joint_names=["can11"], target=target,
                            situations=[simulated, encoder_fk], tcp_frame="Pendulum tip", robot=pendulum_robot(),
                            description=f"Matched target {target_id}. The archived hardware used an earlier controller. "
                                        "Its readout uses encoder FK on the nominal plan clock.")
    sources = physical["corpora"]["pendulum/workspace/v2"]["controllers"]
    labels = ["Locked sim", *sources]
    stops = [sim["worst_stop"]["stop_error_max_mm"], *[item["worst"]["stop_error_max_mm"]["stop_error_max_mm"]
                                                      for item in sources.values()]]
    full = [sim["worst_rms"]["full_trajectory_rms_mm"], *[item["worst"]["full_trajectory_rms_mm"]["full_trajectory_rms_mm"]
                                                       for item in sources.values()]]
    legacy = physical["legacy_bam_workspace_run"]
    summary = ReportPage("Summary", metrics=[
        MetricCard("CAN 11 simulation", f"{sim['runs']}/{sim['runs']}", "Workspace runs at rung 1.0"),
        MetricCard("CAN 11 physical archive", f"{sum(item['matched_traces'] for item in sources.values())}", "Encoder traces at rung 1.0"),
        MetricCard("BAM FB legacy workspace RMS", f"{legacy['full_trajectory_rms_mm']:.3f} mm", "One historical course, command clock"),
    ], charts=[BarChart("Worst CAN 11 accuracy over each corpus", labels,
                        [BarSeries("Worst stop", stops), BarSeries("Full-trajectory RMS", full)], unit="mm")],
        tables=[ReportTable("Archived CAN 11 trace coverage", ["Controller", "Matched tapes", "Traces", "Missing-tick traces"],
                            [TableRow([name, item["unique_targets"], item["matched_traces"],
                                       item["matched_traces_with_missing_plan_ticks"]]) for name, item in sources.items()])])
    insights = ReportPage("Insights", insights=[
        Insight("Where the hardware trace ends", "The CAN 11 archive measures motor encoder FK. An independent measurement "
                "of the link's tip is needed to resolve downstream backlash."),
        Insight("BAM FB coverage", "The archived highest-rung BAM FB recording covers one workspace task on an irregular "
                "command clock. There are no matched conveyor recordings in the imported archive."),
    ])
    output.mkdir(parents=True, exist_ok=True)
    write_comparison_report(comparison, output / "comparison.html", title="Highest-rung tracking evidence", summary=summary,
                            insights=insights, provenance={"CAN 11 manifest SHA-256": sim["dataset_manifest_sha256"],
                                                          "Simulation lock SHA-256": sim["controller_lock_sha256"]},
                            breadcrumb=[("Tracking evidence", "index.html"), ("Matched CAN 11 playback", "")])
    for source, filename in ((qualification, "pendulum-qualification.json"), (archive, "physical-archive-audit.json")):
        (output / filename).write_bytes(source.read_bytes())
    bam = None
    if bam_evidence is not None:
        bam = json.loads(bam_evidence.read_text())
        build_bam(bam, bam_sources, np.asarray(base), output / "bam-fb.html")
        (output / "bam-fb-qualification.json").write_bytes(bam_evidence.read_bytes())
    (output / "index.html").write_text(gallery(sim, legacy, bam))


def bam_study(trace_file, cohort, evidence, base):
    trace = Trace.load(trace_file)
    meta = trace.meta
    with trace_file.open("rb") as stream:
        trace_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if (meta["dataset"] != cohort or meta["domain"] != "sim" or meta["controller_sha256"] != evidence["controller_sha256"]
            or evidence["corpora"][cohort]["trace_digests"].get(meta["task_id"]) != trace_hash):
        raise ValueError(f"{cohort} playback differs from the measured controller")
    synchronous = trace.optional["synchronous_tcp_pos"]
    target = Situation("target", "Frozen reference", t=trace.t, q=trace.target_q, qd=trace.target_qd, qdd=trace.target_qdd,
                       poses=base @ poses(trace.target_tcp_pos, trace.target_tcp_rot))
    simulation = Situation("sim", "Locked BAM FB simulation", t=trace.t, q=trace.q, qd=trace.qd, tau=trace.tau,
                           poses=base @ poses(synchronous, trace.tcp_rot))
    title = "BAM FB workspace" if cohort == "workspace" else "BAM FB conveyor"
    return Comparison(title=title, name=f"bam-fb-{cohort}", joint_names=["j1", "j2", "c1", "w1", "w2", "w3"],
                      target=target, situations=[simulation], tcp_frame="Claw tip", robot=bam_fb_robot(),
                      description=f"Matched target {meta['task_id']}. TCP positions use the current simulation tick. "
                                  "Joint and orientation overlays use the logged board state.")


def build_bam(evidence, traces, base, output):
    comparisons = [bam_study(path, kind, evidence, base) for kind, path in zip(("workspace", "conveyor"), traces, strict=True)]
    summary = ReportPage("Summary", tables=[ReportTable("BAM FB qualification at rung 1.0",
        ["Dataset", "Runs", "Worst stop (mm)", "Worst full RMS (mm)", "Existing gate passes"],
        [TableRow([kind.capitalize(), sum(part["counts"].values()),
                   f'{part["worst"]["stop_error_max_mm"]["stop_error_max_mm"]:.3f}',
                   f'{part["worst"]["full_trajectory_rms_mm"]["full_trajectory_rms_mm"]:.3f}',
                   part["existing_gates"]["passes"]]) for kind, part in evidence["corpora"].items()])])
    write_comparison_report(comparisons, output, title="BAM FB at the highest declared rung", summary=summary,
                            provenance={"Controller SHA-256": evidence["controller_sha256"]},
                            breadcrumb=[("Tracking evidence", "index.html"), ("BAM FB playback", "")])


def bam_overview(evidence):
    if evidence is None:
        return ""
    rows = "".join(f'<tr><th scope="row">{html.escape(name.capitalize())}</th><td>{sum(part["counts"].values())}</td>'
                   f'<td>{part["worst"]["stop_error_max_mm"]["stop_error_max_mm"]:.3f}</td>'
                   f'<td>{part["worst"]["full_trajectory_rms_mm"]["full_trajectory_rms_mm"]:.3f}</td>'
                   f'<td>{part["existing_gates"]["passes"]}</td></tr>' for name, part in evidence["corpora"].items())
    return f'''<article><h2>BAM FB simulation at rung 1.0</h2><p>One locked controller ran both datasets. It used increased board gains
in simulation. <a href="bam-fb.html">Open BAM FB playback</a> · <a href="bam-fb-qualification.json">Frozen evidence</a></p>
<div class="scroll"><table><thead><tr><th>Dataset</th><th>Runs</th><th>Worst stop (mm)</th><th>Worst full RMS (mm)</th>
<th>Existing gate passes</th></tr></thead><tbody>{rows}</tbody></table></div></article>'''


def gallery(sim, legacy, bam=None):
    headline = "CAN 11 met both simulation targets at rung 1.0."
    can11 = f"Across {sim['runs']} workspace paths the worst stop was"
    video_stem = "walkthrough"
    poster = "poster"
    video_label = "CAN 11 playback in the trajectory comparison"
    if bam is not None:
        total = sim["runs"] + sum(sum(part["counts"].values()) for part in bam["corpora"].values())
        headline = f"All {total} frozen trajectories met both simulation targets at rung 1.0."
        can11 = f"Across {sim['runs']} CAN 11 workspace paths the worst stop was"
        video_stem = "bam-walkthrough"
        poster = "bam-poster"
        video_label = "BAM FB workspace and conveyor playback in the trajectory comparison"
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BAM FB and pendulum tracking evidence</title><style>
body {{margin:0;background:#f7f6f2;color:#202b28;font:16px/1.5 system-ui}}
main {{max-width:1060px;margin:auto;padding:clamp(16px,5vw,64px)}} h1 {{font-size:clamp(2rem,6vw,3.7rem);line-height:1.08;margin:.4em 0}}
p {{max-width:72ch}} a {{color:#11695b}} figure {{margin:1.4em 0}} video {{display:block;width:100%;aspect-ratio:16/9;background:#26302d;border-radius:8px}}
figcaption {{padding-top:.5em}} article {{margin:2rem 0}}
table {{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}} th,td {{text-align:left;padding:.5em;border-bottom:1px solid #cad6d0}} .scroll {{overflow:auto}}
</style><body><main>
<h1>BAM FB and pendulum tracking</h1>
<p><strong>{headline}</strong> {can11}
{sim['worst_stop']['stop_error_max_mm']:.3f} mm and worst full-trajectory RMS was {sim['worst_rms']['full_trajectory_rms_mm']:.3f} mm.
The simulation used higher board stiffness than the archived hardware controllers.</p>
<p><a href="../../dashboard/#goals">Blackbox Goals</a> · <a href="comparison.html#tab=track">Matched CAN 11 playback</a> ·
<a href="pendulum-qualification.json">Simulation evidence</a> · <a href="physical-archive-audit.json">Physical archive audit</a></p>
<figure><video controls autoplay muted loop playsinline preload="metadata" poster="media/{poster}.webp" aria-label="{video_label}">
<source src="media/{video_stem}.mp4" type="video/mp4"><img src="media/{video_stem}.gif" alt="{video_label}"></video>
<figcaption>Recorded stock trajectory comparison. <a href="media/{video_stem}.gif">GIF fallback</a></figcaption></figure>
{bam_overview(bam)}
<article><h2>Hardware archive</h2><p>CAN 11 has 468 top-rung encoder traces across three historical controllers. Their tool estimates
use board encoder FK on the plan clock. Each controller missed at least one target. The older BAM FB workspace run
<code>{html.escape(legacy['run_id'])}</code> scored {legacy['stop_error_max_mm']:.3f} mm at its stop and
{legacy['full_trajectory_rms_mm']:.3f} mm full-trace RMS over one course. The current hardware goal requires the matched full dataset,
acquisition timebase and an independent output-side measurement.</p></article>
</main></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("qualification", "archive", "simulation", "physical", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--bam-evidence", type=Path)
    parser.add_argument("--bam-sources", type=Path, nargs=2, metavar=("WORKSPACE", "CONVEYOR"))
    parser.add_argument("--bam-station", type=Path)
    args = parser.parse_args()
    if any((args.bam_evidence, args.bam_sources, args.bam_station)) and not all((args.bam_evidence, args.bam_sources, args.bam_station)):
        parser.error("BAM FB evidence, both playback traces and the frozen station must be supplied together")
    base = json.loads(args.bam_station.read_text())["base_in_cell"] if args.bam_station else None
    build(args.qualification, args.archive, args.simulation, args.physical, args.output,
          args.bam_evidence, args.bam_sources, base)


if __name__ == "__main__":
    main()
