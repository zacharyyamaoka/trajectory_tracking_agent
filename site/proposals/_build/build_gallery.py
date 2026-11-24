"""Build ../index.html (the comparison and pick page) and make it safe to publish.

    uv run python site/proposals/_build/build_gallery.py --gallery <path to the babble skill's scripts/gallery.py>

1. writes the spec from gallery_spec.py and builds it with the babble skill's gallery.py (deck shell);
2. rewords the deck shell's code comments that cite a private repo (WHY: site/ is public; lane W's
   tests/test_site_static.py::test_no_private_paths_or_personal_data_in_site);
3. runs that test, so the build fails if anything private is left.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROPOSALS = HERE.parent
sys.path.insert(0, str(HERE))

REWORD = [
    # matched by the shape "<repo> docs/babble_report_deck…", so this file names no private repo either
    (re.compile(r"\([\w-]+ docs/babble_report_deck/formats/[\w.-]+:"), "(an earlier internal report's splice format:"),
    (re.compile(r"\([\w-]+ docs/babble_report_deck\)"), "(ported from an earlier internal report's diff lens)"),
    (re.compile(r"in [\w-]+ docs/babble_report_deck"), "of an earlier internal report"),
]


def leaks() -> int:
    """Lane W's own check, so the pattern lives in one place (tests/test_site_static.py)."""
    test = "tests/test_site_static.py::test_no_private_paths_or_personal_data_in_site"
    return subprocess.run(["uv", "run", "--all-extras", "pytest", "-q", test], cwd=PROPOSALS.parent.parent).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gallery", type=Path, required=True, help="the babble skill's scripts/gallery.py")
    args = parser.parse_args()
    import gallery_spec

    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "spec.json"
        out = subprocess.run([sys.executable, str(HERE / "gallery_spec.py")], capture_output=True, text=True, check=True)
        spec.write_text(out.stdout)
        json.loads(out.stdout)
        index = PROPOSALS / "index.html"
        if index.exists():
            index.unlink()
        subprocess.run([sys.executable, str(args.gallery), "build", "--spec", str(spec), "--output", str(index)], check=True)
    text = index.read_text()
    for pattern, replacement in REWORD:
        text = pattern.sub(replacement, text)
    index.write_text(text)
    subprocess.run([sys.executable, str(args.gallery), "check", "--input", str(index), "--strict"], check=True)
    if leaks():
        print("private paths or personal data left in site/ (see the test output above)", file=sys.stderr)
        return 1
    print(f"index.html built and clean · {len(gallery_spec.V)} variants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
