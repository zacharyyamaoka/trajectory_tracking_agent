# How an agent works here

You are the Trajectory Tracking Agent (or one of its lanes). Your job: make robots track a given trajectory more
accurately, inside the gates, by proposing better controllers. Read `OBJECTIVES.md` first; it is the whole outside view.

## The loop

1. Read `PROGRESS.md` (where the search stands), `ideas.md` (the queue) and `tta leaderboard`.
2. Pick one idea, or propose one. Write it as a new solution: `tta new <id> --parent <best or a niche winner> --change "…"`.
3. `tta evaluate <id>` (dev only). It writes `solutions/<id>/scorecard.json`, appends `ledger.jsonl` and refreshes
   `PROGRESS.md` and `site/progress.svg`.
4. Commit the solution folder, the ledger row and the progress files together (by pathspec), win or lose:
   `git add -- solutions/<id>` (a new folder is untracked), then
   `git commit -- solutions/<id> ledger.jsonl PROGRESS.md status.json site/progress.svg site/views ideas.md`.
5. Update `ideas.md`: cross off what you tried, add what the result suggests.

## Rules

- **Never edit the ruler**: `OBJECTIVES.md`, `src/trajectory_tracking_agent/ruler/`, `datasets/`. A ruler change is a
  new version, proposed in `docs/peps/` for Zach.
- **Learn about the robot only through the boundary** (OBJECTIVES §1, "What a solution may know"): never the plant's
  truth, never `deployment.plant()`, never a model with less than the given 10 % error. Identify what you need from your own dev runs.
- **Never select on holdout.** Holdout is scored only to report a finished solution.
- **Keep the losers.** A discarded solution's scorecard tells the next agent what not to try.
- **One change per solution**, named in `meta.json`'s `change`, so the lineage reads as a story.
- **Sim only.** The real arm is a separate stage; nothing here opens a bus.
- **State lives in files**, so any session can stop at any point (a rate limit, a crash) and the next one resumes
  from `ledger.jsonl` + `solutions/` + `ideas.md` without a takeover brief.

## Lessons so far (generation 1, 2026-11-24)

- **Identify at the gains you will run with.** A model fitted from joint errors learns the loop as well as the plant:
  p5s-pass3's model run at the boards' normal gains scored 0.156 mm, worse than the line refitted at those gains (0.070).
- **Scores repeat bit for bit**, so any gain is real; check it with two runs if you doubt it. Until robot_controllers
  f25f485 the calibrated lookahead drifted with machine load by ~2 % and nothing flagged it.
- **The twin has no compliance**, so stiffer board gains are cheap here and may not transfer to a real arm. Tag such
  solutions `transfer-risk:stiffness` in meta.json and keep a line at the boards' normal gains beside them.

