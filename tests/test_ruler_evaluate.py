"""Lane E's own tests of the evaluator: one task end to end, fail-closed paths, the scorecard and the run record.

The fail-closed cases run throwaway solutions from a temporary solutions folder (`population.SOLUTIONS_DIR` patched), so
nothing here writes to `solutions/` or `ledger.jsonl`.
"""

from __future__ import annotations

import json
import math
import textwrap

import numpy as np
import pytest
from robot_msgs import load_npz
from robot_msgs.sensor import JointState
from robot_msgs.trajectory import JointTrajectory

from trajectory_tracking_agent import evaluate as evaluate_module
from trajectory_tracking_agent import ledger, population
from trajectory_tracking_agent.ruler import gates
from trajectory_tracking_agent.ruler.dataset import TAPES_DIR, sha256, task

SHORT_TASK = "workspace-dev-014"  # an a_to_b_joint move, 1.55 s


def _write_solution(root, solution_id: str, body: str) -> None:
    folder = root / solution_id
    folder.mkdir(parents=True)
    (folder / "solution.py").write_text(textwrap.dedent(body))
    (folder / "meta.json").write_text(json.dumps({
        "id": solution_id, "parent": None, "change": "test", "proposed_by": {"agent": "pytest", "model": None, "session": None},
        "created": "2026-11-24T00:00:00-07:00", "tags": [],
    }))  # fmt: skip


@pytest.fixture
def scratch_solutions(tmp_path, monkeypatch):
    monkeypatch.setattr(population, "SOLUTIONS_DIR", tmp_path)
    return tmp_path


def _assert_failed_closed(row, why: str) -> None:
    assert row["kpis"]["completed"] is False
    assert row["verdicts"]["completed"] is False
    assert any(why in note for note in row["notes"]), row["notes"]
    assert not gates.admissible([row["verdicts"]])


# ── a real solution, one task ───────────────────────────────────────────────────────────────────────────────


def test_run_task_scores_a_real_solution():
    row = evaluate_module.run_task("p4s", SHORT_TASK)
    assert row["task"] == SHORT_TASK and row["kind"] == "a_to_b_joint"
    assert set(row["verdicts"]) == set(gates.GATES)
    assert row["kpis"]["completed"] is True, row["notes"]
    assert 0.0 < row["objective"] < 10.0  # mm: a calibrated board PD tracks a UR5e move within millimetres
    assert row["kpis"]["limit_violations"] == 0 and row["kpis"]["floor_clearance_violations"] == 0
    diagnostics = row["diagnostics"]
    assert diagnostics["ticks"] == pytest.approx(row["duration_s"] * 50.0, abs=2)  # 50 Hz host
    assert diagnostics["host_compute_ms_p95"] > 0.0 and diagnostics["energy_j"] > 0.0
    assert diagnostics["stops"] >= 1  # every tape ends in a hold
    json.dumps({k: v for k, v in row.items() if k != "_arrays"}, allow_nan=False)  # JSON-safe, NaN as None


def test_run_task_is_repeatable():
    # WHY exact: the deployment sends each command at its wake time (Deployment.timing, include_compute=False), so the
    # tick's CPU time, which varies with host load, never moves a latch; p6s (mj_inverse every tick) is the hard case
    first = evaluate_module.run_task("p6s", SHORT_TASK)
    second = evaluate_module.run_task("p6s", SHORT_TASK)
    assert second["objective"] == first["objective"]
    assert second["kpis"] == first["kpis"]


def test_measured_tool_is_fk_of_the_plants_joints_on_the_targets_grid():
    row = evaluate_module.run_task("p4s", SHORT_TASK)
    arrays = row["_arrays"]
    from trajectory_tracking_agent.ruler.deployment import deployment

    np.testing.assert_allclose(arrays["tool_xyz"], deployment().tool_position(arrays["q"]), atol=1e-12)
    np.testing.assert_allclose(arrays["tool_target_xyz"], deployment().tool_position(arrays["q_target"]), atol=1e-12)
    assert np.all(np.diff(arrays["t"]) > 0) and arrays["t"][0] == 0.0


def test_controller_receives_joint_states_at_the_deployment_rate(monkeypatch):
    build = population.load_build("p5s-pass3")
    tick_intervals = []
    host_periods = []

    def watch_build(trajectory, deployment):
        assert isinstance(trajectory, JointTrajectory)
        host_periods.append(deployment.host_period_s)
        controller = build(trajectory, deployment)
        tick = controller.tick

        def watch_tick(state, dt):
            assert isinstance(state, JointState)
            assert tuple(state.name) == tuple(trajectory.joint_names)
            tick_intervals.append(dt)
            return tick(state, dt)

        controller.tick = watch_tick
        return controller

    monkeypatch.setattr(population, "load_build", lambda _: watch_build)
    row = evaluate_module.run_task("p5s-pass3", SHORT_TASK)
    assert row["verdicts"]["completed"], row["notes"]
    assert host_periods == [0.02]
    expected_ticks = math.ceil(row["duration_s"] / host_periods[0]) + 1
    assert len(tick_intervals) == expected_ticks
    assert tick_intervals[0] == 0.0
    np.testing.assert_allclose(tick_intervals[1:], host_periods[0], atol=1e-12, rtol=0)


@pytest.mark.parametrize(("return_value", "reason"), [
    ("self.hold", "not (ServoCommand, defines)"),
    ("(self.hold, {})", "not a robot_msgs ServoCommand"),
    ("(ServoCommand(name=self.names[1:], position=self.hold[1:]), {})", "the command names no"),
])
def test_controller_must_send_a_servo_command_for_all_joints(scratch_solutions, return_value, reason):
    _write_solution(scratch_solutions, "bad-command", f"""
        from robot_msgs.control import ServoCommand

        class BadCommand:
            def __init__(self, trajectory):
                self.names = trajectory.joint_names
                self.hold = trajectory.positions[0]

            def tick(self, state, dt):
                return {return_value}

        def build(trajectory, deployment):
            return BadCommand(trajectory)
    """)
    _assert_failed_closed(evaluate_module.run_task("bad-command", SHORT_TASK), reason)


def test_a_retimed_controller_is_scored_against_the_frozen_tape(monkeypatch):
    tape = TAPES_DIR / f"{SHORT_TASK}.npz"
    original_digest = sha256(tape)
    reference = load_npz(tape)
    baseline = evaluate_module.run_task("p5s-pass3", SHORT_TASK)
    build = population.load_build("p5s-pass3")

    def build_retimed(trajectory, deployment):
        return build(trajectory.time_scaled(2.0), deployment)

    monkeypatch.setattr(population, "load_build", lambda _: build_retimed)
    retimed = evaluate_module.run_task("p5s-pass3", SHORT_TASK)

    assert baseline["verdicts"]["completed"]
    assert retimed["objective"] > baseline["objective"]
    _assert_failed_closed(retimed, "did not settle")
    np.testing.assert_array_equal(retimed["_arrays"]["t"], reference.t)
    np.testing.assert_array_equal(retimed["_arrays"]["q_target"], reference.positions)
    assert sha256(tape) == original_digest


@pytest.mark.parametrize("field", ["t", "positions", "velocities", "accelerations", "piece"])
@pytest.mark.parametrize("reopen", [False, True])
def test_controller_cannot_edit_the_reference_arrays(monkeypatch, field, reopen):
    frozen = task(SHORT_TASK).trajectory[field]
    original = frozen.copy()
    build = population.load_build("p5s-pass3")

    def build_with_edit(trajectory, deployment):
        samples = trajectory[field]
        if reopen:
            samples.setflags(write=True)
        samples.flat[-1] += 1
        return build(trajectory, deployment)

    monkeypatch.setattr(population, "load_build", lambda _: build_with_edit)
    try:
        row = evaluate_module.run_task("p5s-pass3", SHORT_TASK)
        _assert_failed_closed(row, "build raised ValueError")
        np.testing.assert_array_equal(frozen, original)
    finally:
        # Restore the cached tape if this test catches an edit, so it cannot poison another test.
        if frozen.flags.writeable:
            frozen[...] = original
            frozen.setflags(write=False)


# ── fail closed ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_build_that_raises_fails_every_gate(scratch_solutions):
    _write_solution(scratch_solutions, "broken", """
        def build(trajectory, deployment):
            raise RuntimeError("no controller today")
    """)
    row = evaluate_module.run_task("broken", SHORT_TASK)
    _assert_failed_closed(row, "build raised RuntimeError")
    assert row["objective"] is None
    assert not any(row["verdicts"].values())  # nothing was measured, so nothing passes


def test_a_nan_command_fails_completed(scratch_solutions):
    _write_solution(scratch_solutions, "nan-ff", """
        import numpy as np
        from robot_msgs.control import ServoCommand

        class NanController:
            status = "running"
            def __init__(self, trajectory):
                self.names = tuple(trajectory.joint_names)
                self.hold = np.asarray(trajectory.positions[0], dtype=float)
            def tick(self, state, dt):
                ff = np.full(len(self.names), np.nan)
                return ServoCommand(name=self.names, position=self.hold, feedforward_effort=ff), {}

        def build(trajectory, deployment):
            return NanController(trajectory)
    """)
    row = evaluate_module.run_task("nan-ff", SHORT_TASK)
    _assert_failed_closed(row, "non-finite command")


def test_a_solution_importing_the_ruler_is_refused(scratch_solutions):
    _write_solution(scratch_solutions, "peek", """
        from trajectory_tracking_agent.ruler import metrics

        def build(trajectory, deployment):
            raise AssertionError("never reached")
    """)
    row = evaluate_module.run_task("peek", SHORT_TASK)
    _assert_failed_closed(row, "never imports the ruler")
    with pytest.raises(PermissionError):
        evaluate_module.evaluate("peek", "dev", task_ids=[SHORT_TASK], records=False)


def test_check_source_names_dataset_reads_but_not_docstrings(tmp_path):
    source = tmp_path / "solution.py"
    source.write_text('"""Never tuned on holdout."""\nPATH = "datasets/ur5e_alone/workspace/v2/tapes"\n')
    problems = population.check_source(source)
    assert len(problems) == 1 and "datasets" in problems[0]


def test_the_time_box_fails_completed(scratch_solutions, monkeypatch):
    _write_solution(scratch_solutions, "slow", """
        import time
        import numpy as np
        from robot_msgs.control import ServoCommand

        class Slow:
            status = "running"
            def __init__(self, trajectory):
                self.names = tuple(trajectory.joint_names)
                self.hold = np.asarray(trajectory.positions[0], dtype=float)
            def tick(self, state, dt):
                time.sleep(0.002)
                return ServoCommand(name=self.names, position=self.hold), {}

        def build(trajectory, deployment):
            return Slow(trajectory)
    """)
    monkeypatch.setattr(evaluate_module, "TIME_BOX_FACTOR", 0.02)  # 31 ms for the 1.55 s task
    row = evaluate_module.run_task("slow", SHORT_TASK)
    _assert_failed_closed(row, "time box")


def test_a_controller_that_never_moves_fails_the_stop_gate(scratch_solutions):
    _write_solution(scratch_solutions, "statue", """
        import numpy as np
        from robot_msgs.control import ServoCommand

        class Statue:
            status = "running"
            def __init__(self, trajectory):
                self.names = tuple(trajectory.joint_names)
                self.hold = np.asarray(trajectory.positions[0], dtype=float)
            def tick(self, state, dt):
                return ServoCommand(name=self.names, position=self.hold), {}

        def build(trajectory, deployment):
            return Statue(trajectory)
    """)
    row = evaluate_module.run_task("statue", SHORT_TASK)
    assert row["objective"] > 50.0  # the target moves away by tens of centimetres
    assert row["verdicts"]["stop_error_max_mm"] is False
    _assert_failed_closed(row, "did not settle")


# ── a scorecard and its run records ─────────────────────────────────────────────────────────────────────────


def test_evaluate_on_a_subset_returns_a_scorecard_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate_module, "RUNS_DIR", tmp_path / "runs")
    before = ledger.LEDGER_PATH.read_text() if ledger.LEDGER_PATH.exists() else ""
    scorecard = evaluate_module.evaluate("p4s", "dev", task_ids=[SHORT_TASK, "workspace-dev-032"], workers=1)
    assert (ledger.LEDGER_PATH.read_text() if ledger.LEDGER_PATH.exists() else "") == before  # a subset is not a score
    assert scorecard["ruler"] == "v1" and scorecard["split"] == "dev" and len(scorecard["tasks"]) == 2
    assert scorecard["objective"] == pytest.approx(np.median([row["objective"] for row in scorecard["tasks"]]))
    assert set(scorecard["failed_gates"]) == set(gates.GATES)
    assert set(scorecard["code"]) >= {"solution_sha256", "repo_commit", "robot_controllers", "robot_msgs"}
    assert scorecard["code"]["robot_controllers"]["version"] and scorecard["code"]["robot_msgs"]["version"]
    record = json.loads((tmp_path / "runs" / "p4s" / "dev" / f"{SHORT_TASK}.json").read_text())
    for key in ("t", "q_target", "qd_target", "q", "qd", "tau", "tau_cap", "tool_target_xyz", "tool_xyz", "metrics", "gates"):
        assert key in record
    assert len(record["t"]) == len(record["q"]) == len(record["tool_xyz"])
    assert record["metrics"]["tool_track_rms_mm"] == pytest.approx(scorecard["tasks"][0]["objective"])
    json.dumps(scorecard, allow_nan=False)


def test_evaluate_refuses_more_than_four_workers():
    with pytest.raises(ValueError):
        evaluate_module.evaluate("p4s", "dev", workers=5, write=False)


def test_holdout_is_never_scored_by_a_dev_evaluation():
    from trajectory_tracking_agent.ruler.dataset import tasks

    dev_ids = {task.id for task in tasks("dev")}
    assert all(task_id.startswith("workspace-dev-") for task_id in dev_ids)
    assert not dev_ids & {task.id for task in tasks("holdout")}


def test_rows_from_a_failed_task_are_json_safe():
    from trajectory_tracking_agent.ruler.dataset import task

    row = evaluate_module._failed_row(task(SHORT_TASK), "why", math.nan)
    json.dumps(row, allow_nan=False)
    assert row["kpis"]["floor_clearance_violations"] is None and not any(row["verdicts"].values())
