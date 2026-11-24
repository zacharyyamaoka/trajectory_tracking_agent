# References

What this agent builds on and borrows from. Each entry says what we take from it.

## Packages it builds on

- [robot_msgs](https://github.com/zacharyyamaoka/robot_msgs): the vocabulary at the boundary (`JointTrajectory`, `JointState`, `ServoCommand`, `JointController`).
- [robot_controllers](https://github.com/zacharyyamaoka/robot_controllers): the UR5e plant, the moteus board model, bus timing, the feed-forward / feedback / layout parts, and generation 0 of the population.
- [robot_trajectories](https://github.com/zacharyyamaoka/robot_trajectories): how the dataset's motions were made (timed by a private jerk-limited, time-optimal planner; the tapes ship frozen).
- [MuJoCo](https://github.com/google-deepmind/mujoco) and [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie): the physics and the UR5e model.

## The repo format: black-box optimization agents

- [evo](https://github.com/evo-hq/evo): gates as plain exit codes inherited by child experiments, frontier strategies (`pareto_per_task`), failure classes on discards, ideator briefs for when the queue runs dry.
- [karpathy/autoresearch](https://github.com/karpathy/autoresearch/blob/master/program.md): `program.md` as the brief, a frozen scorer, a results table per run.
- [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch): `ideas.md`, a living digest, MAD confidence for noisy scores.
- [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve): `evaluate()` returning a metrics dict plus an error side channel; a viewer fed by checkpoints.
- [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve): public / private metrics, a correctness gate, agent skills.
- [GEPA](https://github.com/gepa-ai/gepa): a Pareto front per task, and diagnostic text returned with each score.
- [AlphaEvolve](https://arxiv.org/abs/2506.13131): a program database and staged evaluation.
- [Anthropic, effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents): a fixed resume order and a progress file.
- [AGENTS.md](https://agents.md): one brief that every coding agent reads.
- [MLE-bench](https://github.com/openai/mle-bench): description, grader and checksums as the scorer's shape.
- [METR task standard](https://github.com/METR/task-standard): what the agent may see and what it may not.
- [AI Scientist](https://github.com/SakanaAI/AI-Scientist): plots read only the run folders, never the method (our viewer rule).
- [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent): a versioned record of what the agent did on each run.
- [Copier](https://copier.readthedocs.io/en/stable/updating/): how a template's updates reach repos made from it.
- [Nygard, Documenting Architecture Decisions](https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions): decision records (`docs/peps/`).

## Population views (how the search is shown)

- [ShinkaEvolve plots](https://github.com/SakanaAI/ShinkaEvolve/tree/main/shinka/plots): the best static set (best-so-far, lineage tree, Pareto).
- [evo](https://github.com/evo-hq/evo): a spine-first tree and a score chart with kept / discarded / failed dots.
- [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve/blob/main/docs/configuration.md): failed programs stay visible in their own column.
- [GEPA visualization](https://github.com/gepa-ai/gepa/blob/main/src/gepa/visualization.py): a tree marking the best and the Pareto-front members.
- [autoresearch analysis.ipynb](https://github.com/karpathy/autoresearch/blob/master/analysis.ipynb): a progress plot plus "top hits" ranked by improvement.
- [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954): a lineage tree coloured by score, and the winning lineage's dips.
- [FunSearch](https://pmc.ncbi.nlm.nih.gov/articles/PMC10794145/): programs grouped by their per-task score signature, i.e. diversity measured on outputs, not code.
- [pyribs](https://github.com/icaros-usc/pyribs) / [QDax plotting](https://github.com/adaptive-intelligent-robotics/QDax/blob/main/qdax/utils/plotting.py): MAP-Elites archive heatmaps and coverage curves.
- [Optuna visualization](https://github.com/optuna/optuna/tree/master/optuna/visualization): the best line drawn over feasible trials only.
- [Recht et al. 2019](https://arxiv.org/abs/1902.10811): the old-vs-new test set scatter, the model for the dev-vs-holdout view.
- [trackio](https://github.com/gradio-app/trackio): a local, W&B-compatible tracker; a light mirror for the numbers.
- [ALife phylogeny standard](https://alife-data-standards.github.io/alife-data-standards/phylogeny.html): the minimal lineage table.

## Standards behind the metrics

- ISO 9283, manipulating industrial robots: performance criteria (pose and path accuracy, repeatability, stabilisation).
