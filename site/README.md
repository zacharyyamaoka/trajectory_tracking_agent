# site/: the landing page

A static page that **plays back saved runs**. Nothing is simulated or scored in the browser: every run was simulated
and scored by the ruler when `tta evaluate` ran it, and every number on the page is the ruler's own, copied from that
run's record. (Zach, 2026-11-24: "You can just playback saved runs"; until then the page ran MuJoCo's WebAssembly
build and Pyodide live. Git history keeps that runtime.)

**The landing and the dashboard are blackbox_agent's, not files here** (since 2026-11-25). `.github/workflows/pages.yml`
calls the package's `site.yml@v0` on every push to `main`; it runs `blackbox build`, which writes the package's stock
landing (`index.html`) and dashboard (`dashboard/`) around every other file of this `site/` at the pushed commit (the
domain dashboards, `nav.json`, `data/`, `vendor/data-ui/`) and re-folds `data/state.json`, keeping this build's
`playback` slice. Never add `site/index.html` (the build drops it; `site/overrides/index.html` would replace the stock
landing, and the dashboard counts it as an override). Preview exactly what the push will publish, from the last commit:

```bash
uvx --from git+https://github.com/zacharyyamaoka/blackbox_agent@v0 blackbox serve --box ~/trajectory_tracking_agent
```

The stock landing's hero is the viewer's **`<bb-evidence>`** (its CONTRACT §14) whenever `state.json`'s playback slice
lists runs, which this build writes: one saved run, Lens (the 3D replay large, a card per metric) or Recorder (every
metric a lane on one timeline), showing which samples each number counted, where it failed and its worst moment. Its
run row (one chip per listed run) picks the bb-run/1 record it plays; the Ticker headliner sits under it as Progress,
then the gates. (Zach, 2026-11-24: "it should use the newer 3D explanation things we designed, they are in the
storybook"; until 2026-11-25 this repo had its own landing with Solution and Dev task pickers, a joint-error plot, the
black box and the population. Git history keeps it.)

## Rebuild it

After new solutions are scored (`tta evaluate <id>` writes their run records to `outputs/runs/`):

```bash
uv run --all-extras python tools/build_site.py build
```

It rewrites `site/data/` (the run records, `state.json`, `page.json`, the solution sources) and then runs `check`.
`state.json` is folded by the installed blackbox_agent package (the `site` extra, the commit `uv.lock` pins; `BB_FOLD`
overrides), the same fold CI runs; each record is written by the viewer's `tools/fold_runs.py`, read from the
blackbox_agent lab beside this repo (`~/blackbox_agent`; `BB_FOLD_RUNS` overrides). It refuses
when a run it should ship has no record, or a record whose numbers differ from the scorecard (stale); it prints the
`uv run --all-extras tta evaluate <id>` that rewrites it. Records are never written by hand.

## Which runs ship: the rule

Read from `ledger.jsonl` (each solution's latest dev row) by `selection()` in `tools/build_site.py`:

1. **Every scored solution**, except those tagged `ablation` in `meta.json`, on **one representative dev task per task
   kind**: the first dev task of each kind in dataset order. Today: `workspace-dev-000` (ISO 9283 path),
   `workspace-dev-001` (ISO 9283 cube), `workspace-dev-002` (A→B line), `workspace-dev-003` (A→B joint move),
   `workspace-dev-016` (via points).
2. **The best admissible solution and the best admissible generation-0 solution** (tag `gen-0`) on **all 42 dev
   tasks**.

Ablation solutions test which parts of a solution matter; they are not search progress, so they are left out of the
playback and the run row.

On 2026-11-24 that is 244 (solution, task) runs: 34 solutions × 5 tasks, plus p5s-pass3 (best) and p6s (best of
generation 0) on the other 37 tasks. The run row lists only what ships. If the page ever had to shrink, it would ship fewer tasks, never fewer numbers per run.

## What is in `site/data/`

| Path | What |
|---|---|
| `state.json` | bb-state/1, the viewer's fold of this repo at HEAD (the headliner reads it), plus the `playback` slice this build writes: every shipped run's record path (`runs/<solution>/<task>.json`, relative to `state.json`), `schema: "bb-run/1"`, a label and `admissible` (every gate passed on that task, the verdict the record shows; the run chips colour from it without fetching the record) |
| `runs/<solution>/<task>.json` | one saved run as a **bb-run/1** record (the viewer's `schemas/run-record.schema.json`): the ruler's metrics with their rules, which samples each counted, where it failed and its peak; the time base and stops; channels (tool error, target and measured tool points and joint angles, torque and speed as a % of each cap, the lowest point's floor clearance, power); the arm's drawn geom poses (target ghost and measured) |
| `runs/index.json` | per solution its shipped tasks (record, objective, every gate passed?) and what scored it (repo commit, robot_controllers / robot_msgs commits, `solution.py` sha256, date), and the build's honesty checks per run |
| `page.json` | the black-box contract, the robot_msgs types, the leaderboard (from every scorecard), the best solution's code (the retired landing's; kept as the leaderboard's check) |
| `solutions/<id>/solution.py` | byte copies of each shipped solution's code |

How a record is made: `build` computes what is drawn natively from `tta evaluate`'s run record (the arm's geom poses from
the deployment's own model and `mujoco.mj_kinematics`, checked against `deployment.link_points`; the tool error from the
ruler's `metrics.tool_errors_m`; the stop errors from `metrics.stop_errors_mm`; the floor's lowest moving point from
`deployment.link_points`) into a compact binary export (`outputs/site/playback/`, gitignored), and the viewer's
`fold_runs.tta_record` turns that into the bb-run/1 record. The browser does no kinematics and computes no score.

**Display resolution** (every number on a card is the record's metric, at the fold's rounding; these steps are for
drawing): the channels keep all of the record's 100 Hz samples, so "which samples count" is the ruler's own count; the
drawn arm runs at 25 Hz (bb-run/1's `layer.t`) to 1 mm, plus the frame at each metric's peak; tool points to 1 µm,
joint angles to 1e-4°, torque and speed to 0.1 % of their caps (`CHANNEL_DIGITS` in `tools/build_site.py`).

**Two honesty checks per run** (`runs/index.json` → `checks`, `subset`; the first is shown under the explainer):

- The tracking numbers (`tool_track_rms_mm`, `stop_error_max_mm`) re-run with the ruler's functions on the record's
  saved samples agree with the scored number within 0.001 mm (the record keeps positions to 0.1 µm).
- The violation gates (`saturation_share_pct`, `limit_violations`, `floor_clearance`) are counted by the ruler on every
  4 kHz physics sample; the record keeps the 100 Hz samples, a subset of those. Each gate's rule on the page says how
  many of the drawn samples it flags; a violation among them that the ruler did not count would fail the build.

## Checks

```bash
uv run --all-extras python tools/build_site.py check                                   # shipped numbers == scorecards
uv run --all-extras pytest -q tests/test_site_static.py tests/test_site_playback.py tests/test_site_headliner.py
uv run --all-extras --with playwright==1.64.1 python tools/build_site.py parity          # every saved run, headless
uv run --all-extras --with playwright==1.64.1 python tools/build_site.py shoot           # headless Chromium: outputs/site/
```

`check` proves the shipped runs are the rule's, `state.json` lists exactly their records, and each record's metrics and
gate verdicts equal its scorecard's per-task row. The tests also validate every listed record against the
viewer's `run-record.schema.json`, read where it lives. `parity` and `shoot` drive the page CI builds: they run the
package's build of HEAD into `outputs/site/built/` (so commit first). `parity` opens every listed run by its chip in
headless Chromium (never a visible window) and reads each card back against its record, with no page or console error
and no request to a Python or MuJoCo runtime. `shoot` clicks every metric (each changes the 3D scene), switches Lens ↔
Recorder (the chosen metric stays), opens a lane, plays a failing run, measures that nothing scrolls sideways at 390 px,
and saves light / dark / phone screenshots and the hero video (`outputs/site/hero.mp4`).

The page stays under 15 MiB **as served**, all of `site/` included: text gzipped (GitHub Pages sends it so, and git
stores it so; measured 2026-11-24: `data/state.json`, 678 kB on disk, arrived as 87 kB), media as they are. On disk the
records are ~33 MB of JSON. The stock `<bb-evidence>` loads the first listed record, then every other listed record to
colour its run row's chips by their verdicts (measured 2026-11-25: 244 record requests within 8 s of landing), where
the retired landing loaded one record per pick (~35 kB on the wire).
