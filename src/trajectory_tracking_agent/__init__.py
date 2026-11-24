"""Trajectory Tracking Agent: the ruler, evaluate(), the population and the tta CLI (see OBJECTIVES.md).

    import trajectory_tracking_agent as tta
    deployment = tta.deployment("ur5e_alone")         # robot + scene + bus + host rate
    task = tta.tasks("dev")[0]                         # task.trajectory: a robot_msgs JointTrajectory
    scorecard = tta.evaluate("p7s", split="dev")       # writes the scorecard and one ledger row

Lazy (PEP 562): importing the package, or `trajectory_tracking_agent.ruler.metrics`, loads neither MuJoCo nor
robot_controllers, so the numpy-only metrics also import in a browser.
"""

from __future__ import annotations

from typing import Any

__all__ = ["deployment", "evaluate", "tasks"]


def __getattr__(name: str) -> Any:
    if name == "deployment":
        from trajectory_tracking_agent.ruler.deployment import deployment

        return deployment
    if name == "tasks":
        from trajectory_tracking_agent.ruler.dataset import tasks

        return tasks
    if name == "evaluate":
        from trajectory_tracking_agent.evaluate import evaluate

        return evaluate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
