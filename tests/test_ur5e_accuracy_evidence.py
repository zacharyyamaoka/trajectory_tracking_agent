import runpy
from pathlib import Path

import numpy as np
import pytest

accuracy = runpy.run_path(Path(__file__).resolve().parents[1] / "experiments" / "ur5e_speed_sweep" / "accuracy.py")


def test_complete_matrix_rejects_an_empty_or_relabelled_run_set():
    expected = [("target", 0.1), ("target", 1.0)]
    accuracy["exact_matrix"](list(reversed(expected)), expected, "sweep")
    with pytest.raises(ValueError, match="missing"):
        accuracy["exact_matrix"]([], expected, "sweep")
    with pytest.raises(ValueError, match="repeated"):
        accuracy["exact_matrix"]([expected[0], expected[0]], expected, "sweep")


def test_recording_includes_holds_and_requires_a_measured_stop(tmp_path):
    samples = 41
    clock = np.arange(samples) / 100
    moving = np.arange(samples) < 20
    desired = np.repeat(np.eye(4)[None, :, :], samples, axis=0)
    actual = desired.copy()
    actual[20:, 0, 3] = 0.001
    path = tmp_path / "recording.npz"
    np.savez(path, t=clock, moving=moving, target_poses=desired, actual_poses=actual)
    assert accuracy["recording_measurements"](path, samples, 0.4) == pytest.approx((np.sqrt(21 / 41), 1, 1))

    moving[20] = True  # Twenty samples span 0.19 s, so this trace has no scored stop.
    np.savez(path, t=clock, moving=moving, target_poses=desired, actual_poses=actual)
    with pytest.raises(ValueError, match="no measured stops"):
        accuracy["recording_measurements"](path, samples, 0.4)


def test_failed_gate_keeps_its_numeric_measurements():
    gate_names = accuracy["COMMON_CHECKS"] | {"scene_clearance"}
    verdicts = {name: name != "scene_clearance" for name in gate_names}
    row = accuracy["row"]("portal", "cycle", 1.0, 0.3, 0.4, 10, 900, verdicts)
    summary = accuracy["summarize"]([row])
    assert summary["runs_passing_all_gates"] == 0
    assert summary["worst"]["full_trajectory_rms_mm"]["full_trajectory_rms_mm"] == 0.4
    with pytest.raises(ValueError, match="finite"):
        accuracy["row"]("portal", "cycle", 1.0, None, 0.4, 10, 900, verdicts)
