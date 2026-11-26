"""Fit the pendulum's board-effort model from recorded development JointState messages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def motion_rows(states):
    time, position, _velocity, effort = np.asarray(states, dtype=float).T
    period = float(np.median(np.diff(time)))
    if not np.isfinite(states).all() or period <= 0 or not np.allclose(np.diff(time), period, rtol=0, atol=1e-9):
        raise ValueError("expected finite samples on the uniform controller reply clock")
    # WHY derive velocity from the encoder samples: the board's reported velocity is filtered and delayed.
    offsets = np.arange(-2, 3, dtype=float)
    derivative = np.linalg.pinv(np.vander(offsets, N=4, increasing=True))[1] / period
    speed = np.lib.stride_tricks.sliding_window_view(position, 5) @ derivative
    acceleration = np.lib.stride_tricks.sliding_window_view(speed, 5) @ derivative
    position, effort, speed = position[4:-4], effort[4:-4], speed[2:-2]
    moving = np.abs(speed) > 0.2
    return np.column_stack((np.sin(position), np.cos(position), np.sign(speed), speed, acceleration))[moving], effort[moving]


def identify(probes):
    summary_path = probes / "summary.json"
    summary = json.loads(summary_path.read_text())
    if summary.get("split") != "dev" or summary.get("domain") != "sim" or len(summary.get("runs", [])) != 40:
        raise ValueError("expected the 40 simulation development runs")
    design, efforts = [], []
    for run in summary["runs"]:
        recording = probes / run["recording"]
        if digest(recording) != run["recording_sha256"] or not run["checks"]["completed"]:
            raise ValueError(f"incomplete or changed calibration recording {recording}")
        with np.load(recording) as data:
            rows, effort = motion_rows(data["controller_state"])
        design.append(rows)
        efforts.append(effort)
    design, efforts = np.concatenate(design), np.concatenate(efforts)
    coeff, _, rank, _ = np.linalg.lstsq(design, efforts, rcond=None)
    if rank != design.shape[1]:
        raise ValueError("the probes do not excite all five model terms")
    names = ("gravity_sin_nm", "gravity_cos_nm", "coulomb_nm", "viscous_nm_s_rad", "inertia_kg_m2")
    return {"schema": "tta.pendulum-feedforward/1", "probe_summary_sha256": digest(summary_path),
            "dataset_manifest_sha256": summary["dataset_manifest_sha256"], "moving_samples": len(efforts),
            "fit_residual_rms_nm": float(np.sqrt(np.mean((design @ coeff - efforts) ** 2))),
            "coefficients": dict(zip(names, coeff.tolist(), strict=True))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probes", type=Path)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    args.model.write_text(json.dumps(identify(args.probes), indent=2, allow_nan=False) + "\n")
