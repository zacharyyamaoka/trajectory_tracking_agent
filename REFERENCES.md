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

## Standards behind the metrics

- ISO 9283, manipulating industrial robots: performance criteria (pose and path accuracy, repeatability, stabilisation).
