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
| `status.json` | schema `ai-team-status/1` (vault `PROJECT - AI Team`): kpi = best admissible objective, written from the ledger by `tta progress` | `tta` only (lane E builds it) |
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

## 6. The ruler's frozen signatures (lane T tests them; lane E implements them; neither changes them)

`src/trajectory_tracking_agent/ruler/metrics.py`, numpy only, SI in, the unit in the name out:

```python
moving_mask(t, target_tool_xyz, target_qd) -> np.ndarray[bool]          # OBJECTIVES §4 "moving"
stop_windows(t, moving) -> list[tuple[float, float]]                    # target at rest >= 0.2 s -> (t0, t1)
tool_track_rms_mm(target_tool_xyz, measured_tool_xyz, moving) -> float  # (N,3) m, (N,3) m, (N,) -> mm
tool_track_max_mm(target_tool_xyz, measured_tool_xyz, moving) -> float
stop_error_max_mm(t, target_tool_xyz, measured_tool_xyz, stops) -> float  # mean over each stop's last 0.1 s
saturation_share_pct(torque, caps) -> float                             # (N,n) N·m, (n,) N·m; |tau| >= 0.98 cap
limit_violations(q, qd, q_lo, q_hi, qd_max) -> int                      # samples, 1.05 x velocity limit
floor_clearance_violations(points_z, floor_z=0.0) -> int                # (N,k) m: tool + link origins
```

`src/trajectory_tracking_agent/ruler/gates.py`:

```python
GATES = ("completed", "stop_error_max_mm", "saturation_share_pct", "limit_violations", "floor_clearance")
gate_verdicts(task_kpis: Mapping[str, float | bool | None]) -> dict[str, bool]   # fail closed: None / NaN -> False
admissible(verdicts_per_task: Sequence[Mapping[str, bool]]) -> bool             # every task, every gate
objective(task_objectives: Sequence[float]) -> float                            # median; any NaN -> NaN
```

A task with no moving samples returns `nan` from the tracking metrics (it then fails nothing by itself; `completed`
decides). A task with no stops has `stop_error_max_mm = 0.0` and passes that gate.
