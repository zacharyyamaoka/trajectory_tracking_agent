# site/: the landing page

A static page that **plays back saved runs**. Nothing is simulated or scored in the browser: every run was simulated
and scored by the ruler when `tta evaluate` ran it, and every number on the page is the ruler's own, copied from that
run's record. (Zach, 2026-11-24: "You can just playback saved runs"; until then the page ran MuJoCo's WebAssembly
build and Pyodide live. Git history keeps that runtime.)

Published to GitHub Pages from `site/` on every push to `main` (`.github/workflows/pages.yml`).

## Rebuild it

After new solutions are scored (`tta evaluate <id>` writes their run records to `outputs/runs/`):

```bash
uv run --all-extras python tools/build_site.py build
```

It rewrites `site/data/` (the playback files, `page.json`, the solution sources) and then runs `check`. It refuses
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
| `playback/index.json` | the rule and what it selected, the deployment's constants, the drawn geoms, and per solution: its shipped tasks (file, objective, gates passed) and what scored it (repo commit, robot_controllers / robot_msgs commits, `solution.py` sha256, date) |
| `playback/tasks/<task>.bin.gz` | the target once per task: time, target joints, target tool path, moving samples, stops, the target arm's geom poses per sample |
| `playback/runs/<solution>/<task>.bin.gz` | one saved run: the record's `metrics`, `gates` and `notes` verbatim; measured joints, joint speeds, torques, tool path, tool error, the measured arm's geom poses, the lowest moving point; and what each card's explanation shows (`explain`) |
| `page.json` | the black-box contract, the robot_msgs types, the leaderboard (from every scorecard), the best solution's code |
| `solutions/<id>/solution.py` | byte copies of each shipped solution's code, for the code view |

Everything drawn is computed natively at build time, never in the browser: the arm's geom poses come from the
deployment's own model and `mujoco.mj_kinematics` (checked against `deployment.link_points`), the tool error from the
ruler's `metrics.tool_errors_m`, the stop errors from `metrics.stop_errors_mm`, the floor's lowest moving point from
`deployment.link_points`. The page's JavaScript draws, converts units (rad → °) and shows a torque or joint state as a %
of its cap or limit; it computes no score.

**Two honesty checks per run** (`explain.checks`, `explain.subset`), shown on the page:

- The tracking numbers (`tool_track_rms_mm`, `stop_error_max_mm`) re-run with the ruler's functions on the record's
  saved samples agree with the scored number within 0.001 mm (the record keeps positions to 0.1 µm).
- The violation gates (`saturation_share_pct`, `limit_violations`, `floor_clearance`) are counted by the ruler on every
  4 kHz physics sample; the record keeps the 100 Hz samples, a subset of those. The page draws the 100 Hz samples and
  says so; a violation among them that the ruler did not count would be flagged.

**Format** (`read_playback` in `tools/build_site.py` and `assets/playback.js` are the same decoder; `shoot` checks they
agree): `gzip(b"TTAPLAY1" + uint32 LE header length + header JSON + arrays)`. Each array is integers at a stated step
(`index.json` → `codec.steps`: 0.1 µm for tool points, 1e-7 rad for joints, 10 µm for the drawn arm), each column
contiguous, as its first difference along time, in the narrowest signed integer, its bytes split into planes; a run's
arrays that follow the target (joints, tool, arm) are stored as differences from the task file's. These steps are for
drawing only: every number on a card is the record's own float.

## Checks

```bash
uv run --all-extras python tools/build_site.py check                                   # shipped numbers == scorecards
uv run --all-extras pytest -q tests/test_site_static.py tests/test_site_playback.py
uv run --no-project --with playwright==1.64.1 python tools/build_site.py shoot          # headless Chromium: outputs/site/
```

`shoot` loads the page in headless Chromium (never a visible window), measures the time to the first playable frame,
checks that no request goes to a Python or MuJoCo runtime, that the cards show the record's numbers and each click
changes the 3D and 2D views, that every shipped (solution, task) plays, and that the JavaScript decoder returns the
Python decoder's arrays; it saves light / dark / 390 px screenshots and the hero video (`outputs/site/hero.mp4`).

The page stays under 15 MB committed, all of `site/` included.
