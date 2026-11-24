# Build contract (v1, frozen 2026-11-24)

The dispatcher owns this file, `OBJECTIVES.md`, `README.md`, `AGENTS.md`, `REFERENCES.md`, `pyproject.toml` and
`uv.lock`. Lanes never install packages: they name a missing dependency in their report and the dispatcher adds it.
Lanes share one git index: commit **by pathspec** (`git commit -- <your paths>`), never `git add -A`, and read
`git diff --cached --name-only` first.

## 1. Repo layout and write sets

| Path | What | Owner |
|---|---|---|
| `OBJECTIVES.md`, this file, `README.md`, `AGENTS.md`, `REFERENCES.md`, `ideas.md`, `pyproject.toml`, `uv.lock` | the contract and the agent's brief | dispatcher |
| `src/trajectory_tracking_agent/ruler/` (`deployment.py`, `dataset.py`, `metrics.py`, `gates.py`) | the frozen ruler: §2–4 of OBJECTIVES | lane E |
| `src/trajectory_tracking_agent/{evaluate.py,ledger.py,population.py,cli.py,__init__.py}` | `evaluate()`, the ledger, the population, the `tta` CLI | lane E |
| `datasets/ur5e_alone/workspace/v2/` | the frozen dataset + speed-1.0 tapes | lane E |
| `solutions/` | the population (generation 0 = robot_controllers P1–P10 × interpolation) | lane E (gen 0), then the agent |
| `ledger.jsonl`, `PROGRESS.md` | the local truth (append-only) and its generated log | `tta` only |
| `tools/progress_chart.py`, `site/progress.svg` | the built-in tracker | lane E |
| `tests/` | `tests/test_ruler_*.py` (lane E) · `tests/test_site_*.py` (lane W) | per lane |
| `site/` except `site/progress.svg` and `site/proposals/` | the landing page: in-browser MuJoCo running the real Python code | lane W |
| `site/proposals/` | five ways to show what the metrics mean | lane P |
| `docs/peps/` | decision records | dispatcher |
| `outputs/` | traces, renders, caches (gitignored) | anyone |

## 2. A solution (`solutions/<id>/`)

```
solutions/<id>/
  solution.py      def build(trajectory: JointTrajectory, deployment: Deployment) -> JointController
  meta.json        {"id", "parent": id | null, "change": "one line: what differs from the parent",
                    "proposed_by": {"agent", "model", "session"}, "created": ISO-8601, "tags": [...]}
  scorecard.json   written by `tta evaluate` only: {"ruler": "v1", "split", "objective", "admissible",
                    "gate_pass_rate", "gates": {...}, "diagnostics": {...}, "tasks": [...per-task rows],
                    "code": {"solution_sha256", "repo_commit", "robot_controllers", "robot_msgs"}}
```

- `id` is short and readable (`p7s-calibrated`, `p7s+coulomb`); never reused. A losing solution is kept.
- A solution may import any public package (robot_msgs, robot_controllers, numpy). It may not import this repo's
  `ruler/` (no peeking at the scorer) or read `datasets/*/holdout`.
- A building block that wins on several deployments graduates into robot_controllers (`models.py`) by a PR there;
  the solution then imports it.

## 3. The ledger (`ledger.jsonl`, one JSON object per line, append-only)

`{"t": ISO-8601, "solution": id, "parent": id|null, "split": "dev"|"holdout", "ruler": "v1", "objective": float|null,
"admissible": bool, "gate_pass_rate": float, "failed_gates": {gate: count}, "diagnostics": {...},
"wall_time_s": float, "repo_commit": sha, "proposed_by": {...}}`

The ledger is the local truth; W&B (project "Trajectory Tracking") is a replayable copy of summary scalars only.
`PROGRESS.md` and `site/progress.svg` are regenerated from it by `tta progress`.

## 4. The CLI (`tta`)

`tta verify` (dataset sha256s) · `tta evaluate <id> [--split dev|holdout] [--workers N]` (writes scorecard + one
ledger row; time-boxed: a task over 10× its trajectory duration in wall time fails `completed`) · `tta leaderboard` ·
`tta progress` (PROGRESS.md + site/progress.svg) · `tta new <id> --parent <id> --change "…"` (copies the parent).

## 5. Machine

Sim only: nothing here opens a serial port, CAN, a camera or moteus. Evaluations run with at most 4 worker processes.
