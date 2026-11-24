"""`tta`: the Trajectory Tracking Agent's command line (CONTRACT §4).

    tta verify                                   # every dataset + tape sha256, the deployment builds
    tta evaluate p7s [--split dev|holdout] [--workers N]   # scorecard + one ledger row, then PROGRESS.md + the chart
    tta leaderboard                              # OBJECTIVES §4's ranking, holdout - dev beside the admissible ones
    tta progress                                 # PROGRESS.md, status.json, site/progress.svg (+ outputs/progress.png)
    tta new p7s+coulomb --parent p7s --change "host Coulomb feed-forward"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

from trajectory_tracking_agent.ruler.dataset import REPO_ROOT

CHART_TOOL = REPO_ROOT / "tools" / "progress_chart.py"


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{value:.{digits}f}"


def cmd_verify(_: argparse.Namespace) -> int:
    from trajectory_tracking_agent.ruler import dataset
    from trajectory_tracking_agent.ruler.deployment import deployment

    problems = dataset.verify()
    record = json.loads(dataset.TAPES_MANIFEST.read_text()) if dataset.TAPES_MANIFEST.exists() else {"files": {}}
    try:
        dep = deployment("ur5e_alone")
    except Exception as error:  # noqa: BLE001
        problems.append(f"deployment: {error}")
        dep = None
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {dataset.DATASET_DIR.relative_to(REPO_ROOT)}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    tapes = sum(1 for name in record["files"] if name.startswith("tapes/"))
    counts = {split: len(dataset.tasks(split)) for split in dataset.SPLITS}
    print(f"OK: {dataset.DATASET_DIR.relative_to(REPO_ROOT)}: {len(record['files'])} files, every sha256 matches "
          f"tapes_manifest.json ({len(record['files']) - tapes} dataset files + {tapes} tapes); each tape's sha256 is "
          "the one arm_motion_bench's manifest lists; tasks.jsonl matches its tasks_sha256")
    print(f"    tasks: dev {counts['dev']}, holdout {counts['holdout']}; joints {', '.join(dep.joint_names)}")
    print(f"    deployment {dep.name}: {dep.host_rate_hz:g} Hz host, bus {dep.bus.source}, caps "
          f"{'/'.join(f'{c:g}' for c in dep.torque_cap_nm)} N·m, floor z = {dep.floor_z_m:g} m")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from trajectory_tracking_agent.evaluate import evaluate

    scorecard = evaluate(args.id, split=args.split, workers=args.workers, records=not args.no_records)
    failed = {g: n for g, n in scorecard["failed_gates"].items() if n}
    print(f"{args.id} on {args.split}: tool_track_rms_mm {_fmt(scorecard['objective'])} mm (median of "
          f"{len(scorecard['tasks'])} tasks), admissible {'yes' if scorecard['admissible'] else 'no'}, gate pass rate "
          f"{100 * scorecard['gate_pass_rate']:.1f} %, {scorecard['wall_time_s']:.1f} s")
    if failed:
        print("  failed gates (tasks): " + ", ".join(f"{g} {n}" for g, n in failed.items()))
    if not args.no_progress:
        cmd_progress(args, quiet=True)
    return 0


def cmd_leaderboard(_: argparse.Namespace) -> int:
    from trajectory_tracking_agent import ledger

    board = ledger.leaderboard_rows()
    if not board:
        print("no solutions scored yet: tta evaluate <id>")
        return 0
    print(f"{'#':>2}  {'solution':<14} {'dev mm':>8} {'adm':>4} {'pass %':>7} {'holdout mm':>11} {'ho - dev':>9}  failed gates (dev tasks)")
    for row in board:
        failed = ", ".join(f"{g} {n}" for g, n in row["failed_gates"].items()) or "—"
        holdout = _fmt(row["objective_holdout"]) if row["admissible"] else "—"
        delta = _fmt(row["holdout_minus_dev"]) if row["admissible"] else "—"
        print(f"{row['rank']:>2}  {row['solution']:<14} {_fmt(row['objective_dev']):>8} "
              f"{'yes' if row['admissible'] else 'no':>4} {100 * row['gate_pass_rate']:>6.1f} {holdout:>11} {delta:>9}  {failed}")
    return 0


def _chart_module() -> Any:
    spec = importlib.util.spec_from_file_location("tta_progress_chart", CHART_TOOL)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {CHART_TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_progress(_: argparse.Namespace, quiet: bool = False) -> int:
    from trajectory_tracking_agent import ledger, population

    order = population.ids_in_creation_order()
    ledger.PROGRESS_PATH.write_text(ledger.progress_markdown(order))
    paths = [ledger.PROGRESS_PATH, ledger.write_status(), *_chart_module().write_chart()]
    if not quiet:
        print("wrote " + ", ".join(str(p.relative_to(REPO_ROOT)) for p in paths))
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    from trajectory_tracking_agent import population

    proposed_by = {
        "agent": args.agent or os.environ.get("TTA_AGENT"),
        "model": args.model or os.environ.get("TTA_MODEL"),
        "session": args.session or os.environ.get("TTA_SESSION"),
    }
    folder = population.new(args.id, parent=args.parent, change=args.change, proposed_by=proposed_by, tags=args.tag)
    print(f"created {folder.relative_to(REPO_ROOT)} (parent {args.parent}); next: tta evaluate {args.id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tta", description="The Trajectory Tracking Agent (ruler v1, OBJECTIVES.md)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify", help="re-check every sha256 of the frozen dataset and its tapes").set_defaults(run=cmd_verify)
    evaluate = commands.add_parser("evaluate", help="score a solution: scorecard + one ledger row")
    evaluate.add_argument("id")
    evaluate.add_argument("--split", choices=("dev", "holdout"), default="dev")
    evaluate.add_argument("--workers", type=int, default=4, help="worker processes, 1..4 (CONTRACT §5)")
    evaluate.add_argument("--no-records", action="store_true", help="skip outputs/runs/<id>/<split>/*.json")
    evaluate.add_argument("--no-progress", action="store_true", help="do not refresh PROGRESS.md and the chart")
    evaluate.set_defaults(run=cmd_evaluate)
    commands.add_parser("leaderboard", help="the ranking (OBJECTIVES §4)").set_defaults(run=cmd_leaderboard)
    commands.add_parser("progress", help="PROGRESS.md + site/progress.svg from the ledger").set_defaults(run=cmd_progress)
    new = commands.add_parser("new", help="a new solution folder, copied from its parent")
    new.add_argument("id")
    new.add_argument("--parent", required=True, help="the solution it starts from")
    new.add_argument("--change", required=True, help="one line: what differs from the parent")
    new.add_argument("--agent")
    new.add_argument("--model")
    new.add_argument("--session")
    new.add_argument("--tag", action="append", default=[])
    new.set_defaults(run=cmd_new)
    args = parser.parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":
    sys.exit(main())
