"""A controller tracks the UR5e at its full time scale (Zach, 2026-11-25, Vibe Tracks feedback fb-85acc868, positive:
"The UR is asctually working, we have a controller that can control it properly at like its maximum time scale.. Ok
thats not trivial.").

Held on the committed speed study (experiments/ur5e_speed_sweep/study.json: off-score UR5e simulation, dev split, 42
targets, nominal tapes at the configured joint-speed limits). The bar is Zach's standing 1 mm tool gate (OBJECTIVES.md,
2026-11-11), applied to every target's tool RMS, not only the median. A refit that loses full speed turns this red.
"""
from __future__ import annotations

import json
from pathlib import Path

STUDY = Path(__file__).resolve().parent.parent / "experiments" / "ur5e_speed_sweep" / "study.json"
TOOL_GATE_MM = 1.0


def test_the_sweep_reaches_the_full_time_scale():
    study = json.loads(STUDY.read_text())
    assert study["fractions"][-1] == 1.0
    assert len(study["targets"]) >= 40


def test_some_controller_keeps_every_target_inside_the_tool_gate_at_full_speed():
    study = json.loads(STUDY.read_text())
    full = study["fractions"].index(1.0)
    worst = {name: max(per_speed[full]) for name, per_speed in study["tracking_rms_mm"].items()
             if len(per_speed[full]) == len(study["targets"])}
    assert worst, "no controller scored every target at full speed"
    best = min(worst, key=worst.get)
    assert worst[best] <= TOOL_GATE_MM, f"best at full speed is {best}: worst target {worst[best]:.3f} mm"
