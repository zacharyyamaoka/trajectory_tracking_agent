"""site/data/junit.xml: the test run the Spec page reads, committed by `tools/build_site.py build` because CI cannot
run the tests (the deps are local path deps) and folds the committed file instead (.github/workflows/pages.yml). It is
public, so it names no host and no local path, and state.json was folded from exactly this run."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "site" / "data"
JUNIT = DATA / "junit.xml"
RELATIVE = "../../../site/data/junit.xml"  # relative to tools/bb/viewer/, as build_site and ci_refold.py hand it


def _build_site():
    spec = importlib.util.spec_from_file_location("build_site", REPO / "tools" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not JUNIT.exists(), reason="site/ not built")
def test_the_committed_junit_names_no_host_or_local_path_and_is_the_run_state_json_folded():
    text = JUNIT.read_text()
    root = ET.fromstring(text)
    assert not [e.tag for e in root.iter() if "hostname" in e.attrib]
    for local in ("/home/", str(REPO), str(Path.home()), "/tmp/"):
        assert local not in text, local
    suite = next(root.iter("testsuite"))
    spec = json.loads((DATA / "state.json").read_text())["spec"]
    assert spec["junit"] == RELATIVE
    assert spec["junit_run"]["tests"] == int(suite.get("tests")) and spec["junit_run"]["at"] == suite.get("timestamp")


def test_public_junit_drops_the_host_and_relativises_paths_and_keeps_what_the_fold_reads():
    bs = _build_site()
    home, repo, tmp = str(Path.home()), str(REPO), tempfile.gettempdir()
    raw = (f'<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest" errors="0" '
           f'failures="1" skipped="1" tests="3" time="1.5" timestamp="2026-11-24T20:00:00" hostname="some-host">'
           f'<testcase classname="tests.test_a" name="test_ok" time="0.1" />'
           f'<testcase classname="tests.test_a" name="test_bad[x]" time="0.2"><failure message="{repo}/tests/test_a.py:9: '
           f'boom">{repo}/tests/test_a.py:9: in test_bad\n  {home}/robot_controllers/x.py:3: AssertionError</failure>'
           f'</testcase><testcase classname="tests.test_b" name="test_skip" time="0"><skipped message="{home}/y {tmp}/pytest-of-x/z" />'
           f'</testcase></testsuite></testsuites>')
    out = bs.public_junit(raw)
    assert "hostname" not in out and home not in out and repo not in out and tmp not in out
    assert "tests/test_a.py:9: in test_bad" in out and "~/robot_controllers/x.py:3" in out
    a, b = ET.fromstring(raw), ET.fromstring(out)

    def read(root):  # what the fold reads (blackbox_agent proposals-vibetracks/_build/extract.py junit())
        suite = next(root.iter("testsuite"))
        return ({k: suite.get(k) for k in ("tests", "failures", "errors", "skipped", "time", "timestamp")},
                [(t.get("classname"), t.get("name"), [c.tag for c in t]) for t in root.iter("testcase")])

    assert read(a) == read(b)
