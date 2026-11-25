"""The site bar on every page of site/: one include, one nav.json (blackbox_agent viewer CONTRACT §18, lane SHIP 2026-11-24).

Every page shows the same bar, the viewer's stock <bb-site-nav>, reading the one site/nav.json (bb-site-nav/1): the box's name and its dashboards (Black box,
Trajectory coverage, Trajectory comparison, Model × Dataset), then the open dashboard's own tabs or pages. A page gets it
with one include right after <body>, written by the page's own build (tools/build_coverage.py, tools/build_dropins.py):

    <bb-site-nav src="../nav.json" current="comparison"></bb-site-nav>
    <script type="module" src="../dashboard/viewer/src/components/bb-site-nav.js"></script>

WHY an include, not a frame around the pages (lane NAV prototyped frames): each page stays its own URL, so its deep links
(?deployment=…&dataset=…#tab=…, runs/<task>/report.html#tab=track) survive a reload and are shareable, Back is the
browser's own, and nothing is symlinked (GitHub Pages serves site/ only). Zach's pick, 2026-11-24: lane NAV's 01 Two rows.
The landing page keeps its own bar, with "Open the dashboard →" (proposals-landing 02, his pick).

WHERE the bar's module comes from (2026-11-25, lane PKG): the live site is written by blackbox_agent's `blackbox build`
(.github/workflows/pages.yml calls its site.yml@v0). It serves the stock landing at index.html and the dashboard at
dashboard/, with the viewer (and so bb-site-nav.js) at dashboard/viewer/src/components/: the same path each page's
include names, so the includes are unchanged; the box keeps no copy of either. A link into those two is checked
against the installed package (the `site` extra) instead of site/ (`built`).
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
NAV = SITE / "nav.json"
# Where the built site has the bar's module (blackbox_agent's build: <out>/dashboard/ is its dashboard folder)
BAR_REL = "dashboard/viewer/src/components/bb-site-nav.js"


def _package() -> tuple[Path | None, Path | None]:
    try:
        from blackbox_agent.site import DASHBOARD, TEMPLATE
    except ImportError:  # the `site` extra is not installed: every package-built page reads as missing
        return None, None
    return Path(DASHBOARD), Path(TEMPLATE)


_DASHBOARD, _TEMPLATE = _package()
# The bar's module as the installed package has it (the built site serves this file at BAR_REL)
BAR_JS = _DASHBOARD / "viewer" / "src" / "components" / "bb-site-nav.js" if _DASHBOARD else SITE / BAR_REL
SCHEMA = "bb-site-nav/1"
TAG = re.compile(r"<bb-site-nav\b[^>]*></bb-site-nav>")
SCRIPT = re.compile(r'<script type="module" src="([^"]*bb-site-nav\.js)"></script>')
# the interim bars this one replaced (lane CV's stage bar, lane DROP's header strip): a page must carry none of them
OLD_BARS = re.compile(r"<bb-stages\b|stages/bb-stages\.js|src=\"(?:\.\./)*nav\.js\"|class=\"tta-nav\"")


def _rel(page: Path) -> str:
    rel = os.path.relpath(SITE, page.parent).replace(os.sep, "/")
    return "" if rel == "." else rel + "/"


def tag(page: Path, current: str, *, here: str = "", theme: str = "", page_id: str = "") -> str:
    """The include for the page at `page` (a path under site/): the bar element and its module."""
    rel = _rel(page)
    attrs = [f'src="{rel}nav.json"', f'current="{html.escape(current)}"']
    if page_id:
        attrs.append(f'page="{html.escape(page_id)}"')
    if here:
        attrs.append(f'here="{html.escape(here)}"')
    if theme:
        attrs.append(f'theme="{html.escape(theme)}"')
    return (f"<bb-site-nav {' '.join(attrs)}></bb-site-nav>\n"
            f'<script type="module" src="{rel}dashboard/viewer/src/components/bb-site-nav.js"></script>')


def include(text: str, page: Path, current: str, **kw: str) -> str:
    """`text` with the bar right after <body> (exactly one <body>); a bar already there is replaced, so a re-run is a no-op."""
    text = SCRIPT.sub("", TAG.sub("", text)).replace("<body>\n\n", "<body>\n")
    if text.count("<body>") != 1:
        raise SystemExit(f"{page}: expected exactly one <body>")
    return text.replace("<body>", "<body>\n" + tag(page, current, **kw), 1)


def package_file(path: Path) -> Path | None:
    """The installed package's file that `blackbox build` writes at `path` (a path in site/): the stock landing for
    index.html, the dashboard folder's file for dashboard/...; None for any other path, or without the package."""
    try:
        rel = path.resolve().relative_to(SITE.resolve()).as_posix()
    except ValueError:
        return None
    if rel == "index.html" and _TEMPLATE:
        return _TEMPLATE / "site" / "index.html"
    if (rel == "dashboard" or rel.startswith("dashboard/")) and _DASHBOARD:
        return _DASHBOARD / rel.removeprefix("dashboard").lstrip("/")
    return None


def built(path: Path) -> bool:
    """`path` (in site/) is a file of the built site: one of site/'s own, or one the package's build adds."""
    if path.is_file():
        return True
    provided = package_file(path)
    return bool(provided and provided.is_file())


def _resolves(href: str, base: Path = SITE) -> bool:
    path = (base / href.split("#")[0].split("?")[0]).resolve()
    provided = package_file(path)
    if href.endswith("/") or path.is_dir() or (provided is not None and provided.is_dir()):
        return built(path / "index.html")
    return built(path)


def nav_problems() -> list[str]:
    """site/nav.json: bb-site-nav/1, every dashboard and page href a file of this site, ids unique, order complete."""
    if not NAV.exists():
        return ["site/nav.json is missing"]
    doc = json.loads(NAV.read_text())
    out = [] if doc.get("schema") == SCHEMA else [f"site/nav.json: schema {doc.get('schema')!r}, not {SCHEMA}"]
    ids: set[str] = set()
    for d in doc.get("dashboards", []):
        for item in [d, *d.get("pages", [])]:
            if item["id"] in ids:
                out.append(f"site/nav.json: id {item['id']} twice")
            ids.add(item["id"])
            if not _resolves(item["href"]):
                out.append(f"site/nav.json {item['id']}: {item['href']} is not a page of site/")
    if sorted(doc.get("order", [])) != sorted(d["id"] for d in doc.get("dashboards", [])):
        out.append("site/nav.json: order must name every dashboard once")
    if not _resolves(doc["site"]["landing"]):
        out.append(f"site/nav.json: the landing {doc['site']['landing']} is not a page of site/")
    return out


def page_problems(pages: list[Path]) -> list[str]:
    """Each page: exactly one bar, reading site/nav.json, its module the built site's bb-site-nav.js (BAR_REL, which the
    installed package must have), `current` a dashboard; none of the interim bars."""
    doc = json.loads(NAV.read_text()) if NAV.exists() else {"dashboards": []}
    dashboards = {d["id"] for d in doc["dashboards"]}
    out = [] if BAR_JS.is_file() else [f"{BAR_REL}: the installed blackbox_agent has no such file (uv sync --all-extras)"]
    for page in pages:
        text = page.read_text(errors="replace")
        name = page.relative_to(REPO)
        tags, scripts = TAG.findall(text), SCRIPT.findall(text)
        if len(tags) != 1 or len(scripts) != 1:
            out.append(f"{name}: {len(tags)} bars and {len(scripts)} bar modules (one each)")
            continue
        src = re.search(r'src="([^"]+)"', tags[0]).group(1)
        current = re.search(r'current="([^"]+)"', tags[0])
        if (page.parent / src).resolve() != NAV.resolve():
            out.append(f"{name}: its bar reads {src}, not site/nav.json")
        if (page.parent / scripts[0]).resolve() != (SITE / BAR_REL).resolve():
            out.append(f"{name}: its bar module is {scripts[0]}, not the built site's {BAR_REL}")
        if not current or current.group(1) not in dashboards:
            out.append(f"{name}: current={current and current.group(1)!r} is not a dashboard in site/nav.json")
        if OLD_BARS.search(text):
            out.append(f"{name}: still carries an interim bar (bb-stages or nav.js)")
    return out
