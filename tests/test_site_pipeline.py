"""The page's driver (site/runtime/pipeline.py), run natively: it returns the ruler's own numbers, and every drawing it
ships reproduces the number on its card. The same file runs in the browser (tools/build_site.py parity)."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PIPELINE = REPO / "site" / "runtime" / "pipeline.py"
FIELDS = REPO / "site" / "runtime" / "mujoco_fields.json"

pytest.importorskip("mujoco")
pytest.importorskip("robot_controllers")


def _pipeline():
    spec = importlib.util.spec_from_file_location("site_pipeline", PIPELINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def run():
    return _pipeline().run("p2", "workspace-dev-000", render=True)


def test_the_card_numbers_are_run_task_s(run):
    from trajectory_tracking_agent.evaluate import run_task

    row = run_task("p2", "workspace-dev-000")
    assert run["row"]["objective"] == row["objective"]
    assert run["row"]["kpis"] == row["kpis"]
    assert run["row"]["verdicts"] == row["verdicts"]


def test_every_drawing_reproduces_its_card(run):
    for name, (ruler, drawn) in run["explain"]["checks"].items():
        assert ruler is not None, name
        if isinstance(ruler, float):
            assert math.isclose(ruler, drawn, rel_tol=1e-12, abs_tol=1e-12), name
        else:
            assert ruler == drawn, name


def test_the_run_is_json_for_the_page(run):
    text = _pipeline().dumps(run)
    assert "NaN" not in text and "Infinity" not in text
    page = json.loads(text)
    frames = page["render"]
    assert len(frames["t"]) == len(frames["measured"]["geom_xpos"]) == len(frames["target"]["geom_xpos"])
    assert len(frames["lowest"]) == len(frames["t"])


def test_field_table_matches_native_mujoco():
    """The shim shapes arrays from mujoco_fields.json; it must agree with the native bindings for every field the UR5e
    plant, its feed-forward and the ruler touch."""
    import mujoco
    from robot_controllers.bench.ur5e import load_model

    table = json.loads(FIELDS.read_text())
    assert table["mujoco"] == mujoco.__version__
    model = load_model()
    data = mujoco.MjData(model)
    used = {"MjModel": ("dof_armature", "dof_damping", "dof_frictionloss", "body_mass", "body_inertia", "body_jntnum",
                        "jnt_range", "geom_type", "geom_size", "geom_bodyid"),
            "MjData": ("qpos", "qvel", "qacc", "qfrc_applied", "qfrc_inverse", "site_xpos", "xpos", "geom_xpos",
                       "geom_xmat", "efc_type", "efc_id", "efc_force")}
    for kind, names in used.items():
        source = model if kind == "MjModel" else data
        for name in names:
            assert table[kind][name] == list(getattr(source, name).shape[1:]), f"{kind}.{name}"
