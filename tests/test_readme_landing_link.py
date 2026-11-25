"""The README's first line under the title links the live landing page (Zach, 2026-11-24: "on the first line on the
readme should link to the github page that is hosting the latest version of the landing page"), and the format it
follows (the blackbox_agent template, template/tests/test_readme_landing_link.py)."""

from __future__ import annotations

from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"
PAGES = "https://zacharyyamaoka.github.io/trajectory_tracking_agent/"
TEMPLATE = "https://github.com/zacharyyamaoka/blackbox_agent"


def test_the_first_line_links_the_live_landing_page_and_the_template() -> None:
    lines = [line for line in README.read_text().splitlines() if line.strip()]
    assert lines[0].startswith("# "), lines[0]
    first = lines[1]
    assert f"]({PAGES})" in first, first
    assert f"]({TEMPLATE})" in first, first
