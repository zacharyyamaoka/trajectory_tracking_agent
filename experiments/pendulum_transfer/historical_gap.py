"""Compare the frozen high-gain historical feedforward on the CAN 11 synthetic gap."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

from arm_motion_bench.datasets import load_dataset

from locked_controller import (DATASET_SHA, MODEL_SHA, RACK_RUNNER_SHA, RUNG, STATION, VERSION, adopted_parameters,
                               digest, frozen_tapes, rack, rack_template, run_commands, sealed_stress, summarize)

EVIDENCE_DIR = Path(__file__).resolve().parent
REFERENCE_ROWS_SHA = "fc91425e2ba46ad30cffd9ec1f9a843051de150a0f3f1ae5dcc62116fb38297e"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("reference_rows", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if digest(args.reference_rows) != REFERENCE_ROWS_SHA:
        raise ValueError("expected the rows from the previous matched G2 transfer")
    if digest(rack.version_path(STATION, VERSION)) != MODEL_SHA or digest(Path(rack.__file__)) != RACK_RUNNER_SHA:
        raise ValueError("the adopted rack model or runner changed")

    reference = json.loads((EVIDENCE_DIR / "locked-evidence.json").read_text())
    rows = json.loads(args.reference_rows.read_text())
    historical = rows["historical_locked_gains"]
    baseline = summarize(historical, "twin_encoder")
    if baseline != reference["adopted_lugre_encoder_scores"]["historical_locked_gains"]:
        raise ValueError("historical baseline is inconsistent with committed evidence")
    expected = {row["task"]: row["command_sha256"] for row in historical}
    kp_scale = reference["g2_controller"]["gain_scale"]
    kd_scale = reference["g2_controller"]["damping_scale"]

    dataset = load_dataset(args.dataset)
    tapes = frozen_tapes(dataset)
    board = rack.record_station(STATION)
    adopted, frame = adopted_parameters(board)
    if set(tapes) != set(expected) or frame != reference["model_frame"] or dataset.info.rate_hz != reference["host_rate_hz"]:
        raise ValueError("the comparison frame, targets or clock differ from the prior replay")
    commands = {}
    for task, tape in tapes.items():
        template, window = rack_template(task, tape)
        frozen = replace(template, kp_scale=kp_scale, kd_scale=kd_scale)
        _, checksum = run_commands(frozen, board, task)
        if checksum != expected[task]:
            raise ValueError(f"{task}: historical command stream differs from previous high-gain run")
        commands[task] = (window, frozen)

    stress, assumptions = sealed_stress(tapes, commands, board, adopted, args.output.parent / "scenes", args.workers)
    if assumptions != reference["synthetic_gap"]["assumptions"] or any(row["command_sha256"] != expected[row["task"]] for row in stress):
        raise ValueError("the historical comparison changed the synthetic plant or command stream")
    largest = max(stress, key=lambda row: row["max_encoder_to_load_mm"])
    report = {"dataset_manifest_sha256": DATASET_SHA, "split": "dev", "rung": RUNG, "model_version": VERSION,
              "model_sha256": MODEL_SHA, "controller": "historical ff_model", "kp_scale": kp_scale, "kd_scale": kd_scale,
              "reference_rows_sha256": REFERENCE_ROWS_SHA, "model_frame": frame, "adopted_lugre_encoder": baseline,
              "synthetic_gap": {"assumptions": assumptions, "twin_encoder": summarize(stress, "twin_encoder"),
                                "twin_load": summarize(stress, "twin_load"), "max_encoder_to_load_mm": largest["max_encoder_to_load_mm"],
                                "max_encoder_to_load_task": largest["task"]}}
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.output.with_suffix(".rows.json").write_text(json.dumps(stress, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
