"""Drive the Trajectory Comparison and Model × Dataset pages in headless Chromium (never a visible window) and keep the
evidence.

    uv run --no-project --with playwright==1.64.1 python tools/shoot_dropins.py --out <dir>

It serves site/ itself (python's http.server on a free 127.0.0.1 port, stopped by its pid when done). Checks, each
written to <dir>/results.json: light, dark and a 390 px phone on every page with no sideways scroll (measured:
the document's scrollWidth against the viewport) and no console error, page error, failed request or 4xx/5xx; the
header strip draws on every page; Model × Dataset's Per dataset (median) cell for each solution reads its objective; a
per-task cell's click lands on its run's report (the deep link) and the report's question tab switches. Then the hero
clip: Model × Dataset -> click a cell -> its Comparison report -> switch question tab, recorded to <dir>/hero.webm
(+ .mp4 and .gif when ffmpeg is there).
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
HERO_SOLUTION = "p5s-pass3"
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


def cell(page, solution: str, column: int):
    return page.locator("data-views tbody tr", has_text=solution).first.locator("td").nth(column)


def task_cell(page, solution: str, task: str):
    """The pivot cell of one solution on one task (data-ui marks a cell with its column's id)."""
    return page.locator("data-views tbody tr", has_text=solution).first.locator(f'td[data-col$="/ {task}"]')


def number(locator) -> str:
    """A pivot cell's number as drawn, without its record count."""
    return locator.evaluate("(td) => { const c = td.cloneNode(true); c.querySelectorAll('.dv-n').forEach((n) => n.remove()); return c.textContent.trim(); }")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                               "--directory", str(SITE)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/"
    results: dict = {"base": "site/ on a local http.server", "looks": [], "strip": {}, "rollup": {}, "deep_link": {},
                     "hero": {}}
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
                    strip = page.evaluate("(() => { const n = document.querySelector('[data-tta-nav]'); return n && n.innerText.replace(/\\s+/g, ' ').trim(); })()")
                    results["strip"].setdefault(name, strip)
                    results["looks"].append({"page": name, "scheme": scheme, "width": width, "sideways_px": sideways(page),
                                             "problems": problems, "shot": shot.name, "strip": bool(strip)})
                    page.close()
                context.close()

            # 2. the roll-up: Per dataset (median) reads each solution's objective; a per-task cell opens its run
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            problems = []
            watch(page, problems)
            page.goto(base + "models-datasets/index.html")
            settle(page)
            page.get_by_role("tab", name="Per dataset (median)").click()
            page.wait_for_timeout(1500)
            for sid, objective in objectives.items():
                shown = number(cell(page, sid, 2))
                results["rollup"][sid] = {"shown": shown, "objective": objective, "ok": shown == f"{objective:.3g}"}
            page.screenshot(path=str(out / "models-datasets-per-dataset.png"))
            page.get_by_role("tab", name="Per task", exact=True).click()
            page.wait_for_timeout(1500)
            value = number(task_cell(page, HERO_SOLUTION, HERO_TASK))
            task_cell(page, HERO_SOLUTION, HERO_TASK).click()
            page.wait_for_url("**/comparison/runs/**", timeout=10000)
            settle(page, 2000)
            landed = page.url.replace(base, "")
            page.get_by_role("tab", name="Where is the error?").click()
            page.wait_for_timeout(800)
            active = page.evaluate("(() => { const t = document.querySelector('[data-tc-tab][aria-selected=\"true\"]'); return t && t.dataset.tcTab; })()")
            table = page.evaluate("[...document.querySelectorAll('table')].map(t => t.innerText).find(x => x.includes('Tool tracking RMS (moving samples)')) || ''")
            results["deep_link"] = {"cell": value, "landed": landed, "tab_after_click": active, "problems": problems,
                                    "ok": landed == f"comparison/runs/{HERO_TASK}/report.html#tab=track" and active == "where",
                                    "table_names_best": HERO_SOLUTION in table}
            context.close()

            # 3. the hero clip: Model × Dataset -> a cell -> its Comparison report -> switch question tab
            context = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(out / "video"),
                                          record_video_size={"width": 1280, "height": 800})
            page = context.new_page()
            problems = []
            watch(page, problems)
            page.goto(base + "models-datasets/index.html")
            settle(page, 1800)
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
    results["ok"] = bool(looks_ok and results["deep_link"].get("ok") and all(r["ok"] for r in results["rollup"].values())
                         and not results["hero"].get("problems"))
    (out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: results[k] for k in ("rollup", "deep_link", "ok")}, indent=1, ensure_ascii=False))
    for look in results["looks"]:
        if look["sideways_px"] > 0 or look["problems"] or not look["strip"]:
            print("PROBLEM", look)
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
