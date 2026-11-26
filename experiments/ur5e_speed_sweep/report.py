"""Write the UR5e speed study report with links to the canonical viewer pages."""

import argparse
import html
import json
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
OUTPUT = SOURCE.parents[1] / "site" / "reports" / "ur5e-speed-sweep.html"
sys.path.insert(0, str(SOURCE.parents[1] / "tools"))
import site_bar  # noqa: E402

MEDIA = "media/ur5e-speed-sweep"
SWEEPS = "../comparison/#/sweeps"
COVERAGE = "../datasets/ur5e/#tab=trajectory-speed-scale"
TARGETS = "../comparison/workbench/#tab=targets"
WINNER = "p5s-damping185-refit"


def bar_rows(labels, values):
    maximum = max(values)
    return "\n".join(f'<tr><th scope="row">{html.escape(label)}</th><td><meter min="0" max="{maximum}" '
                     f'value="{value}" aria-label="{value:.2f} seconds"></meter></td><td>{value:.2f}</td></tr>'
                     for label, value in zip(labels, values, strict=True))


def source_link(sources, key, title):
    return f'<a href="{html.escape(sources[key], quote=True)}">{html.escape(title)}</a>'


def build(study, limits):
    speeds = study["fractions"]
    controllers = study["controllers"]
    winner_rows = controllers[WINNER]["by_speed"]
    full = winner_rows[-1]
    target_count = len(study["targets"])
    full_winner = full["median_mm"]
    slow = winner_rows[0]["median_mm"]
    eligible = [(result["median_mm"], speed) for speed, result in zip(speeds, winner_rows, strict=True)
                if result["median_mm"] is not None]
    best_error, best_speed = min(eligible)
    all_pass = sum(bin_result["all_gates_pass"] for solution in controllers.values() for bin_result in solution["by_speed"])
    simulated_peak = max(full["simulated_peak_deg_s"])
    simulated_over = full["simulated_dwell_s"][-1]
    frozen = limits["all"]
    frozen_total = frozen["duration_s"]
    decile_labels = ["0–10%", *(f">{index * 10}–{(index + 1) * 10}%" for index in range(1, 10))]
    frozen_bars = bar_rows(decile_labels, frozen["max_joint_speed_decile_time_s"])
    winner_dwell = full["simulated_dwell_s"]
    measured_bars = bar_rows(["0%", ">0–10%", *decile_labels[1:], ">100%"], winner_dwell)
    planned_bars = bar_rows([f"{speed:.1f}" for speed in speeds], [item["elapsed_s"] for item in study["nominal_tapes"]])
    near_limit = frozen["max_joint_speed_decile_time_s"][-1]
    table = "".join(
        f'<tr><th scope="row">{html.escape(name)}</th><td>{row["median_mm"]:.5f}</td>'
        f'<td>{row["all_gates_pass"]}/{target_count}</td><td>{max(row["simulated_peak_deg_s"]):.3f}</td></tr>'
        for name, item in sorted(controllers.items(), key=lambda item: item[1]["by_speed"][-1]["median_mm"])
        for row in (item["by_speed"][-1],)
    )
    sources = limits["source_urls"]
    manual = source_link(sources, "ur_manual", "UR5e user manual")
    sheet = source_link(sources, "ur_technical_sheet", "UR5e technical sheet")
    driver = source_link(sources, "ur_ros2_description", "UR ROS 2 joint limits")
    hardware = source_link(sources, "ur_safety_configuration", "UR safety configuration")
    peak_table = "".join(
        f'<tr><th scope="row">{name}</th><td>180</td><td>{target:.3f}</td><td>{measured:.3f}</td></tr>'
        for name, target, measured in zip(("Base", "Shoulder", "Elbow", "Wrist 1", "Wrist 2", "Wrist 3"),
                                         frozen["joint_peak_abs_velocity_deg_s"], full["simulated_peak_deg_s"], strict=True)
    )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UR5e speed sweep · Trajectory Tracking Agent</title>
<style>
:root {{color-scheme:light dark;--bg:#f8f9f5;--panel:#fff;--text:#202822;--muted:#4d5e54;--line:#d5ddd6;--accent:#07635c}}
@media(prefers-color-scheme:dark) {{:root {{--bg:#131b18;--panel:#1d2923;--text:#eff6f0;--muted:#bad2c4;--line:#3e5248;--accent:#89dcd4}}}}
* {{box-sizing:border-box}} body {{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,sans-serif}}
main {{max-width:1180px;margin:auto;padding:clamp(16px,4vw,64px)}} a {{color:var(--accent);text-underline-offset:.18em}}
h1 {{font-size:clamp(2.1rem,5vw,4.3rem);letter-spacing:-.05em;line-height:1.05;margin:.28em 0}}
h2 {{margin:0 0 .38em;letter-spacing:-.025em}} p {{margin:.45em 0 1em}} .lede {{font-size:1.16em;max-width:70ch}}
.quiet,figcaption {{color:var(--muted)}} nav {{display:flex;gap:8px 20px;flex-wrap:wrap;margin:1.3em 0}}
figure {{margin:1.45em 0}} video,img {{display:block;width:100%;height:auto;background:var(--panel);border-radius:10px}}
video {{aspect-ratio:16/9;border:1px solid var(--line)}} figcaption {{margin-top:.65em;font-size:.9em}}
[hidden] {{display:none !important}}
.grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));gap:14px}}
section {{margin:25px 0}} .panel {{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:clamp(14px,3vw,27px)}}
table {{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}} th,td {{text-align:right;padding:.35em .5em;border-bottom:1px solid var(--line)}}
th:first-child {{text-align:left}} .bars th,.bars td {{padding:.25em .35em}} meter {{width:100%;min-width:50px;height:1em;display:block;accent-color:var(--accent)}}
meter::-webkit-meter-optimum-value {{background:var(--accent)}} .bars th {{width:6.4em}} .bars td:last-child {{width:4em}}
.scroll {{overflow:auto}} .chart {{width:100%;height:620px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}}
summary {{cursor:pointer;color:var(--accent);margin:.6em 0}} footer {{border-top:1px solid var(--line);margin-top:35px;padding-top:14px}}
</style></head><body><main>
<header><h1>UR5e tracking across speeds</h1>
<p class="lede"><strong>{full_winner:.5f} mm at full speed.</strong> The leading controller passed all five gates on
{full['all_gates_pass']} of {target_count} simulated dev trajectories at 1.0. Its median error was {slow:.5f} mm at 0.1 and
lowest at {best_speed:.1f} ({best_error:.5f} mm).</p>
<nav aria-label="Open the stock viewers"><a href="{SWEEPS}">Speed sweeps</a><a href="{COVERAGE}">Trajectory speed scale</a>
<a href="{TARGETS}">Targets and runs</a></nav></header>
<figure><img id="chart-poster" src="ur5e-sweep-chart.webp" alt="The stock speed sweep with five controller curves and ten speed bins" width="1280" height="720">
<video id="walkthrough" hidden controls autoplay loop muted playsinline preload="metadata" poster="ur5e-sweep-chart.webp"
aria-label="Walkthrough of the live UR5e viewers" data-src="{MEDIA}/walkthrough.mp4"></video>
<figcaption>Captured in the browser from the stock viewers. <a id="animated-fallback" hidden href="{MEDIA}/walkthrough.gif">Animated fallback</a></figcaption></figure>
<section class="panel"><h2>Tracking error by speed</h2>
<p>Five controller configurations ran the same {target_count} simulated dev trajectories at each of ten speeds.
Every point is the median per-trajectory tool RMS over moving samples. Bands show the middle half of the targets.
The log scale keeps the closely spaced curves readable. {all_pass:,} of {study['trials']:,} runs passed every gate.</p>
<p><a href="{SWEEPS}">Open the stock chart and its measurement table</a></p>
<iframe class="chart" title="Stock Trajectory Comparison speed sweep" loading="lazy" src="{SWEEPS}"></iframe>
<h3>At nominal speed 1.0</h3><div class="scroll"><table><thead><tr><th>Controller</th><th>Median RMS (mm)</th>
<th>All gates pass</th><th>Peak simulated speed (°/s)</th></tr></thead><tbody>{table}</tbody></table></div></section>
<section id="time-at-speed"><h2>Time spent at each speed</h2>
<p>There are two speed measures. The nominal fraction describes how far the whole tape was slowed from its fastest
saved timing. Instantaneous utilization is the fastest joint at that moment as a fraction of 180°/s.</p>
<div class="grid"><div class="panel"><h3>Frozen dataset · joint-speed utilization</h3>
<p>All {frozen['tapes']} frozen tapes have nominal speed 1.0. Across their {frozen_total:.2f} s, the planned joints spend
{near_limit:.2f} s ({100 * near_limit / frozen_total:.1f}%) above 90% of the speed limit. The first band includes holds.</p>
<table class="bars"><thead><tr><th>Utilization</th><th colspan="2">Elapsed seconds</th></tr></thead><tbody>{frozen_bars}</tbody></table>
<p><a href="{COVERAGE}">Open the frozen dataset’s speed distribution</a></p></div>
<div class="panel"><h3>Matched sweep · nominal speed</h3><p>Each fraction has {target_count} dev trajectories, or
{len(speeds) * target_count} tapes across the sweep. The times count each tape once across all controllers.</p>
<table class="bars"><thead><tr><th>Fraction</th><th colspan="2">Elapsed seconds</th></tr></thead><tbody>{planned_bars}</tbody></table></div></div>
<details class="panel"><summary>Simulated time at each instantaneous speed · leading controller, nominal 1.0</summary>
<p>The joint velocities are from the simulator at 100 Hz. This covers {sum(winner_dwell):.2f} s of dev trajectories,
including {simulated_over:.2f} s above 180°/s. Peak sampled speed was {simulated_peak:.3f}°/s.</p>
<table class="bars"><thead><tr><th>Utilization</th><th colspan="2">Elapsed seconds</th></tr></thead><tbody>{measured_bars}</tbody></table></details></section>
<section class="panel"><h2>UR5e joint-limit audit</h2>
<p>UR rates all six joints at <strong>180°/s</strong>. The frozen references use that cap and peaked at
{max(frozen['joint_peak_abs_velocity_deg_s']):.5f}°/s. The simulation gate permits 189°/s at the physics rate,
so a run can pass the gate while exceeding the 180°/s planning cap. The installed arm’s tracking and active safety limits remain unverified.</p>
<div class="scroll"><table><thead><tr><th>Joint</th><th>UR rating (°/s)</th><th>Frozen target peak (°/s)</th>
<th>Simulated winner peak (°/s)</th></tr></thead><tbody>{peak_table}</tbody></table></div>
<p>UR’s user manual lists ±160° elbow travel and ±360° on the other axes. Its technical sheet lists ±360° for the
elbow. The model plans to approximately ±180° at the elbow, close to the ROS 2 planning range. Every frozen reference
sample is inside ±160°. The local acceleration and jerk caps are timing inputs, with no corresponding UR ratings in the cited joint-limit files.</p>
<p>{manual} · {sheet} · {driver} · {hardware}</p></section>
<footer><strong>Method.</strong> The off-score study takes each pinned full-speed dev tape, stretches time by the inverse
of the nominal fraction, and samples it at 100 Hz. The final hold rounds the timing up by less than 0.01 s. At 1.0 each score
and gate verdict is checked against the frozen scorecard. The stock Targets and Runs workbench opens the saved 1.0 recordings.
<p><a href="https://github.com/zacharyyamaoka/trajectory_tracking_agent/tree/main/experiments/ur5e_speed_sweep">Source and evidence</a></p></footer>
</main>
<script>
const walkthrough = document.getElementById('walkthrough');
fetch(walkthrough.dataset.src, {{method: 'HEAD'}}).then(response => {{
    if (!response.ok) return;
    walkthrough.addEventListener('loadedmetadata', () => {{
        document.getElementById('chart-poster').hidden = true;
        document.getElementById('animated-fallback').hidden = false;
        walkthrough.hidden = false;
    }}, {{once: true}});
    walkthrough.src = walkthrough.dataset.src;
}}).catch(() => {{ /* The static screenshot remains available without the retained video. */ }});
</script></body></html>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=OUTPUT, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    page = build(json.loads((SOURCE / "study.json").read_text()), json.loads((SOURCE / "limits.json").read_text()))
    args.output.write_text(site_bar.include(page, OUTPUT, "comparison", page_id="comparison-study"))


if __name__ == "__main__":
    main()
