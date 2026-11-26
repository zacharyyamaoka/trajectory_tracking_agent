"""Render the saved conveyor transfer through the stock trajectory comparison viewer."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
from arm_motion_bench.dashboard_models import ur5e_robot
from traj_compare import (BarChart, BarSeries, Comparison, Insight, MetricCard, ReportPage, ReportTable, Situation, TableRow,
                          write_comparison_report)


def fmt(value, places=3):
    return "—" if value is None else f"{value:.{places}f}"


def rows_for(runs):
    return [[f"{run['speed_fraction']:.1f}", fmt(run["duration_s"], 2), fmt(run["full_trajectory_rms_mm"]),
             fmt(run["kpis"]["stop_error_max_mm"]), fmt(run["settle_max_mm"]),
             str(run["scene_clearance_violating_samples"]),
             ", ".join(name.replace("_", " ") for name, passed in run["verdicts"].items() if not passed) or "None"]
            for run in runs]


COLUMNS = ["Nominal speed", "Duration (s)", "Full TCP RMS (mm)", "Worst stop (mm)", "Final settle (mm)",
           "Physics samples inside scene margin", "Failed checks"]


def build(data, output, audit_path=None, goal_path=None, parent_path=None):
    baseline = json.loads((data / "baseline.json").read_text())
    runs = sorted(baseline["runs"], key=lambda run: run["speed_fraction"])
    full = next(run for run in runs if run["speed_fraction"] == 1.0)
    goal = json.loads(goal_path.read_text()) if goal_path is not None else None
    parent = json.loads(parent_path.read_text()) if parent_path is not None else None
    if goal is not None and (goal["controller_sha256"] != baseline["controller_sha256"]
                             or goal["datasets"]["portal"] != baseline["dataset_manifest_sha256"]):
        raise ValueError("goal evidence and playback must refer to the same frozen dataset and controller")
    if parent is not None and (parent["dataset_manifest_sha256"] != baseline["dataset_manifest_sha256"]
                               or [run["speed_fraction"] for run in parent["runs"]] != [run["speed_fraction"] for run in runs]):
        raise ValueError("baseline comparison must use the same full speed sweep")
    audited_full = None
    if audit_path is not None:
        audit = json.loads(audit_path.read_text())
        if audit["dataset_manifest_sha256"] != baseline["dataset_manifest_sha256"]:
            raise ValueError("independent audit and replay must refer to the same frozen dataset")
        audited_full = next(run for run in audit["runs"] if run["speed_fraction"] == 1.0)
        np.testing.assert_allclose(audited_full["tool_track_rms_mm"], full["tracking_rms_mm"], atol=1e-12, rtol=0)
    with np.load(data / full["recording"]) as signals:
        t = signals["t"]
        target = Situation("target", "Frozen full-speed route", t=t, q=signals["target_q"], qd=signals["target_qd"],
                           qdd=signals["target_qdd"], poses=signals["target_poses"])
        simulated = Situation("portal", "Portal simulation", t=t, q=signals["actual_q"], qd=signals["actual_qd"],
                              tau=signals["actual_torque"], poses=signals["actual_poses"])
        comparison = Comparison(
            title="Full-speed route", name="full-speed", joint_names=signals["joint_names"].tolist(), target=target,
            situations=[simulated, Situation("real", title="Physical arm", note="No physical arm data for this study")],
            robot=ur5e_robot(), tcp_frame="Conveyor station TCP", stats_mask=signals["moving"], stats_mask_label="moving samples",
            description="The complete frozen route at nominal 1.0 in the portal station's cell coordinates.",
        )
    checks = sum(all(run["verdicts"].values()) for run in runs)
    labels = [f"{run['speed_fraction']:.1f}" for run in runs]
    error_series = [BarSeries("Mount-aware controller" if goal else "Unchanged upright controller",
                              [run["full_trajectory_rms_mm"] for run in runs])]
    if parent is not None:
        error_series.append(BarSeries("Unchanged upright controller", [run["full_trajectory_rms_mm"] for run in parent["runs"]]))
    charts = [BarChart("Conveyor full-trajectory TCP RMS", labels, error_series, unit="mm")]
    if goal:
        for title, metric in (("Worst stop error by nominal speed", "stop_error_max_mm"),
                              ("Worst full-tape RMS by nominal speed", "full_trajectory_rms_mm")):
            series = [BarSeries(cohort.capitalize(), [goal["speeds"][label][cohort]["worst"][metric][metric]
                                                     for label in labels]) for cohort in goal["cohorts"]]
            charts.append(BarChart(title, labels, series, unit="mm", decimals=3))
    summary = ReportPage("Summary", metrics=[
        MetricCard("Full-speed tracking", f"{fmt(full['full_trajectory_rms_mm'])} mm", "Full TCP RMS including holds"),
        MetricCard("Worst full-speed stop", f"{fmt(full['kpis']['stop_error_max_mm'])} mm", "Final 0.1 s of each stop"),
        MetricCard("Passed every check", f"{checks}/{len(runs)}", "Simulation runs"),
    ], charts=charts,
        tables=[ReportTable(title="Matched speed sweep", columns=COLUMNS,
                            rows=[TableRow(cells=row) for row in rows_for(runs)])])
    insights = ReportPage("Insights", insights=[
        Insight("Upright calibration in the portal", "The portal turns the base 180° about its x axis. " + (
                "The mount-aware controller rotates the gravity contribution using the deployment's base-frame gravity."
                if goal else "The unchanged controller retained its upright gravity and friction fit.")),
        Insight("What clearance means", "The cell model checks each physics sample against the belt, rims, bins, beam and "
                "robot itself. The belt is static, the gripper is a collision capsule, and the arm carries no payload."),
    ])
    output.mkdir(parents=True, exist_ok=True)
    write_comparison_report(comparison, output / "comparison.html", title="UR5e conveyor tracking",
                            subtitle=f"{baseline['picks']} picks · {baseline['controller']}", summary=summary, insights=insights,
                            provenance={"controller SHA-256": baseline["controller_sha256"],
                                        "dataset manifest SHA-256": baseline["dataset_manifest_sha256"]},
                            breadcrumb=[("Conveyor study", "index.html"), ("Full-speed replay", "")])
    (output / "baseline.json").write_bytes((data / "baseline.json").read_bytes())
    if audit_path is not None:
        (output / "independent-audit.json").write_bytes(audit_path.read_bytes())
    if goal is not None:
        (output / "accuracy.json").write_bytes(goal_path.read_bytes())
    (output / "index.html").write_text(gallery(baseline, runs, full, audited_full, goal))


def goal_summary(goal):
    stop_key = "stop_error_max_mm"
    rms_key = "full_trajectory_rms_mm"
    overall = goal["overall"]
    stop = overall["worst"][stop_key]
    rms = overall["worst"][rms_key]
    result = "met" if stop[stop_key] < 0.5 and rms[rms_key] < 1 else "missed"
    rows = "".join(f'<tr><th scope="row">{html.escape(name.capitalize())}</th><td>{item["runs"]}</td>'
                   f'<td>{fmt(item["worst"][stop_key][stop_key])}</td><td>{fmt(item["worst"][rms_key][rms_key])}</td>'
                   f'<td>{item["runs_passing_all_gates"]}/{item["runs"]}</td></tr>'
                   for name, item in goal["cohorts"].items())
    narrative = f'''<p>The locked controller <strong>{result} both targets across {overall["runs"]} simulated runs</strong>.
The worst stop was <strong>{fmt(stop[stop_key])} mm</strong> against a 0.5 mm target at nominal {stop["fraction"]:.1f}.
The worst full-run RMS was <strong>{fmt(rms[rms_key])} mm</strong> against a 1.0 mm target at nominal {rms["fraction"]:.1f}.
The runs include 42 upright dev paths, 12 upright holdout paths and one 30-pick conveyor route.</p>
<p><a href="../../dashboard/#goals">Blackbox Goals</a> · <a href="accuracy.json">Measurements and source checksums</a> ·
<a href="../conveyor-baseline/">Unchanged-controller baseline</a> · <a href="../../comparison/#/sweeps">Upright speed sweeps</a></p>'''
    table = f'''<section><h2>All three test sets</h2><div class="scroll"><table><thead><tr><th scope="col">Test set</th>
<th scope="col">Runs</th><th scope="col">Worst stop (mm)</th><th scope="col">Worst full RMS (mm)</th>
<th scope="col">Passed all gates</th></tr></thead><tbody>{rows}</tbody></table></div>
<p><a href="comparison.html#tab=summary">Compare error distributions by nominal speed</a></p></section>'''
    return narrative, table


def gallery(baseline, runs, full, audited_full, goal=None):
    table = "\n".join("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>" for row in rows_for(runs))
    headers = "".join(f"<th scope=col>{html.escape(title)}</th>" for title in COLUMNS)
    passed_scene = sum(run["verdicts"]["scene_clearance"] for run in runs)
    clearance = ""
    if audited_full is not None:
        nearest = audited_full["minimum_contact_excluding_static_pairs"]
        pair = html.escape(" and ".join(nearest["pair"]).replace("_", " "))
        clearance = (f'<p>The separate 100 Hz audit found a <strong>{nearest["signed_distance_mm"]:.2f} mm</strong> gap '
                     f'between {pair} at {nearest["t_s"]:.2f} s. The gate requires 10 mm. '
                     '<a href="independent-audit.json">Independent pose and clearance audit</a></p>')
    heading = "UR5e tracking at every speed" if goal else "UR5e conveyor pick-and-place baseline"
    narrative = f'''<p><strong>{fmt(full['full_trajectory_rms_mm'])} mm full-run RMS at 1.0.</strong>
The {baseline['picks']}-pick route returned home in {fmt(full['duration_s'], 2)} seconds. The unchanged upright-trained
controller’s worst stop error was {fmt(full['kpis']['stop_error_max_mm'])} mm in the upside-down portal.
{passed_scene}/{len(runs)} runs passed the scene clearance check.</p>'''
    goal_table = ""
    if goal:
        narrative, goal_table = goal_summary(goal)
    controller_details = ("The controller used the mount orientation to correct the sign of the gravity term."
                          if goal else "The mounted simulation used the leader’s unchanged gains and upright calibration.")
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{heading}</title>
<style>
:root {{color-scheme:light dark;--paper:#f7f6f2;--ink:#222b29;--edge:#cad6d0;--link:#09645b}}
@media(prefers-color-scheme:dark) {{:root {{--paper:#141b19;--ink:#e5f1ef;--edge:#41554e;--link:#9adbd2}}}}
* {{box-sizing:border-box}} body {{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,sans-serif}}
main {{margin:auto;max-width:1180px;padding:clamp(16px,5vw,68px)}} h1 {{font-size:clamp(2.2rem,5vw,4rem);line-height:1.05;margin:.35em 0}}
p {{max-width:76ch}} a {{color:var(--link)}} figure {{margin:1.5em 0}} video {{display:block;width:100%;aspect-ratio:16/9;background:#202927;border-radius:8px}}
figcaption {{padding-top:.5em}} table {{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
th,td {{padding:.5em .65em;text-align:left;border-bottom:1px solid var(--edge)}} th {{font-size:.85em}} .scroll {{overflow:auto}}
iframe {{width:100%;height:680px;border:1px solid var(--edge);border-radius:8px}} section {{margin-top:2em}}
</style><body><main>
<header><h1>{heading}</h1>
{narrative}
{clearance}
<p><a href="comparison.html">Open stock full-speed playback and sweep charts</a> · <a href="baseline.json">Machine-readable results</a></p></header>
<figure><video controls autoplay muted loop playsinline preload="metadata" poster="media/poster.webp" aria-label="Recorded walkthrough of the stock playback">
<source src="media/walkthrough.mp4" type="video/mp4"><img src="media/walkthrough.gif" alt="The simulated arm replays the conveyor route"></video>
<figcaption>Browser recording of the stock trajectory comparison. <a href="media/walkthrough.gif">GIF fallback</a></figcaption></figure>
{goal_table}
<section><h2>Tracking across the same route</h2><p>Each speed uses the same ordered pick and bin poses. All distance
measurements use the portal station’s tool point. The clearance column counts 4 kHz physics samples inside the
station’s margin, which includes close approaches.</p>
<div class="scroll"><table><thead><tr>{headers}</tr></thead><tbody>{table}</tbody></table></div></section>
<section><h2>Full-speed replay</h2><iframe title="Stock trajectory comparison" src="comparison.html#tab=track" loading="lazy"></iframe></section>
<section><h2>What ran</h2><p>The stock arm_motion_bench PEP 0032 portal fixture has a static belt, four bins and a capsule
that stands in for the claw. The arm carried no payload. {controller_details} These are simulation results.
Physical part pickup and the dynamic Robotiq gripper remain unmeasured.</p></section>
</main></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--goal", type=Path)
    parser.add_argument("--parent", type=Path)
    args = parser.parse_args()
    build(args.data, args.output, args.audit, args.goal, args.parent)


if __name__ == "__main__":
    main()
