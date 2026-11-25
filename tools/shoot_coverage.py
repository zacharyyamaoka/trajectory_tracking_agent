"""Drive the Deployments and Datasets pages in headless Chromium (never a visible window) and keep the evidence.

    uv run --no-project --with playwright==1.64.1 python tools/shoot_coverage.py --base http://127.0.0.1:<port>/ --out <dir>

Serve site/ first (any static server; for Open in Rerun, `tools/build_coverage.py local` and traj_compare.serve). Checks,
each written to <dir>/results.json: light, dark and a 390 px phone on every page with no sideways scroll (measured) and
no console error or failed request; the stage bar draws the same text on every page; a gallery card's click lands on the
Datasets page filtered to it (the corner count and the pill); deep links (?split=holdout, a deferred deployment's notice,
#tab=); then the hero clip: Deployments -> a deployment -> its filtered workbench -> a trajectory -> Open in Rerun (or
the static page's record actions), recorded to <dir>/hero.webm (+ .mp4 and .gif when ffmpeg is there).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = (("deployments-gallery", "deployments/"), ("deployments-table", "deployments/#view=table"),
         ("datasets", "datasets/ur5e/?deployment=ur5e_alone&dataset=ur5e_alone/workspace/v2"))
LOOKS = (("light", 1440, 900), ("dark", 1440, 900), ("light", 390, 844), ("dark", 390, 844))


def watch(page, sink: list) -> None:
    page.on("console", lambda m: sink.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: sink.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: sink.append(f"requestfailed: {r.url}"))
    page.on("response", lambda r: sink.append(f"{r.status}: {r.url}") if r.status >= 400 else None)


def settle(page, ms: int = 2500) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    base = args.base.rstrip("/") + "/"
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    results: dict = {"looks": [], "stage_bar": {}, "click": {}, "deep_links": {}, "hero": {}}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        # 1. every page in every look: sideways scroll, errors, a screenshot
        for scheme, width, height in LOOKS:
            context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
            page = context.new_page()
            problems: list[str] = []
            watch(page, problems)
            for name, path in PAGES:
                page.goto(base + path)
                if name == "deployments-table":
                    page.get_by_text("Table", exact=True).first.click()
                settle(page)
                box = page.evaluate("() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})")
                page.screenshot(path=out / f"{name}-{scheme}-{width}.png")
                bar = page.evaluate("() => document.querySelector('bb-stages')?.innerText.replace(/\\s+/g, ' ').trim()")
                results["stage_bar"].setdefault(bar, []).append(f"{name}-{scheme}-{width}")
                results["looks"].append({"page": name, "scheme": scheme, "width": width, "scroll_width": box["scroll"],
                                         "client_width": box["client"], "sideways": box["scroll"] > box["client"]})
            results["looks"][-1]["problems"] = problems
            results.setdefault("problems", {})[f"{scheme}-{width}"] = problems
            context.close()

        # 2. a gallery card's click lands filtered; deep links
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        problems = []
        watch(page, problems)
        page.goto(base + "deployments/")
        settle(page, 1500)
        page.locator('[data-id="deployment:ur5e_alone"]').first.click()
        settle(page)
        results["click"] = {"url": page.url.replace(base, ""),
                            "count": page.locator("data-count").first.inner_text(),
                            "pills": page.locator("data-pills").first.inner_text().replace("\n", " ")}
        for name, path in (("holdout", "datasets/ur5e/?split=holdout"),
                           ("deferred", "datasets/ur5e/?deployment=ur5e"),
                           ("tab", "datasets/ur5e/?deployment=ur5e_alone#tab=tool-position")):
            page.goto(base + path)
            settle(page)
            notice = page.locator("#link-notice")
            results["deep_links"][name] = {
                "count": page.locator("data-count").first.inner_text(),
                "notice": notice.inner_text() if notice.is_visible() else None,
                "tab": page.evaluate("() => document.querySelector('[role=tab][aria-selected=true]')?.textContent.trim()"),
            }
            page.screenshot(path=out / f"deep-{name}.png")
        results["problems"]["click-and-links"] = problems
        context.close()

        # 3. the hero clip
        context = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(out / "video"),
                                      record_video_size={"width": 1280, "height": 800})
        page = context.new_page()
        problems = []
        watch(page, problems)
        page.goto(base + "deployments/")
        settle(page, 1200)
        card = page.locator('[data-id="deployment:ur5e_alone"]').first
        card.hover()
        page.wait_for_timeout(700)
        card.click()
        settle(page, 1800)
        page.get_by_role("tab", name="Trajectories").first.click()
        page.wait_for_timeout(1000)
        page.locator("data-workbench tbody tr").nth(2).click()
        page.wait_for_timeout(1200)
        actions = page.locator("[data-drill-action]")
        labels = [actions.nth(i).inner_text() for i in range(actions.count())]
        pressed = next((label for label in ("Open in Rerun", "Open in the Rerun web viewer") if label in labels), None)
        status = None
        if pressed == "Open in Rerun":
            page.get_by_role("button", name="Open in Rerun").click()
            page.wait_for_timeout(1800)
            status = page.locator(".ds-act-status").first.inner_text()
        else:
            page.wait_for_timeout(1500)
        page.screenshot(path=out / "hero-last.png")
        results["hero"] = {"actions": labels, "pressed": pressed, "status": status}
        results["problems"]["hero"] = problems
        video = page.video.path()
        context.close()
        browser.close()

    Path(video).replace(out / "hero.webm")
    shutil.rmtree(out / "video", ignore_errors=True)
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out / "hero.webm"), "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out / "hero.mp4")], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out / "hero.webm"), "-vf",
                        "fps=8,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
                        str(out / "hero.gif")], check=True)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(out / "hero.mp4")], capture_output=True, text=True)
        results["hero"]["seconds"] = float(probe.stdout.strip() or 0)
    results["ok"] = (not any(look["sideways"] for look in results["looks"])
                     and not any(results["problems"].values()) and len(results["stage_bar"]) == 1)
    (out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: results[k] for k in ("ok", "click", "deep_links", "hero")}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
