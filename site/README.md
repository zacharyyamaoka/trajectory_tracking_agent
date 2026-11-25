# site/: the landing page

A static page that **plays back saved runs**. Nothing is simulated or scored in the browser: every run was simulated
and scored by the ruler when `tta evaluate` ran it, and every number on the page is the ruler's own, copied from that
run's record. (Zach, 2026-11-24: "You can just playback saved runs"; until then the page ran MuJoCo's WebAssembly
build and Pyodide live. Git history keeps that runtime.)

Under the Ticker headliner, the run on screen is the blackbox_agent viewer's **`<bb-evidence>`** (vendored as
`vendor/bb-evidence.js`, its CONTRACT §14): one saved run, Lens (the 3D replay large, a card per metric) or Recorder
(every metric a lane on one timeline), showing which samples each number counted, where it failed and its worst
moment. The page's Solution and Dev task pickers choose which bb-run/1 record it plays; under it, each joint's
tracking error (the one joint view it does not draw), the black box and the population. (Zach, 2026-11-24: "it should
use the newer 3D explanation things we designed, they are in the storybook"; until then the page had its own three.js
stage, score cards and joint plots. Git history keeps them.)

Published to GitHub Pages from `site/` on every push to `main` (`.github/workflows/pages.yml`).

## Rebuild it

After new solutions are scored (`tta evaluate <id>` writes their run records to `outputs/runs/`):

```bash
uv run --all-extras python tools/build_site.py build
```

It rewrites `site/data/` (the run records, `state.json`, `page.json`, the solution sources) and then runs `check`. It
needs the blackbox_agent viewer beside this repo (`~/blackbox_agent`; `BB_FOLD`, `BB_FOLD_RUNS` override): its
`tools/fold_state.py` writes `state.json` and its `tools/fold_runs.py` writes each record. It refuses
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
playback, the pickers and the population table.

On 2026-11-24 that is 244 (solution, task) runs: 34 solutions × 5 tasks, plus p5s-pass3 (best) and p6s (best of
generation 0) on the other 37 tasks. The pickers list only what ships: the task picker shows the selected solution's
shipped tasks. If the page ever had to shrink, it would ship fewer tasks, never fewer numbers per run.

## What is in `site/data/`

| Path | What |
|---|---|
| `state.json` | bb-state/1, the viewer's fold of this repo at HEAD (the headliner reads it), plus the `playback` slice this build writes: every shipped run's record path (`runs/<solution>/<task>.json`, relative to `state.json`), `schema: "bb-run/1"` and a label |
| `runs/<solution>/<task>.json` | one saved run as a **bb-run/1** record (the viewer's `schemas/run-record.schema.json`): the ruler's metrics with their rules, which samples each counted, where it failed and its peak; the time base and stops; channels (tool error, target and measured tool points and joint angles, torque and speed as a % of each cap, the lowest point's floor clearance, power); the arm's drawn geom poses (target ghost and measured) |
| `runs/index.json` | the pickers: per solution its shipped tasks (record, objective, every gate passed?) and what scored it (repo commit, robot_controllers / robot_msgs commits, `solution.py` sha256, date), and the build's honesty checks per run |
| `page.json` | the black-box contract, the robot_msgs types, the leaderboard (from every scorecard), the best solution's code |
| `solutions/<id>/solution.py` | byte copies of each shipped solution's code, for the code view |

How a record is made: `build` computes what is drawn natively from `tta evaluate`'s run record (the arm's geom poses from
the deployment's own model and `mujoco.mj_kinematics`, checked against `deployment.link_points`; the tool error from the
ruler's `metrics.tool_errors_m`; the stop errors from `metrics.stop_errors_mm`; the floor's lowest moving point from
`deployment.link_points`) into a compact binary export (`outputs/site/playback/`, gitignored), and the viewer's
`fold_runs.tta_record` turns that into the bb-run/1 record. The browser does no kinematics and computes no score; the
page's own JavaScript only subtracts target from measured joint angles for the joint-error plots.

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
uv run --no-project --with playwright==1.64.1 python tools/build_site.py parity         # every picker option, headless
uv run --no-project --with playwright==1.64.1 python tools/build_site.py shoot          # headless Chromium: outputs/site/
```

`check` proves the shipped runs are the rule's, `state.json` lists exactly their records, and each record's metrics and
gate verdicts equal its scorecard's per-task row. The tests also validate every record the pickers offer against the
viewer's `run-record.schema.json`, read where it lives. `parity` opens every (solution, task) the pickers offer in
headless Chromium (never a visible window) and reads each card back against its record, with no page or console error
and no request to a Python or MuJoCo runtime. `shoot` clicks every metric (each changes the 3D scene), switches Lens ↔
Recorder (the chosen metric stays), opens a lane, plays a failing run, measures that nothing scrolls sideways at 390 px,
and saves light / dark / phone screenshots and the hero video (`outputs/site/hero.mp4`).

The page stays under 15 MiB **as served**, all of `site/` included: text gzipped (GitHub Pages sends it so, and git
stores it so; measured 2026-11-24: `data/state.json`, 678 kB on disk, arrived as 87 kB), media as they are. On disk the
records are ~33 MB of JSON; a visitor loads `state.json` and one record per pick (~35 kB on the wire).
