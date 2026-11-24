"""The page's saved runs (site/data/playback/): the rule picked them, every number equals its scorecard row, every
option the pickers show has its file, and what is drawn was computed natively from the run record.

Replaces tests/test_site_pipeline.py (2026-11-24), which checked the retired in-browser pipeline: its "the card numbers
are run_task's" became `test_every_shipped_number_is_its_scorecard_row` (now exact, read from the shipped files), its
"every drawing reproduces its card" became `test_every_drawing_agrees_with_its_card`, and its JSON check became the
codec and decoding tests.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
PLAYBACK = SITE / "data" / "playback"
RUNS = REPO / "outputs" / "runs"

pytestmark = pytest.mark.skipif(not (PLAYBACK / "index.json").exists(), reason="site/data/playback not built")


def _build_site():
    spec = importlib.util.spec_from_file_location("build_site", REPO / "tools" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bs = _build_site()


@pytest.fixture(scope="module")
def index():
    return json.loads((PLAYBACK / "index.json").read_text())


def test_every_shipped_number_is_its_scorecard_row():
    """`check`: the shipped pairs are the rule's on the current ledger, and every run file's metrics, gates and notes
    equal its scorecard's per-task row exactly (and the files decode, with the task's row count)."""
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
    for row in index["solutions"]:
        meta = json.loads((REPO / "solutions" / row["id"] / "meta.json").read_text())
        assert "ablation" not in meta.get("tags", []), f"{row['id']} is an ablation: it never ships"
        if row["id"] in (best, gen0):
            assert sorted(row["tasks"]) == sorted(kinds), f"{row['id']} ships every dev task"
        else:
            assert sorted(row["tasks"]) == sorted(representative)
    assert "gen-0" in json.loads((REPO / "solutions" / gen0 / "meta.json").read_text())["tags"]
    assert index["rule"]["count"] == sum(len(row["tasks"]) for row in index["solutions"])


def test_every_option_has_its_files(index):
    """The pickers list index.solutions and each one's tasks; each must load: its run file and its task file exist."""
    tasks = {row["id"]: row for row in index["tasks"]}
    for row in index["solutions"]:
        assert row["tasks"], f"{row['id']} ships no task: it would be a dead option"
        for task_id, entry in row["tasks"].items():
            assert task_id in tasks
            assert (PLAYBACK / entry["file"]).exists(), entry["file"]
            assert (PLAYBACK / tasks[task_id]["file"]).exists()
        assert (SITE / "data" / "solutions" / row["id"] / "solution.py").exists()


def test_every_drawing_agrees_with_its_card(index):
    """The ruler's functions re-run on each record's saved samples reproduce the tracking numbers (within the record's
    0.1 um rounding), and the 100 Hz samples drawn for the 4 kHz gates never contradict the ruler's count."""
    for row in index["solutions"]:
        for task_id, entry in row["tasks"].items():
            header = _header(entry["file"])
            for name, item in header["explain"]["checks"].items():
                assert item["ok"], f"{row['id']} {task_id} {name}: {item}"
                if item["ruler"] is not None:
                    assert abs(item["ruler"] - item["record"]) <= bs.CHECK_TOLERANCE_MM
            for name, item in header["explain"]["subset"].items():
                assert item["consistent"] is not False, f"{row['id']} {task_id} {name}: {item}"


def _header(rel: str) -> dict:
    import gzip
    import struct

    blob = gzip.decompress((PLAYBACK / rel).read_bytes())
    length = struct.unpack("<I", blob[8:12])[0]
    return json.loads(blob[12:12 + length])


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
    """A few shipped runs whose record is on this machine: the default, a failing one, a long one."""
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
    """Decoded, a run file gives back the record's joints and tool points (within the stated steps), and the drawn arm
    is the deployment's own FK of the record's joints: its geoms carry the body origins of `deployment.link_points`."""
    pytest.importorskip("mujoco")
    from trajectory_tracking_agent.ruler.deployment import deployment

    pairs = _pairs_with_records(index)
    if not pairs:
        pytest.skip("no run records on this machine (outputs/ is gitignored)")
    dep = deployment("ur5e_alone")
    steps = index["codec"]["steps"]
    solutions = {row["id"]: row for row in index["solutions"]}
    for sid, task in pairs:
        record = json.loads((RUNS / sid / "dev" / f"{task}.json").read_text())
        _, task_values, task_ints = bs.read_playback(PLAYBACK / f"tasks/{task}.bin.gz")
        header, values, _ = bs.read_playback(PLAYBACK / solutions[sid]["tasks"][task]["file"], base=task_ints)
        assert header["metrics"] == record["metrics"] and header["gates"] == record["gates"]
        q = np.asarray(record["q"], dtype=float)
        assert np.max(np.abs(values["q"] - q)) <= steps["q"]
        assert np.max(np.abs(task_values["q_target"] - np.asarray(record["q_target"]))) <= steps["q"]
        assert np.max(np.abs(values["tool"] - np.asarray(record["tool_xyz"]))) <= steps["tool"]
        assert np.max(np.abs(values["tool"] - dep.tool_position(q))) <= 2 * steps["tool"]
        # the drawn arm: the geom poses of the record's joints, from the model whose body origins _Poses checks equal
        # deployment.link_points (it refuses otherwise)
        pos, _ = bs._Poses(dep)(q)
        assert np.max(np.abs(values["geom_pos"] - pos)) <= steps["geom_pos"]
