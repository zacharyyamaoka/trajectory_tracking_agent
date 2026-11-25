#!/usr/bin/env python3
"""Vendor the viewer's fold into a black-box repo, so the box's CI can re-fold site/data/state.json from every push.

    python3 ~/blackbox_agent/tools/vendor_fold.py --box ~/trajectory_tracking_agent             # blackbox_agent HEAD
    python3 ~/blackbox_agent/tools/vendor_fold.py --box ~/trajectory_tracking_agent --ref d1a4906
    python3 ~/trajectory_tracking_agent/tools/bb/tools/vendor_fold.py --check --box ~/trajectory_tracking_agent

Copies the fold's whole file closure (CLOSURE) from one committed blackbox_agent ref into <box>/tools/bb/, keeping the
repo-relative layout, so the fold's own path logic (fold_state.py's BB_REPO = viewer/.., folds/ideas.py's parents[3],
spec.py's proposals-vibetracks/_build, ablation_study.py's proposals-ablation-page/_build) resolves inside the copy
unchanged. Then, in the box:

    python3 tools/bb/viewer/tools/fold_state.py --repo . --ref HEAD --out site/data/state.json

WHY a `git archive` of a ref, never the working tree: other lanes edit the fold in place, so the copy is exactly one
commit, and tools/bb/VENDOR.json names it with every file's sha256. WHY vendored and not fetched: blackbox_agent is
private, so a box's CI cannot clone it. The fold is stdlib + git, so the copy runs on a CI runner's plain python3.
`--check` holds the copy to VENDOR.json (an edited or stray file fails), and needs no blackbox_agent: this script
vendors itself into tools/bb/tools/. Vendoring fails, writing nothing, when a vendored line names a home directory,
the agent config dir, the vault, the private workspace or an e-mail address (FORBIDDEN): a box may be public.

A new import in the fold (a lane module loaded by path) means a new CLOSURE line; tests/test_vendor_fold.py fails
until it is added (the vendored fold crashes, or folds differently from the fold in place).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

VENDOR_DIR = "tools/bb"
SOURCE_URL = "https://github.com/zacharyyamaoka/blackbox_agent"
RUN = "python3 tools/bb/viewer/tools/fold_state.py --repo . --ref HEAD --out site/data/state.json"
# Every file the fold opens, as blackbox_agent-relative globs (a `*` never crosses a `/`). Traced 2026-11-24 with an
# audit hook over `fold_state.py --all --check` (every scenario: standard, rc, spec map, junit, junit_dir, empty box).
CLOSURE = (
    "viewer/tools/fold_state.py",                    # the driver
    "viewer/tools/fold_runs.py",                     # the saved-playback codec it loads by path
    "viewer/tools/folds/*.py",                       # every plug-in slice (a new slice is picked up by the glob)
    "proposals-ideas/_shared/ideas_parse.py",        # fold_state.py's IDEAS_PARSE and folds/ideas.py's V1
    "proposals-ideas/_shared/ideas_history.py",
    "proposals-ideas/_shared/ideas_model.py",
    "proposals-ideas-v2/_shared/common.py",          # folds/ideas.py's V2
    "proposals-ideas-v2/_shared/roadmap.py",
    "proposals-ideas-v2/01-lens-board/format.py",    # folds/ideas.py's LENS
    "proposals-vibetracks/_build/extract.py",        # folds/spec.py's junit() reader
    "proposals-ablation-page/_build/build.py",       # folds/ablation_study.py's PAGE_BUILD
    "proposals-ablation/_shared/build.py",           # ...which imports these two from its sys.path
    "proposals-ablation/_shared/formats.py",
)
# copied too when the ref has them, never required (an older ref predates them): this script, so a box can --check its
# copy without blackbox_agent, and the CI step that uses that copy (template/.github/workflows/pages.yml)
SELF = "tools/vendor_fold.py"
CI = "tools/ci_refold.py"
EXTRAS = (SELF, CI)
# GOTCHAS "Private paths in a public repo": a box may be public, so vendoring FAILS when a vendored line names a home
# directory (/home/<name>; a bare "/home/" is a guard that looks for one), the agent config dir, the vault, the private
# workspace or an e-mail address: the same set trajectory_tracking_agent's own public scans forbid. The fix goes in the
# source here (the copy must stay byte-identical to the commit VENDOR.json names), never in the copy.
# WHY the [o]/[l]/[a] spellings: so this line does not match itself (this script is vendored and scanned too).
FORBIDDEN = re.compile(r"/h[o]me/[A-Za-z0-9_.-]+|\.c[l]aude\b|z[a]ch_brain|b[a]m_ws|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")


def git(repo: Path, *args: str) -> bytes:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args[:3])} in {repo}: {out.stderr.decode().strip()}")
    return out.stdout


def default_source() -> Path:
    """blackbox_agent itself when this script runs from its checkout; from a box's tools/bb/tools/, ~/blackbox_agent."""
    here = Path(__file__).resolve().parents[1]
    return here if (here / ".git").exists() else Path.home() / "blackbox_agent"


def closure(source: Path, sha: str) -> list[str]:
    tree = git(source, "ls-tree", "-r", "--name-only", sha).decode().splitlines()
    files: list[str] = []
    for pattern in CLOSURE:
        hits = [p for p in tree if fnmatch.fnmatchcase(p, pattern) and p.count("/") == pattern.count("/")]
        if not hits:  # a stale CLOSURE line: fail loudly rather than ship a fold missing a file
            raise SystemExit(f"{pattern}: no such file in blackbox_agent@{sha[:7]} (the fold moved; update CLOSURE)")
        files += [p for p in sorted(hits) if p not in files]
    return files + [p for p in EXTRAS if p in tree]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def vendor(box: Path, source: Path, ref: str) -> dict:
    """Write <box>/tools/bb/ from blackbox_agent@ref; returns VENDOR.json's content."""
    sha = git(source, "rev-parse", f"{ref}^{{commit}}").decode().strip()
    files = closure(source, sha)
    blob = git(source, "archive", "--format=tar", sha, "--", *files)
    dest = box / VENDOR_DIR
    if dest.exists() and not (dest / "VENDOR.json").exists():
        raise SystemExit(f"{dest} exists and is not a vendored fold (no VENDOR.json): refusing to replace it")
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows, hits = [], []
    with tempfile.TemporaryDirectory(prefix=".bb-vendor-", dir=dest.parent) as tmp:
        stage = Path(tmp) / "bb"
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            tar.extractall(stage, filter="data")
        for path in files:
            data = (stage / path).read_bytes()
            rows.append({"path": path, "sha256": sha256(data), "bytes": len(data)})
            hits += [f"{path}:{n}: {m.group(0)}" for n, line in enumerate(data.decode(errors="replace").splitlines(), start=1)
                     for m in FORBIDDEN.finditer(line)]
        if hits:  # before anything is written: the box keeps its old copy
            raise SystemExit(f"blackbox_agent@{sha[:7]}: {len(hits)} vendored line(s) name a private path or address; fix "
                             f"them at the source and commit, then vendor again:\n  " + "\n  ".join(hits))
        meta = {
            "what": "The blackbox_agent viewer's fold, vendored so this box's CI re-folds site/data/state.json from "
                    "every pushed commit. Never edit it here: re-vendor with blackbox_agent's tools/vendor_fold.py.",
            "source": SOURCE_URL,
            "commit": sha,
            "commit_date": git(source, "log", "-1", "--format=%cI", sha).decode().strip(),
            "run": RUN,
            "check": f"python3 {VENDOR_DIR}/{SELF} --check --box ." if SELF in files else None,
            "ci": f"python3 {VENDOR_DIR}/{CI} --box ." if CI in files else None,
            "bytes": sum(r["bytes"] for r in rows),
            "files": rows,
        }
        (stage / "VENDOR.json").write_text(json.dumps(meta, indent=1) + "\n")
        if dest.exists():
            shutil.rmtree(dest)
        stage.rename(dest)
    return meta


def check(box: Path) -> list[str]:
    """What differs between <box>/tools/bb/ and its VENDOR.json: edited, missing and stray files."""
    dest = box / VENDOR_DIR
    meta_path = dest / "VENDOR.json"
    if not meta_path.exists():
        return [f"{meta_path} is missing (vendor the fold first)"]
    meta = json.loads(meta_path.read_text())
    want = {r["path"]: r["sha256"] for r in meta["files"]}
    problems = []
    for path, digest in want.items():
        f = dest / path
        if not f.exists():
            problems.append(f"missing: {path}")
        elif sha256(f.read_bytes()) != digest:
            problems.append(f"edited since vendoring: {path}")
    for f in sorted(dest.rglob("*")):
        rel = f.relative_to(dest).as_posix()
        if f.is_file() and rel != "VENDOR.json" and rel not in want and "__pycache__" not in f.parts:
            problems.append(f"not vendored: {rel}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--box", required=True, help="the black-box repo to vendor into (or --check)")
    ap.add_argument("--ref", default="HEAD", help="the blackbox_agent commit to copy (default HEAD; never the working tree)")
    ap.add_argument("--source", type=Path, default=None, help="the blackbox_agent checkout (default: this script's repo)")
    ap.add_argument("--check", action="store_true", help="only verify tools/bb/ against its VENDOR.json")
    a = ap.parse_args()
    box = Path(a.box).expanduser().resolve()
    if a.check:
        problems = check(box)
        for p in problems:
            print(p, file=sys.stderr)
        if not problems:
            meta = json.loads((box / VENDOR_DIR / "VENDOR.json").read_text())
            print(f"{VENDOR_DIR}: {len(meta['files'])} files match blackbox_agent@{meta['commit'][:7]}")
        return 1 if problems else 0
    meta = vendor(box, (a.source or default_source()).expanduser().resolve(), a.ref)
    print(f"{box.name}/{VENDOR_DIR}: {len(meta['files'])} files, {meta['bytes']:,} bytes, "
          f"blackbox_agent@{meta['commit'][:7]} ({meta['commit_date'][:10]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
