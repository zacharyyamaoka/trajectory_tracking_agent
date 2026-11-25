"""The page's saved runs (site/data/runs/, listed in site/data/state.json's playback slice): the rule picked them, every
option the pickers offer has a bb-run/1 record that state.playback.runs lists and that validates against the
blackbox_agent viewer's own schema, every number equals its scorecard row, and what is drawn is the run record's.

Rewritten 2026-11-24 (lane EV) when the page's own 3D stage gave way to the viewer's <bb-evidence>: the shipped files
went from the page's binary playback (site/data/playback/, now the build's intermediate in outputs/) to bb-run/1
records, so "every option has its files" became `test_every_picker_option_has_a_listed_valid_record`, and the FK check
reads the record's channels and drawn poses. The codec tests stay: the build still writes that export.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
DATA = SITE / "data"
INDEX = DATA / "runs" / "index.json"
RUNS = REPO / "outputs" / "runs"

pytestmark = pytest.mark.skipif(not INDEX.exists(), reason="site/data/runs not built")


def _build_site():
    spec = importlib.util.spec_from_file_location("build_site", REPO / "tools" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bs = _build_site()


@pytest.fixture(scope="module")
def index():
    return json.loads(INDEX.read_text())


@pytest.fixture(scope="module")
def state():
    return json.loads((DATA / "state.json").read_text())


# ── a JSON Schema (draft-07) validator for the keywords the viewer's schemas use, stdlib only ─────────────────
# WHY here: jsonschema is not a dependency of this repo (lanes never install one). Checked 2026-11-24 against the
# viewer's own ajv on all 244 records and state.json (same verdicts, and ajv rejects the broken record below too);
# `test_the_validator_can_fail` keeps it honest.

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is(value: Any, kind: str) -> bool:
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, float) and value.is_integer())
    return isinstance(value, _TYPES[kind])


def schema_errors(value: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    root = root or schema
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/"), f"only local refs: {ref}"
        target = root
        for part in ref[2:].split("/"):
            target = target[part]
        return schema_errors(value, target, root, path)
    errors: list[str] = []
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is(value, kind) for kind in kinds):
            return [f"{path}: {type(value).__name__} is not {kinds}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: {value!r} is not {schema['const']!r}")
    if "enum" in schema and not any(value == option and type(value) is type(option) or
                                    (_is(value, "number") and _is(option, "number") and value == option)
                                    for option in schema["enum"]):
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors += schema_errors(value[key], sub, root, f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: unexpected {key}" for key in value if key not in schema.get("properties", {})]
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            errors.append(f"{path}: {len(value)} items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errors += schema_errors(item, schema["items"], root, f"{path}[{i}]")
    if "oneOf" in schema:
        matching = sum(1 for sub in schema["oneOf"] if not schema_errors(value, sub, root, path))
        if matching != 1:
            errors.append(f"{path}: matches {matching} of oneOf, not exactly 1")
    return errors


@pytest.fixture(scope="module")
def run_schema():
    if not bs.RUN_RECORD_SCHEMA.exists():
        pytest.skip(f"the viewer's {bs.RUN_RECORD_SCHEMA.name} is not on this machine (BB_FOLD_RUNS)")
    return json.loads(bs.RUN_RECORD_SCHEMA.read_text())


@pytest.fixture(scope="module")
def playback_schema():
    path = bs.RUN_RECORD_SCHEMA.parent / "slices" / "playback.schema.json"
    if not path.exists():
        pytest.skip("the viewer's slices/playback.schema.json is not on this machine")
    return json.loads(path.read_text())


# ── the tests ──────────────────────────────────────────────────────────────────────────────────────────────


def test_every_shipped_number_is_its_scorecard_row():
    """`check`: the shipped runs are the rule's on the current ledger, state.json lists exactly their records, and
    every record's metrics, gate verdicts and notes equal its scorecard's per-task row (at the fold's rounding)."""
    problems = bs.check()
    assert not problems, "\n".join(problems[:20])


def test_the_rule(index):
    rule = bs.selection()
    best, gen0 = rule["full"]["best"], rule["full"]["gen0_best"]
    assert best and gen0
    kinds = dict(bs._dev_task_kinds())
    representative = rule["representative_tasks"]
    assert len(representative) == len(set(kinds.values())), "one representative task per kind"
    assert sorted(kinds[t] for t in representative) == sorted(set(kinds.values()))
    for task in representative:  # the first of its kind in dataset order
        first = next(t for t, k in bs._dev_task_kinds() if k == kinds[task])
        assert task == first
    assert not index["left_out"], f"runs the fold refused: {index['left_out']}"
    for row in index["solutions"]:
        meta = json.loads((REPO / "solutions" / row["id"] / "meta.json").read_text())
        assert "ablation" not in meta.get("tags", []), f"{row['id']} is an ablation: it never ships"
        if row["id"] in (best, gen0):
            assert sorted(row["tasks"]) == sorted(kinds), f"{row['id']} ships every dev task"
        else:
            assert sorted(row["tasks"]) == sorted(representative)
    assert "gen-0" in json.loads((REPO / "solutions" / gen0 / "meta.json").read_text())["tags"]
    assert index["rule"]["count"] == sum(len(row["tasks"]) for row in index["solutions"]) == rule["count"]


def test_every_picker_option_has_a_listed_valid_record(index, state, run_schema, playback_schema):
    """The run row (the stock landing's <bb-evidence>, one chip per listed run) offers index.solutions and each one's
    tasks; every such run has a bb-run/1 record
    that state.json's playback slice lists (so bb-evidence's context may load it), and the record validates against
    the viewer's run-record.schema.json, read where it lives; the slice validates against its own schema."""
    assert not schema_errors(state["playback"], playback_schema), schema_errors(state["playback"], playback_schema)[:5]
    listed = {(row["solution"], row["task"]): row for row in state["playback"]["runs"]}
    offered = [(row["id"], task) for row in index["solutions"] for task in row["tasks"]]
    assert len(offered) == len(listed) == index["rule"]["count"]
    for sid, task in offered:
        entry = next(r for r in index["solutions"] if r["id"] == sid)["tasks"][task]
        row = listed.get((sid, task))
        assert row, f"{sid} {task}: offered by the pickers but not listed in state.playback.runs"
        assert row["path"] == entry["record"] and row["schema"] == "bb-run/1"
        record = json.loads((DATA / row["path"]).read_text())
        errors = schema_errors(record, run_schema)
        assert not errors, f"{row['path']}: {errors[:5]}"
        assert record["id"] == f"{sid}/{task}" and record["subject"]["label"] == row["label"]
    assert (SITE / "data" / "solutions" / offered[0][0] / "solution.py").exists()


def test_every_listed_run_carries_the_verdict_its_record_shows(index, state):
    """Each state.playback.runs entry says `admissible`: true when that solution passed every gate on that task, the
    verdict its record shows (every gate metric `passed`) and its index entry's `pass`. blackbox_agent 0.1.5's
    <bb-evidence> colours a chip from it without fetching the record (else it loads all of them, or on hover past 24).
    Both colours occur, so a constant cannot pass."""
    passes = {(row["id"], task): entry["pass"] for row in index["solutions"] for task, entry in row["tasks"].items()}
    seen = set()
    for row in state["playback"]["runs"]:
        assert isinstance(row.get("admissible"), bool), f"{row['path']}: no admissible verdict on the listed run"
        record = json.loads((DATA / row["path"]).read_text())
        gates = [metric["passed"] for metric in record["metrics"] if metric["kind"] == "gate"]
        assert gates and row["admissible"] == all(gate is True for gate in gates), row["path"]
        assert row["admissible"] == passes[(row["solution"], row["task"])], row["path"]
        seen.add(row["admissible"])
    assert seen == {True, False}


def test_the_validator_can_fail(state, run_schema, playback_schema):
    """The validator above rejects what the viewer's ajv rejects: a record missing its time base, a metric of an unknown
    kind, a layer with neither poses nor a chain, a counted set that is two kinds at once, and a slice row whose
    path is not a .json file."""
    good = json.loads((DATA / state["playback"]["runs"][0]["path"]).read_text())
    assert not schema_errors(good, run_schema)
    broken = [json.loads(json.dumps(good)) for _ in range(4)]
    del broken[0]["time"]
    broken[1]["metrics"][0]["kind"] = "bogus"
    del broken[2]["scene"]["geometry"]["layers"][0]["poses"]
    broken[3]["metrics"][0]["evidence"]["counted"] = {"all": True, "windows": [[0, 1]]}
    for record in broken:
        assert schema_errors(record, run_schema), "a broken record passed"
    row = {**state["playback"]["runs"][0], "path": state["playback"]["runs"][0]["path"] + ".gz"}
    assert schema_errors({"runs": [row]}, playback_schema)
    assert schema_errors({}, run_schema), "an empty record must not pass"


def test_every_drawing_agrees_with_its_card(index):
    """The ruler's functions re-run at build time on each record's saved samples reproduce the tracking numbers (within
    the record's 0.1 um rounding), and the 100 Hz samples drawn for the 4 kHz gates never contradict the ruler's count."""
    for row in index["solutions"]:
        for task_id, entry in row["tasks"].items():
            for name, item in entry["checks"].items():
                assert item["ok"], f"{row['id']} {task_id} {name}: {item}"
                if item["ruler"] is not None:
                    assert abs(item["ruler"] - item["record"]) <= bs.CHECK_TOLERANCE_MM
            for name, item in entry["subset"].items():
                assert item["consistent"] is not False, f"{row['id']} {task_id} {name}: {item}"


def test_the_display_resolution_keeps_the_evidence(index):
    """Compacting for the page never thins what a metric counts: every channel keeps all of the record's 100 Hz samples,
    the drawn arm runs at 25 Hz and keeps the frame at each metric's peak (a paused peak shows the arm there)."""
    import bisect

    entry = index["solutions"][0]["tasks"]
    for task_id in list(entry)[:3]:
        record = json.loads((DATA / entry[task_id]["record"]).read_text())
        t = record["time"]["t"]
        assert record["time"]["rate_hz"] == 100.0 and all(len(c["values"]) == len(t) for c in record["channels"])
        for layer in record["scene"]["geometry"]["layers"]:
            frames = layer["t"]
            assert len(frames) == len(layer["poses"]) and frames[0] == t[0] and frames[-1] == t[-1]
            assert len(frames) <= len(t) // bs.GEOMETRY_STRIDE + 1 + len(record["metrics"])
            for metric in record["metrics"]:
                peak = (metric.get("evidence") or {}).get("peak")
                if peak:
                    at = t[peak["i"]] if "i" in peak else t[bisect.bisect_right(t, peak["t"] + 1e-9) - 1]
                    assert at in frames, f"{task_id} {metric['id']}: no drawn frame at its peak {at}"


@pytest.mark.parametrize("shape", [(1,), (7,), (495, 6), (300, 3), (120, 7, 4)])
def test_the_codec_round_trips(shape):
    rng = np.random.default_rng(len(shape) * 1000 + shape[0])
    for scale in (3, 300, 70_000, 2**29):
        ints = np.cumsum(rng.integers(-scale, scale + 1, size=shape), axis=0)
        data, dtype = bs._pack(ints)
        back = bs._unpack(data, dtype, list(shape))
        assert back.shape == ints.shape and back.dtype == np.int64
        assert np.array_equal(back, ints), (shape, scale, dtype)


def test_a_playback_file_round_trips(tmp_path):
    t = np.arange(50)
    base = {"x": bs._quantize(np.sin(t / 7.0)[:, None] * [1, 2], 1e-7)}
    measured = np.sin(t / 7.0 + 0.001)[:, None] * [1, 2]
    arrays = {"x": (base["x"], 1e-7, None), "y": (bs._quantize(measured, 1e-7) - base["x"], 1e-7, "x")}
    bs.write_playback(tmp_path / "f.bin.gz", {"hello": 1}, {"x": arrays["x"]})
    header, values, ints = bs.read_playback(tmp_path / "f.bin.gz")
    assert header["hello"] == 1 and np.array_equal(ints["x"], base["x"])
    bs.write_playback(tmp_path / "g.bin.gz", {}, {"y": arrays["y"]})
    _, values, _ = bs.read_playback(tmp_path / "g.bin.gz", base=base)
    assert np.max(np.abs(values["y"] - measured)) <= 0.5e-7 + 1e-15
    first = (tmp_path / "g.bin.gz").read_bytes()
    bs.write_playback(tmp_path / "g.bin.gz", {}, {"y": arrays["y"]})
    assert (tmp_path / "g.bin.gz").read_bytes() == first, "a rebuild with no change must be byte-identical"


def _pairs_with_records(index, count=3):
    """A few shipped runs whose `tta evaluate` record is on this machine: the default, a failing one, a long one."""
    out = []
    best = index["rule"]["full"]["best"]
    wanted = [(best, "workspace-dev-001")]
    for row in index["solutions"]:
        failing = next((t for t, e in row["tasks"].items() if not e["pass"]), None)
        if failing:
            wanted.append((row["id"], failing))
            break
    wanted.append((index["rule"]["full"]["gen0_best"], "workspace-dev-022"))
    for sid, task in wanted[:count]:
        if (RUNS / sid / "dev" / f"{task}.json").exists():
            out.append((sid, task))
    return out


def test_what_is_drawn_is_the_record_through_the_deployments_fk(index):
    """A shipped bb-run/1 record gives back the `tta evaluate` record's joints and tool points (within the display
    rounding), and its drawn arm is the deployment's own FK of the record's joints: the measured layer's poses are the
    geom poses of those joints, from the model whose body origins equal `deployment.link_points` (_Poses refuses
    otherwise)."""
    pytest.importorskip("mujoco")
    from trajectory_tracking_agent.ruler.deployment import deployment

    pairs = _pairs_with_records(index)
    if not pairs:
        pytest.skip("no run records on this machine (outputs/ is gitignored)")
    dep = deployment("ur5e_alone")
    solutions = {row["id"]: row for row in index["solutions"]}
    for sid, task in pairs:
        saved = json.loads((RUNS / sid / "dev" / f"{task}.json").read_text())
        record = json.loads((DATA / solutions[sid]["tasks"][task]["record"]).read_text())
        channel = {c["id"]: np.asarray(c["values"], dtype=float) for c in record["channels"]}
        q = np.asarray(saved["q"], dtype=float)
        assert np.allclose(record["time"]["t"], saved["t"], atol=1e-6)
        # the export's step, the fold's rounding, then the page's (1e-4 deg, 1 um): each adds at most half its step
        deg_bound = np.degrees(0.5e-7) + 0.5e-5 + 0.5e-4 + 1e-12
        assert np.max(np.abs(channel["q"] - np.degrees(q))) <= deg_bound
        assert np.max(np.abs(channel["q_target"] - np.degrees(np.asarray(saved["q_target"])))) <= deg_bound
        assert np.max(np.abs(channel["tool"] - np.asarray(saved["tool_xyz"]))) <= 0.5e-7 + 0.5e-7 + 0.5e-6 + 1e-12
        assert np.max(np.abs(channel["tool"] - dep.tool_position(q))) <= 1e-6
        assert record["metrics"][0]["value"] == pytest.approx(saved["metrics"]["tool_track_rms_mm"], abs=0.5e-6)
        measured = next(layer for layer in record["scene"]["geometry"]["layers"] if layer["id"] == "measured")
        rows = [record["time"]["t"].index(t) for t in measured["t"]]
        pos, _ = bs._Poses(dep)(q[rows])
        drawn = np.asarray(measured["poses"], dtype=float)[:, :, :3]
        assert np.max(np.abs(drawn - pos)) <= 0.5 * 10.0 ** -bs.POSE_DIGITS + 1e-5  # the drawn arm's stated rounding
