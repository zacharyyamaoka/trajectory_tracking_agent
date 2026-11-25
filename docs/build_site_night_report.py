"""Build the 2026-11-25 night report on the TTA site: reports/media/tta-site-night-2026-11-25.html (self-contained).

Three changes: (1) the site bar became the switcher, (2) the Datasets page's trajectories open in Rerun's web viewer
as robot_msgs' stock URDF viewer, (3) the page is built by the blackbox_agent package in CI. Every image and the hero
video were recorded from the site built exactly as CI builds it (`blackbox build` at tag v0 = blackbox-agent 0.1.4 on
a clean clone of 239d1dc), served on 127.0.0.1:8940. The captures and the scripts that took them live in
outputs/report-night-1125/ (gitignored; capture/ holds the Playwright scripts, measure.json the page probe).

The report links Zach's machine paths, so it is written under reports/media/ (gitignored), never into the public tree.
Run: uv run --all-extras python docs/build_site_night_report.py
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "outputs" / "report-night-1125"
OUT = REPO / "reports" / "media" / "tta-site-night-2026-11-25.html"
LIVE = "https://zacharyyamaoka.github.io/trajectory_tracking_agent/"
MIME = {".webp": "image/webp", ".png": "image/png", ".mp4": "video/mp4"}


def data_uri(name: str) -> str:
    path = MEDIA / name
    return f"data:{MIME[path.suffix]};base64,{base64.b64encode(path.read_bytes()).decode()}"


def figure(name: str, caption: str, alt: str) -> str:
    return (f'<figure><img loading="lazy" src="{data_uri(name)}" alt="{html.escape(alt)}">'
            f"<figcaption>{caption}</figcaption></figure>")


def measured() -> dict:
    probe = json.loads((MEDIA / "measure.json").read_text())
    pages = {k: v for k, v in probe.items() if not k.startswith(("landing", "deeplink"))}
    landings = {k: v for k, v in probe.items() if k.startswith("landing")}
    return {
        "loads": len(pages) + len(landings),
        "switchers": sum(v["switcher"] for v in pages.values()),
        "pages": len(pages),
        "errors": sum(len(v["errors"]) for v in probe.values() if isinstance(v, dict)),
        "bad": sum(len(v["bad"]) for v in probe.values() if isinstance(v, dict)),
        "chips": sorted({v["chips"] for v in landings.values()}),
        "run_requests": sorted({v["run_requests"] for v in landings.values()}),
        "caption": next(iter(landings.values()))["cap"],
        "deeplink": " · ".join(probe["deeplink p1/dev-000"][:2]),
    }


CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#5f5f5a;--line:#e3e2de;--card:#fff;--accent:#0e7c86;--ok:#1f7a3a;--bad:#b3261e;--warn:#9a5b00;--code:#f3f2ef}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--fg:#ecebe7;--muted:#a3a29c;--line:#34332f;--card:#1e1e1c;--accent:#4cc2c4;--ok:#5cc27f;--bad:#ff8a80;--warn:#f0b35a;--code:#262522}}
html,body{overflow-x:clip}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 16px 80px}h1{font-size:25px;margin:0 0 8px;line-height:1.25}
h2{font-size:19px;margin:40px 0 10px;border-top:1px solid var(--line);padding-top:22px}h3{font-size:16px;margin:20px 0 6px}
p,li{max-width:80ch}.muted{color:var(--muted)}code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:13px;overflow-wrap:anywhere}
pre{background:var(--code);padding:12px 14px;border-radius:8px;overflow:auto;font-size:13px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere}
.verdict{font-size:17px;font-weight:600;max-width:none}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.kpi b{font-size:22px;display:block}.kpi span{font-size:13px;color:var(--muted)}
video,img{max-width:100%;height:auto;border-radius:10px;border:1px solid var(--line);display:block}
figure{margin:0}figcaption{font-size:13px;color:var(--muted);margin:6px 2px 0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:16px;margin:12px 0}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:12px;margin:12px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.card h3{margin-top:0}
.tag{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:999px;border:1px solid currentColor}
.live{color:var(--ok)}.local{color:var(--warn)}.fixed{color:var(--ok)}.open{color:var(--bad)}.pkg{color:var(--warn)}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.tablewrap{overflow-x:auto}
ol.steps li{margin:2px 0}
"""


def main() -> None:
    m = measured()
    hero = (f'<video src="{data_uri("hero.mp4")}" poster="{data_uri("poster.webp")}" autoplay muted loop playsinline controls '
            f'aria-label="Hero: landing replay to the Rerun viewer">'
            f'<img src="{data_uri("poster.webp")}" alt="First frame of the hero: the landing replay"></video>')
    findings = [
        ("fixed", "CI's 0.1.4 build dropped the landing's run row: 0 of 244 run chips drawn",
         "Fixed in <code>239d1dc</code>: <code>site/nav.json</code> turns on <code>landing.evidence.picker</code>, the lock follows "
         f"<code>v0</code> to 0.1.4. Measured here on the CI build: <b>{'/'.join(map(str, m['chips']))}</b> chips at 1280 and 390, light and dark. "
         "Red first: <code>tests/test_site_bar.py::test_the_landing_replay_has_its_run_picker_and_the_lock_is_the_package_ci_builds</code>."),
        ("open", "160 of 2688 Model × Dataset cells open the wrong run",
         f"Still open. <code>index.html?solution=p1&amp;task=workspace-dev-000#run</code> lands on <b>{html.escape(m['deeplink'])}</b> "
         "(the best run, not p1's 2-gate fail). The stock landing ignores the query. Needs the package to read something like "
         "<code>?run=&lt;record path&gt;</code> into <code>bb-evidence</code>'s existing <code>settings.run</code>, then "
         "<code>tools/build_dropins.py</code> (a peer has an uncommitted edit there) and <code>tests/test_dropins.py:204</code> to follow."),
        ("pkg", "The landing downloads every run record to show one",
         f"Package behaviour. Measured: <b>{'/'.join(map(str, m['run_requests']))}</b> <code>/data/runs/*.json</code> requests per landing load "
         "(32.4 MB uncompressed; about 8.5 MB gzipped on Pages); the old landing fetched 2. They colour the chips. "
         "Fix belongs in blackbox_agent: a verdict field in <code>playback.runs</code>, or lazy loads."),
        ("pkg", "Hero caption reads “A saved run of 244 runs”",
         f"Package text (<code>template/site/index.html:135</code>). On the CI build: “{html.escape(m['caption'])}…”."),
    ]
    finding_rows = "\n".join(
        f'<tr><td><span class="tag {k}">{ {"fixed": "fixed", "open": "open", "pkg": "package gap"}[k] }</span></td>'
        f"<td><b>{t}</b><br>{body}</td></tr>" for k, t, body in findings)
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<meta name=color-scheme content="light dark"><title>TTA site, the night of 2026-11-24/25</title><style>{CSS}</style></head><body><main>
<h1>Trajectory Tracking Agent site: the switcher, Rerun's URDF viewer, and a page the package builds</h1>
<p class=verdict>The switcher bar and the Datasets → Rerun viewer are live (origin/main <code>a286c26</code>). The package-built page is committed on TTA
<code>main</code> @ <code>239d1dc</code> but <b>not pushed</b>, so the live page is still the vendored build until the dispatcher pushes.
One finding is still open: 160 Model × Dataset cells open the wrong run.</p>
<p class=muted>Everything below was recorded from the site built the way CI builds it: <code>blackbox build</code> at tag <code>v0</code>
(blackbox-agent 0.1.4, <code>031adc3</code>) on a clean clone of <code>239d1dc</code>, served locally. Recorded 2026-11-25 by a Claude Code
subagent (claude-opus-5-5).</p>
<div class=kpis>
<div class=kpi><b>{m['switchers']}/{m['pages']}</b><span>page loads draw the switcher (5 pages × 1280/390 × light/dark)</span></div>
<div class=kpi><b>{m['errors']} / {m['bad']}</b><span>console errors / 4xx responses over {m['loads']} page loads</span></div>
<div class=kpi><b>0.000023 mm</b><span>worst gap between the URDF's tool and the ruler's, 54 tapes, 12,870 samples (gate 1 mm)</span></div>
<div class=kpi><b>1.446 mm</b><span>UR's own <code>ur_description</code> flange vs the ruler: fails the same gate</span></div>
<div class=kpi><b>963 → 588</b><span>tracked <code>site/</code> files; commit −174k lines</span></div>
<div class=kpi><b>{m['chips'][0]}</b><span>run chips on the CI build's landing (0 before the fix)</span></div>
</div>

<h2>Hero: the landing to Rerun in 20 s</h2>
{hero}
<ol class=steps>
<li><b>Landing</b>: the package's stock landing replays a saved run (p5s-pass3 on workspace-dev-000), the run row below it.</li>
<li><b>Open the dashboard</b>: the package's viewer, reading this box's <code>nav.json</code> and <code>data/state.json</code>.</li>
<li><b>The switcher</b>: “Trajectory Tracking Agent / Black box ▾”, its menu grouped Black box | Trajectory.</li>
<li><b>Trajectory coverage</b> → Deployments, then <b>Datasets · UR5e</b>.</li>
<li>Find <code>dev-029</code> (via_points, 2.11 m tool path), the Trajectories tab, its record, hover <b>Open in the Rerun web viewer</b>.</li>
<li><b>Rerun 0.40.0</b> (app.rerun.io) on the locally served <code>.rrd</code>, played: the URDF arm, the ruler's tool path, q tabs in degrees.</li>
</ol>
<p class=muted>Cuts: loading gaps removed (Rerun takes about 11 s to load in headless Chromium's software rasterizer, and plays slower than
real time there; the orange “Software rasterizer” label is that, not the site). The button itself opens the same viewer with
<code>?url=</code> the <b>Pages</b> copy of the file; the recording points it at the local copy instead. The two are byte-identical
(sha256 <code>575fba1f…</code> for dev-007, checked against Pages). No GIF fallback: at this length it would be several MB, over the page
budget; the poster frame stands in where video does not play.</p>

<h2>1 · The site bar is the switcher <span class="tag live">live, a286c26</span></h2>
<p>Zach, 2026-11-24 ~21:30: “its still the top row tabs but instead of having them spread out its the drop down”. The box name goes to the landing;
the open dashboard has ▾; its menu lists every dashboard under its group heading; the open dashboard's own tabs or pages sit in the row below.
Drawn by the package's <code>bb-site-nav</code> from this box's hand-written <code>site/nav.json</code> (<code>"layout": "switcher"</code>).</p>
<div class=grid2>
{figure("switcher-1280-dark.webp", "1280, dark: the menu open on the Black box dashboard.", "Switcher menu open, dark")}
{figure("switcher-390-light.webp", "390, light: the switcher takes the second row on a phone.", "Switcher on a phone")}
</div>

<h2>2 · Datasets · UR5e → Rerun's URDF viewer <span class="tag live">live, c876631</span></h2>
<p>Every trajectory's record has <b>Open in the Rerun web viewer</b> (Rerun 0.40.0, the version that wrote the file) and <b>Download the .rrd</b>.
Each recording is robot_msgs' stock URDF viewer: the arm moving through the trajectory, the ruler's tool point (flange + 0.1 m) and its path,
and tabs of q, qd, qdd, qddd, q/qd/qdd and TCP, in degrees (Zach's R3 and his tabs). The arm is the ruler's UR5e kinematics (MuJoCo Menagerie,
via robot_controllers) dressed in UR's <code>ur_description</code> collision meshes. <code>tests/test_coverage_robot.py</code> holds it to the ruler:</p>
<pre>URDF tool vs the ruler's tool point over 54 tapes, 12870 samples: max 0.000023 mm
tool path vs the URDF's tool: max 0.000023 mm, 0.000005 deg
ur_description's flange vs the ruler's tool point: max 1.446 mm
6 passed in 2.31s</pre>
<p class=muted>Re-run tonight against <code>239d1dc</code>. UR's own URDF (the datasheet's DH lengths) misses the 1 mm gate, which is why the chain is the ruler's.</p>
<div class=grid2>
{figure("s-rerun.webp", "Rerun 0.40.0 on dev-029 mid-play: the URDF arm, the tool path start → end, the q tab (degrees, travel and margin to limit per joint).", "Rerun viewer playing a trajectory")}
{figure("datasets-1280-light.webp", "The Datasets · UR5e page on the CI build: 54 trajectories, 6 joint grids on one colour scale.", "Datasets page")}
</div>

<h2>3 · The page is built by blackbox_agent in CI <span class="tag local">local, 239d1dc, not pushed</span></h2>
<p><code>.github/workflows/pages.yml</code> is now six lines calling <code>zacharyyamaoka/blackbox_agent/.github/workflows/site.yml@v0</code>
with <code>permissions: {{contents: read, pages: write, id-token: write}}</code>. <code>blackbox check</code> exits 0: “the box is in the format”.</p>
<div class=tablewrap><table>
<tr><th>Removed</th><th>Why it can go</th></tr>
<tr><td><code>site/dashboard/</code> (370 files)</td><td>the package's viewer is served in its place</td></tr>
<tr><td><code>site/index.html</code>, <code>site/assets/</code></td><td>the package's stock landing; its hero replays <code>state.playback.runs</code></td></tr>
<tr><td><code>tools/bb/</code> (25 files, the vendored fold)</td><td><code>tools/build_site.py</code> folds with the package's fold</td></tr>
<tr><td><code>site/vendor/bb-evidence.js</code>, <code>bb-headliner.js</code></td><td>the package ships both</td></tr>
</table></div>
<div class=tablewrap><table>
<tr><th>Kept</th><th>Why</th></tr>
<tr><td><code>site/nav.json</code></td><td>the switcher's menu; now also turns on the landing's run picker</td></tr>
<tr><td><code>comparison/</code> (42 run reports), <code>deployments/</code>, <code>datasets/ur5e/</code> (54 <code>.rrd</code>), <code>models-datasets/</code></td><td>the domain dashboards, carried byte for byte by <code>blackbox build</code></td></tr>
<tr><td><code>site/data/</code> (<code>state.json</code>, <code>runs/</code>, <code>junit*</code>)</td><td><code>state.json</code> is re-folded, its <code>playback</code> slice (244 runs) kept</td></tr>
<tr><td><code>site/vendor/data-ui</code> (1f7c0047)</td><td>the package's data-ui (78d2049) has no <code>views/coverage.js</code>; the Datasets page needs it</td></tr>
</table></div>
<div class=grid2>
{figure("landing-1280-light.webp", "The stock landing on the CI build, 1280 light: verdict, the run row (244 chips), the replay.", "Landing light")}
{figure("landing-1280-dark.webp", "The same at 1280 dark.", "Landing dark")}
</div>
<h3>Phones (390 px)</h3>
<div class=grid4>
{figure("landing-390-dark.webp", "Landing, dark.", "Landing on a phone, dark")}
{figure("datasets-390-light.webp", "Datasets · UR5e, light.", "Datasets on a phone, light")}
{figure("datasets-390-dark.webp", "Datasets · UR5e, dark.", "Datasets on a phone, dark")}
</div>
<div class=tablewrap><table>
<tr><th>Measured</th><th class=num>Before (a286c26)</th><th class=num>After (239d1dc)</th></tr>
<tr><td>Tracked <code>site/</code> files</td><td class=num>963</td><td class=num>588</td></tr>
<tr><td><code>site/</code> on disk</td><td class=num>166 MB</td><td class=num>149 MB</td></tr>
<tr><td>Built site (incl. the package's 17 MB dashboard)</td><td class=num>167 MB</td><td class=num>166 MB</td></tr>
<tr><td>Landing: run records fetched per load</td><td class=num>2</td><td class=num>{m['run_requests'][0]}</td></tr>
<tr><td>Tests (<code>uv run --all-extras pytest</code>)</td><td class=num>—</td><td class=num>1043 passed</td></tr>
<tr><td><code>build_site.py parity</code> / <code>shoot</code></td><td class=num>—</td><td class=num>244/244 runs · 13/13 checks</td></tr>
</table></div>
<p class=muted>Before/after sizes and test counts are the migration lane's; the page-load, chip, request and URDF numbers on this page were measured for this report.</p>

<h2>Findings and outcomes</h2>
<div class=tablewrap><table>{finding_rows}</table></div>
{figure("deeplink.webp", "The open finding: <code>index.html?solution=p1&amp;task=workspace-dev-000#run</code> on the CI build shows p5s-pass3 (all gates pass), not p1.", "Deep link opens the wrong run")}

<h2>Decision surface</h2>
<div class=cards>
<div class=card><h3>Done and proved</h3><ul>
<li>Switcher on all 5 pages, 1280/390, light/dark: {m['switchers']}/{m['pages']}, {m['errors']} errors, {m['bad']} 4xx.</li>
<li>Rerun 0.40.0 opens the URDF recording and plays it (hero step 6); URDF tool within 0.000023 mm of the ruler.</li>
<li>CI-identical build is 0.1.4 and draws the run row ({m['chips'][0]} chips).</li></ul></div>
<div class=card><h3>Decided for you</h3><ul>
<li>Recorded Rerun on the local <code>.rrd</code> (byte-identical to Pages) so the report shows tonight's build, not the live one.</li>
<li>Poster instead of a GIF fallback, to stay under the page budget.</li>
<li><code>reports/media/</code> added to <code>.gitignore</code> (it was only in this clone's <code>.git/info/exclude</code>).</li></ul></div>
<div class=card><h3>Left</h3><ul>
<li><b>Next:</b> push <code>239d1dc</code> (the dispatcher's, after its suite + private-path scan), then watch the first <code>site.yml@v0</code> run.</li>
<li><b>Blocked on the package:</b> <code>?run=</code> deep links, lazy chip colouring, the caption text.</li>
<li><b>Then:</b> the cell URLs in <code>build_dropins.py</code>, once its peer edit lands.</li></ul></div>
<div class=card><h3>Needs you</h3><p>Nothing.</p>
<h3>Deliberately not done</h3><ul><li>No push, no edit to the package or its lab, no touch of <code>tools/build_dropins.py</code>.</li></ul></div>
</div>

<h2>Undo</h2>
<pre>git -C ~/trajectory_tracking_agent revert 239d1dc b95a20c   # the package build (not pushed yet: nothing live to roll back)
git -C ~/trajectory_tracking_agent revert a286c26           # the switcher (live)
git -C ~/trajectory_tracking_agent revert c876631           # Datasets → Rerun URDF recordings (live)</pre>

<h2>How this was recorded</h2>
<pre>git clone ~/trajectory_tracking_agent /tmp/bbx-night/tta                       # 239d1dc
uvx --from git+https://github.com/zacharyyamaoka/blackbox_agent@v0 blackbox build --box . --out /tmp/bbx-night/_site
# blackbox-build.json: blackbox-agent 0.1.4, ref 239d1dcd…, landing stock, kept playback
static server with CORS on 127.0.0.1:8940; Playwright 1.64.1 Chromium, 1280×800 video;
Chromium flag --disable-features=LocalNetworkAccessChecks so app.rerun.io may fetch from 127.0.0.1</pre>
<p class=muted>Scripts and raw captures: <code>outputs/report-night-1125/</code> (capture/record.py, capture/stills.py, measure.json). Live page: <a href="{LIVE}">{LIVE}</a>.</p>
</main></body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    print(f"{OUT} {OUT.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
