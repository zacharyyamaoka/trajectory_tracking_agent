"""The search can be left running overnight: a run stopped at any point (a crash, the OOM killer, a power cut, a rate
limit ending the session) never leaves a file that stops the next one.

WHY (Zach, 2026-11-24; feedback/2026-11-24-runs-overnight.md): the black box was not reliable enough to leave running
through the night. AGENTS.md promises that state lives in files so any session can stop at any point and the next one
resumes from ledger.jsonl + solutions/; these tests hold the file half of that promise. Re-running a killed
evaluation gives the same score bit for bit (tests/test_ruler_determinism.py), so a lost row is recovered by
evaluating again, never by hand.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from trajectory_tracking_agent import files, ledger

IN_PLACE = re.compile(r"(?<!files)\.write_(text|bytes)\(")
SRC = Path(__file__).resolve().parent.parent / "src" / "trajectory_tracking_agent"


def _row(solution: str, objective: float = 1.0) -> dict:
    row = {key: None for key in ledger.ROW_KEYS}
    row.update(solution=solution, split="dev", ruler="v1", objective=objective, admissible=True, gate_pass_rate=1.0,
               failed_gates={}, diagnostics={}, task_objectives={})
    return row


def _ledger_with_torn_tail(tmp_path: Path) -> Path:
    path = tmp_path / "ledger.jsonl"
    whole = "".join(json.dumps(_row(s)) + "\n" for s in ("a", "b"))
    torn = json.dumps(_row("c"))[:57]  # the process died part-way through writing row c
    path.write_text(whole + torn)
    return path


def test_a_torn_last_ledger_line_does_not_stop_the_search(tmp_path: Path) -> None:
    path = _ledger_with_torn_tail(tmp_path)
    assert [row["solution"] for row in ledger.rows(path)] == ["a", "b"]
    assert set(ledger.latest("dev", path)) == {"a", "b"}


def test_the_next_append_after_a_torn_line_is_a_whole_row(tmp_path: Path) -> None:
    path = _ledger_with_torn_tail(tmp_path)
    ledger.append(_row("d"), path)
    text = path.read_text()
    assert text.endswith("\n")
    assert [json.loads(line)["solution"] for line in text.splitlines()] == ["a", "b", "d"]


def test_a_whole_last_row_missing_only_its_newline_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps(_row("a")) + "\n" + json.dumps(_row("b")))  # e.g. an editor dropped the final newline
    assert [row["solution"] for row in ledger.rows(path)] == ["a", "b"]
    ledger.append(_row("c"), path)
    assert [row["solution"] for row in ledger.rows(path)] == ["a", "b", "c"]


def test_a_bad_line_inside_the_ledger_still_fails_loudly(tmp_path: Path) -> None:
    """Only a torn tail (no newline after it) is a crash's leftover; a bad line with rows after it is damage, and
    dropping it would silently lose a score."""
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps(_row("a")) + "\n" + '{"solution": "b", "obj' + "\n" + json.dumps(_row("c")) + "\n")
    with pytest.raises(ValueError, match="line 2"):
        ledger.rows(path)


def test_a_write_killed_before_it_lands_keeps_the_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "scorecard.json"
    path.write_text('{"old": true}\n')

    def killed(*_args, **_kwargs):
        raise KeyboardInterrupt("killed between the write and the rename")

    monkeypatch.setattr(os, "replace", killed)
    with pytest.raises(KeyboardInterrupt):
        files.write_text(path, '{"new": true}\n')
    assert path.read_text() == '{"old": true}\n'
    assert [p.name for p in tmp_path.iterdir()] == ["scorecard.json"]  # no temporary file left behind


def test_a_write_lands_whole(tmp_path: Path) -> None:
    path = tmp_path / "solutions" / "x" / "scorecard.json"
    path.parent.mkdir(parents=True)
    files.write_text(path, "{}\n")
    files.write_text(path, '{"objective": 0.5}\n')
    assert path.read_text() == '{"objective": 0.5}\n'


def test_every_file_the_loop_writes_goes_through_the_atomic_write() -> None:
    """The sweep: scorecards, run records, PROGRESS.md, status.json, a new solution's files. A file written in place
    and cut off half-way is read by the next step (the leaderboard, the site build) and stops it."""
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted(SRC.rglob("*.py")) if path.name != "files.py"
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if IN_PLACE.search(line)
    ]
    assert offenders == []


def test_a_worker_the_machine_kills_stops_the_evaluation_at_once_and_scores_nothing() -> None:
    """WHY (2026-11-25, measured): with memory under 8 % free, the machine's memory guard and the OOM killer ended three of
    an evaluation's four workers. multiprocessing.Pool replaced them silently, so the run waited out its whole backstop
    deadline (10 x every task's duration + 120 s) and then scored each lost task as a failed `completed`: the machine's
    kill went into the ledger as the controller's failure. A lost worker is not a score; the run stops, writes
    nothing, and is evaluated again (the score repeats bit for bit)."""
    from types import SimpleNamespace

    import overnight_jobs
    from trajectory_tracking_agent import evaluate

    task_list = [SimpleNamespace(id=f"t{i}", duration_s=1.0) for i in range(4)]
    start = time.monotonic()
    with pytest.raises(evaluate.WorkerLost, match="t2"):
        evaluate._run_tasks("any", "dev", task_list, 2, None, job=overnight_jobs.killed_on_t2)
    assert time.monotonic() - start < 60.0


def test_tta_evaluate_says_retry_when_a_worker_is_lost(monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    """A loop driving `tta evaluate` overnight tells "evaluate again" (EX_TEMPFAIL, 75) from a scored run (0) and
    from a broken solution or command (anything else), so it retries the machine's failures and nothing else."""
    from trajectory_tracking_agent import cli, evaluate

    def lost(*_args, **_kwargs):
        raise evaluate.WorkerLost("a worker process died while p4s ran on dev (first unfinished task t2)")

    monkeypatch.setattr(evaluate, "evaluate", lost)
    assert cli.main(["evaluate", "p4s", "--no-progress"]) == 75
    assert "evaluate it again" in capsys.readouterr().err
