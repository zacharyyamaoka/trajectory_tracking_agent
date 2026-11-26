"""Drive the Trajectory Comparison and Model × Dataset pages in headless Chromium (never a visible window) and keep the
evidence.

    uv run --no-project --with playwright==1.64.1 python tools/shoot_dropins.py --out <dir> [--site <built site>]

It serves the site itself (python's http.server on a free 127.0.0.1 port, stopped by its pid when done): site/ by
default, or `--site`, a folder `blackbox build --box . --out <folder>` wrote (the live page's files: there the site bar
and the landing page are there too). Checks, each written to <dir>/results.json: light, dark and a 390 px phone on every
page with no sideways scroll (measured: the document's scrollWidth against the viewport) and no console error, page
error, failed request or 4xx/5xx (the bar's module and the landing page only count against a built site); the site
bar draws on every page of a built site; Model × Dataset opens on its Leaderboard with the tabs Leaderboard, Pivot,
Rows; in the Pivot each solution's dev cell (data-ui's `data-value`, unrounded) is its objective; a task cell's click
lands on its run's report (the deep link) and the report's question tab switches. Then the hero clip: Model × Dataset's
Leaderboard -> unfold a family -> the Pivot -> click a task's cell -> its Comparison report -> switch question tab,
recorded to <dir>/hero.webm (+ .mp4 and .gif when ffmpeg is there).
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
PAGES = (("models-datasets", "models-datasets/index.html"), ("comparison", "comparison/index.html"),
         ("comparison-target", "comparison/index.html#/target/workspace-dev-016"),
         ("comparison-run", "comparison/runs/workspace-dev-016/report.html#tab=track"))
LOOKS = (("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844))
# WHY read, not named: the solution the Comparison ships on every task moves with each new best (p5s-pass3 left it
# for p5s-damping185-refit on 2026-11-25, and its cell then opened the landing player instead)
HERO_SOLUTION = json.loads((SITE / "data" / "runs" / "index.json").read_text())["rule"]["full"]["best"]
HERO_TASK = "workspace-dev-016"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def watch(page, sink: list) -> None:
    page.on("console", lambda m: sink.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: sink.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: sink.append(f"requestfailed: {r.url}"))
    page.on("response", lambda r: sink.append(f"{r.status}: {r.url}") if r.status >= 400 else None)


def settle(page, ms: int = 2500) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def sideways(page) -> int:
    """How far the page scrolls sideways (px): the document's scroll width past the viewport's."""
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def leaf_key(solution: str) -> str:
    """The end of a leaf row's key (family › model › config, CONTRACT §57), as tools/build_dropins.py names a solution."""
    return f" › {solution.split('-')[0]} › {solution.split('-', 1)[1] if '-' in solution else 'as built'}"


def task_cell(page, solution: str, task: str):
    """The pivot cell of one solution on one task in ruler v1's dev column (data-ui marks a cell with its column's id: '@'
    + its path, ' / '); the off-ruler speed columns hold the same task, so the column's start is named too."""
    short = task.replace("workspace-", "", 1)
    return (page.locator(f"data-views tr[data-row-key$='{leaf_key(solution)}']").first
            .locator(f'td[data-col^="@ur5e_alone · dev / "][data-col$="/ {short}"]'))


def dev_value(page, solution: str) -> str | None:
    """The unrounded number data-ui draws in a solution's dev-deployment column (its `data-value`)."""
    td = page.locator(f"data-views tr[data-row-key$='{leaf_key(solution)}']").first.locator('td[data-col="@ur5e_alone · dev"]')
    return td.get_attribute("data-value") if td.count() else None


def selected_tabs(page) -> list[str]:
    return page.evaluate("[...document.querySelectorAll('data-views [role=tab][aria-selected=true]')].map(t => t.textContent.trim())")


def open_view(page, name: str) -> None:
    if selected_tabs(page) != [name]:
        page.get_by_role("tab", name=name, exact=True).click()
        page.wait_for_timeout(1500)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--site", type=Path, default=SITE, help="the folder to serve (default site/; or a blackbox build)")
    args = parser.parse_args()
    out = args.out
    built = args.site.resolve() != SITE.resolve()
    out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                               "--directory", str(args.site)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/"
    results: dict = {"base": f"{'a blackbox build' if built else 'site/'} on a local http.server", "looks": [], "strip": {},
                     "views": {}, "rollup": {}, "deep_link": {}, "hero": {}}
    # WHY: site/ alone has neither the bar's module nor the landing page (blackbox build writes both), so a 404 for them
    # counts only against a built site
    only_built = ("/dashboard/viewer/", "/index.html?run=")
    objectives = {sid: json.loads((REPO / "solutions" / sid / "scorecard.json").read_text())["objective"]
                  for sid in ("p5s-pass3", "p6s")}
    try:
        time.sleep(0.5)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            # 1. every page in every look
            for scheme, width, height in LOOKS:
                context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
                for name, path in PAGES:
                    page = context.new_page()
                    problems: list[str] = []
                    watch(page, problems)
                    page.goto(base + path)
                    settle(page)
                    shot = out / f"{name}-{scheme}-{width}.png"
                    page.screenshot(path=str(shot))
                    strip = page.evaluate("(() => { const n = document.querySelector('bb-site-nav'); return n && n.innerText.replace(/\\s+/g, ' ').trim(); })()")
                    results["strip"].setdefault(name, strip)
                    if not built:
                        problems = [p for p in problems if not any(k in p for k in only_built) and "Failed to load resource" not in p]
                    results["looks"].append({"page": name, "scheme": scheme, "width": width, "sideways_px": sideways(page),
                                             "problems": problems, "shot": shot.name, "strip": bool(strip) or not built})
                    page.close()
                context.close()

            # 2. the views, the roll-up (each solution's dev cell is its objective) and a task cell's deep link
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            problems = []
            watch(page, problems)
            page.goto(base + "models-datasets/index.html")
            settle(page)
            tabs = page.evaluate("[...document.querySelectorAll('data-views [role=tab]')].map(t => t.textContent.trim())")
            results["views"] = {"tabs": tabs, "default": selected_tabs(page),
                                "ok": tabs[:3] == ["Leaderboard", "Pivot", "Rows"] and selected_tabs(page) == ["Leaderboard"]}
            page.screenshot(path=str(out / "models-datasets-leaderboard.png"))
            open_view(page, "Pivot")
            for sid, objective in objectives.items():
                shown = dev_value(page, sid)
                results["rollup"][sid] = {"shown": shown, "objective": repr(objective), "ok": shown == repr(objective)}
            page.screenshot(path=str(out / "models-datasets-pivot.png"))
            target = task_cell(page, HERO_SOLUTION, HERO_TASK)
            target.scroll_into_view_if_needed()
            value = target.get_attribute("data-value")
            target.click()
            page.wait_for_url("**/comparison/runs/**", timeout=10000)
            settle(page, 2000)
            landed = page.url.replace(base, "")
            page.get_by_role("tab", name="Where is the error?").click()
            page.wait_for_timeout(800)
            active = page.evaluate("(() => { const t = document.querySelector('[data-tc-tab][aria-selected=\"true\"]'); return t && t.dataset.tcTab; })()")
            table = page.evaluate("[...document.querySelectorAll('table')].map(t => t.innerText).find(x => x.includes('Tool tracking RMS (moving samples)')) || ''")
            if not built:
                problems = [p for p in problems if not any(k in p for k in only_built) and "Failed to load resource" not in p]
            results["deep_link"] = {"cell": value, "landed": landed, "tab_after_click": active, "problems": problems,
                                    "ok": landed == f"comparison/runs/{HERO_TASK}/report.html#tab=track&run={HERO_SOLUTION}"
                                    and active == "where", "table_names_best": HERO_SOLUTION in table}
            context.close()

            # 3. the hero clip: Model × Dataset -> a cell -> its Comparison report -> switch question tab
            context = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(out / "video"),
                                          record_video_size={"width": 1280, "height": 800})
            page = context.new_page()
            problems = []
            watch(page, problems)
            page.goto(base + "models-datasets/index.html")
            settle(page, 1800)
            family = page.locator("data-views tr[data-row-key] button[aria-expanded]").first
            family.click()
            page.wait_for_timeout(1500)
            open_view(page, "Pivot")
            target = task_cell(page, HERO_SOLUTION, HERO_TASK)
            target.scroll_into_view_if_needed()
            target.hover()
            page.wait_for_timeout(900)
            target.click()
            page.wait_for_url("**/comparison/runs/**", timeout=10000)
            settle(page, 2200)
            page.get_by_role("tab", name="Where is the error?").click()
            page.wait_for_timeout(2200)
            page.get_by_role("tab", name="Which joint has the error?").click()
            page.wait_for_timeout(1800)
            video = page.video.path()
            context.close()
            hero = out / "hero.webm"
            shutil.move(video, hero)
            shutil.rmtree(out / "video", ignore_errors=True)
            if not built:
                problems = [p for p in problems if not any(k in p for k in only_built) and "Failed to load resource" not in p]
            results["hero"] = {"webm": hero.name, "problems": problems}
            if shutil.which("ffmpeg"):
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(hero), "-c:v", "libx264", "-pix_fmt",
                                "yuv420p", "-an", "-movflags", "+faststart", str(out / "hero.mp4")], check=True)
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(hero), "-vf",
                                "fps=8,scale=800:-1:flags=lanczos", str(out / "hero.gif")], check=True)
                results["hero"].update({"mp4": "hero.mp4", "gif": "hero.gif"})
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    looks_ok = all(look["sideways_px"] <= 0 and not look["problems"] and look["strip"] for look in results["looks"])
    results["ok"] = bool(looks_ok and results["views"].get("ok") and results["deep_link"].get("ok")
                         and all(r["ok"] for r in results["rollup"].values()) and not results["hero"].get("problems"))
    (out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: results[k] for k in ("views", "rollup", "deep_link", "ok")}, indent=1, ensure_ascii=False))
    for look in results["looks"]:
        if look["sideways_px"] > 0 or look["problems"] or not look["strip"]:
            print("PROBLEM", look)
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
