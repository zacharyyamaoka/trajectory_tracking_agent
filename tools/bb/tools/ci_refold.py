#!/usr/bin/env python3
"""CI's step for a black-box repo's live page: re-fold site/data/state.json from the checked-out commit.

    python3 tools/bb/tools/ci_refold.py --box .        # template/.github/workflows/pages.yml's build job

Runs from the box's vendored copy (tools/bb/, written by tools/vendor_fold.py) on stdlib + git alone. In order; any
failure exits non-zero and leaves site/data/state.json as it was, so the deploy fails and the page stays on its last
good deploy, never a half state:
1. the vendored copy matches its VENDOR.json (vendor_fold --check);
2. site/data/junit.xml, when committed, names no host and no home path (it is published under site/);
3. the fold of HEAD, handed that junit by a path relative to the fold's viewer/ (the string lands in state.json, so an
   absolute path would put the runner's home dir on the page);
4. the slice the box's own export writes is kept from the committed state.json: `playback` (viewer CONTRACT §4, §14:
   the export lists its bb-run/1 records there; the fold never makes it), placed before `source` as the box's build
   places it. WHY: a bare re-fold would drop the runs the landing page plays;
5. the result is a bb-state/1 fold of exactly HEAD; it replaces state.json in one rename.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent  # <box>/tools/bb/tools
FOLD = HERE.parent / "viewer" / "tools" / "fold_state.py"
STATE = "site/data/state.json"
JUNIT = "site/data/junit.xml"
EXPORT_SLICES = ("playback",)  # CONTRACT §4: the one slice a box's export writes into state.json
LEAK = re.compile(r"hostname=|/home/")


def git(box: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(box), *args], capture_output=True, text=True)


def dump(state: dict) -> str:
    return json.dumps(state, indent=1, ensure_ascii=False) + "\n"  # the fold's and the box build's own format


def refold(box: Path) -> dict:
    sys.path.insert(0, str(HERE))
    import vendor_fold

    problems = vendor_fold.check(box)
    if problems:
        raise SystemExit("the vendored fold differs from its VENDOR.json (re-vendor it):\n  " + "\n  ".join(problems))
    head = git(box, "rev-parse", "HEAD").stdout.strip()
    cmd = [sys.executable, str(FOLD), "--repo", str(box), "--ref", "HEAD"]
    junit = box / JUNIT
    if junit.exists():
        if LEAK.search(junit.read_text(errors="replace")):
            raise SystemExit(f"{JUNIT} names a host or a home path: rebuild it with the box's site build")
        cmd += ["--junit", os.path.relpath(junit, FOLD.parent.parent)]
    with tempfile.TemporaryDirectory(prefix="bb-refold-") as tmp:
        out = Path(tmp) / "state.json"
        run = subprocess.run([*cmd, "--out", str(out)], capture_output=True, text=True)
        if run.returncode != 0 or not out.exists():
            raise SystemExit(f"the fold failed (exit {run.returncode}):\n{run.stderr.strip()[-3000:]}")
        fresh = json.loads(out.read_text())
    if fresh.get("schema") != "bb-state/1" or (fresh.get("source") or {}).get("ref") != head:
        raise SystemExit(f"the fold's output is not a bb-state/1 fold of {head}")
    shown = git(box, "show", f"HEAD:{STATE}")
    committed = json.loads(shown.stdout) if shown.returncode == 0 else {}
    carry = {k: committed[k] for k in EXPORT_SLICES if k in committed and k not in fresh}
    state = {}
    for key, value in fresh.items():
        if key == "source":
            state.update(carry)
        state[key] = value
    state.update({k: v for k, v in carry.items() if k not in state})
    target = box / STATE
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.write_text(dump(state))
    os.replace(partial, target)
    return {"ref": head[:7], "kept": sorted(carry), "junit": junit.exists(), "keys": len(state)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--box", default=".", help="the black-box repo (default: the current directory)")
    a = ap.parse_args()
    done = refold(Path(a.box).resolve())
    print(f"{STATE}: folded at {done['ref']}, kept {', '.join(done['kept']) or 'nothing'} from the committed file, "
          f"junit {'folded' if done['junit'] else 'absent'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
