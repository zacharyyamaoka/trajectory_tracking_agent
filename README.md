# Trajectory Tracking Agent

An agent that makes robots follow a given trajectory more accurately. The trajectory and the robot are given; the
agent searches over controllers (what is fed forward, what is fed back, where each runs and how far ahead it samples)
and keeps a scored population of every solution it tried.

![Progress: tool tracking error of every solution tried, best so far as a step line](site/progress.svg)

| File | What's in it |
|---|---|
| [`OBJECTIVES.md`](OBJECTIVES.md) | **Objectives & gates**: the black box's inputs and outputs, the deployment, the dataset, the score |
| [`AGENTS.md`](AGENTS.md) | How an agent works here: the loop and its rules |
| [`PROGRESS.md`](PROGRESS.md) | Where the search stands (generated from `ledger.jsonl`) |
| [`ideas.md`](ideas.md) | The experiment queue |
| [`REFERENCES.md`](REFERENCES.md) | Prior art, the packages it builds on, related repos |
| [`solutions/`](solutions/) | The population: one folder per solution, with its lineage and scorecard |
| [`site/`](site/) | The landing page: saved runs played back, scored by the ruler at evaluation time |

```bash
uv run tta evaluate p7s --split dev
```

Built on [robot_msgs](https://github.com/zacharyyamaoka/robot_msgs) (the vocabulary) and
[robot_controllers](https://github.com/zacharyyamaoka/robot_controllers) (the plants, boards and controller parts).
Part of [robot-sdk](https://github.com/zacharyyamaoka/robot_sdk): packages are what agents build; agents are what
build them.
