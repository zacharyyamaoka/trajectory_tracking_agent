"""The built-in tracker: every solution tried, in creation order, against the objective (like evo's / autoresearch's chart).

    uv run python tools/progress_chart.py         # or `tta progress`: site/progress.svg + outputs/progress.png

- x = the solution's number in creation order (`meta.json` `created`), y = its newest dev `tool_track_rms_mm` (mm; a log
  axis when the values span more than 20x).
- an orange step line = the best so far over admissible solutions; a green filled dot = a new best; a grey dot =
  admissible but not a new best; a red hollow dot = not admissible (hover: how many gates fail, on how many tasks).
  A solution with no objective (it crashed) sits on the top edge as a red hollow dot.
- the best solution's holdout score (reporting only) is a light diamond beside its dev dot, joined by a dashed line.

Hand-written SVG, no external fonts or scripts, explicit neutral greys so it reads on light and dark pages, < 60 KB.
"""

from __future__ import annotations

import math
import sys
from html import escape
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = REPO_ROOT / "site" / "progress.svg"
PNG_PATH = REPO_ROOT / "outputs" / "progress.png"

WIDTH, HEIGHT = 760, 360
LEFT, RIGHT, TOP, BOTTOM = 64, 24, 46, 52
AXIS = "#8c8c8c"  # mid grey: readable on white and on GitHub's dark background
GRID = "#8c8c8c"
TEXT = "#8c8c8c"
ORANGE = "#f28c28"
GREEN = "#2ca02c"
GREY = "#9e9e9e"
RED = "#d62728"
HOLDOUT = "#6aa9e9"
FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
LOG_RANGE = 20.0


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0.0 else None


def chart_points() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """One point per scored solution in creation order, and the best one's holdout row (or None)."""
    from trajectory_tracking_agent import ledger, population

    dev = ledger.latest("dev")
    holdout = ledger.latest("holdout")
    points = []
    number = 0
    best_so_far = math.inf
    for solution in population.ids_in_creation_order():
        number += 1
        row = dev.get(solution)
        if row is None:
            continue
        objective = _finite(row.get("objective"))
        admissible = row.get("admissible") is True and objective is not None
        new_best = admissible and objective < best_so_far
        if new_best:
            best_so_far = objective
        failed = {g: int(n) for g, n in (row.get("failed_gates") or {}).items() if n}
        points.append({"solution": solution, "x": number, "y": objective, "admissible": admissible, "new_best": new_best,
                       "best_so_far": best_so_far if math.isfinite(best_so_far) else None, "failed": failed})
    top = ledger.best()
    held = holdout.get(top["solution"]) if top else None
    pair = None
    if top and held and _finite(held.get("objective")) is not None:
        pair = {"solution": top["solution"], "dev": _finite(top["objective"]), "holdout": _finite(held["objective"]),
                "x": next((p["x"] for p in points if p["solution"] == top["solution"]), None)}
    return points, pair


def _ticks_log(low: float, high: float) -> list[float]:
    out = []
    for exponent in range(math.floor(math.log10(low)), math.ceil(math.log10(high)) + 1):
        for mantissa in (1, 2, 5):
            value = mantissa * 10.0**exponent
            if low <= value <= high:
                out.append(value)
    return out


def _ticks_linear(low: float, high: float) -> list[float]:
    span = high - low
    step = 10.0 ** math.floor(math.log10(span / 4.0)) if span > 0 else 1.0
    for factor in (1, 2, 5, 10):
        if span / (step * factor) <= 6:
            step *= factor
            break
    first = math.ceil(low / step) * step
    return [first + k * step for k in range(int((high - first) / step + 1e-9) + 1)]


def _label(value: float) -> str:
    return f"{value:g}" if value >= 0.01 else f"{value:.0e}"


def render_svg(points: list[dict[str, Any]], pair: dict[str, Any] | None) -> str:
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM
    values = [p["y"] for p in points if p["y"] is not None] + ([pair["holdout"]] if pair else [])
    admissible = [p for p in points if p["admissible"]]
    best = min((p["y"] for p in admissible), default=None)
    title = (f"Trajectory Tracking Agent · {len(points)} solutions · {len(admissible)} admissible · best "
             + (f"{best:.3f} mm" if best is not None else "none yet"))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
             f'font-family="{FONT}" font-size="12" role="img" aria-label="{escape(title)}">',
             f"<title>{escape(title)}</title>",
             f'<text x="{LEFT}" y="20" fill="{TEXT}" font-size="14" font-weight="600">{escape(title)}</text>']
    if not values:
        parts.append(f'<text x="{WIDTH / 2}" y="{HEIGHT / 2}" fill="{TEXT}" text-anchor="middle">No solutions scored yet: '
                     "tta evaluate &lt;id&gt;</text></svg>")
        return "\n".join(parts)
    low, high = min(values), max(values)
    use_log = high / low > LOG_RANGE
    if use_log:
        low, high = 10 ** (math.log10(low) - 0.08), 10 ** (math.log10(high) + 0.08)
        ticks = _ticks_log(low, high)

        def y_of(value: float) -> float:
            return TOP + plot_h * (1 - (math.log10(value) - math.log10(low)) / (math.log10(high) - math.log10(low)))
    else:
        pad = 0.08 * (high - low) if high > low else 0.1 * high
        low, high = max(0.0, low - pad), high + pad
        ticks = _ticks_linear(low, high)

        def y_of(value: float) -> float:
            return TOP + plot_h * (1 - (value - low) / (high - low))

    count = max(p["x"] for p in points)

    def x_of(number: float) -> float:
        return LEFT + plot_w * ((number - 0.5) / count)

    # axes, grid, ticks
    parts.append(f'<g stroke="{GRID}" stroke-opacity="0.25" stroke-width="1">')
    for value in ticks:
        parts.append(f'<line x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y_of(value):.1f}" y2="{y_of(value):.1f}"/>')
    parts.append("</g>")
    parts.append(f'<g fill="{TEXT}" text-anchor="end">')
    for value in ticks:
        parts.append(f'<text x="{LEFT - 6}" y="{y_of(value) + 4:.1f}">{_label(value)}</text>')
    parts.append("</g>")
    parts.append(f'<g stroke="{AXIS}" stroke-width="1"><line x1="{LEFT}" x2="{LEFT}" y1="{TOP}" y2="{TOP + plot_h}"/>'
                 f'<line x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{TOP + plot_h}" y2="{TOP + plot_h}"/></g>')
    step = max(1, math.ceil(count / 20))
    parts.append(f'<g fill="{TEXT}" text-anchor="middle">')
    for number in range(1, count + 1, step):
        parts.append(f'<text x="{x_of(number):.1f}" y="{TOP + plot_h + 16}">{number}</text>')
    parts.append("</g>")
    parts.append(f'<text x="{LEFT + plot_w / 2}" y="{HEIGHT - 10}" fill="{TEXT}" text-anchor="middle">solution number '
                 "(creation order)</text>")
    parts.append(f'<text transform="translate(16 {TOP + plot_h / 2}) rotate(-90)" fill="{TEXT}" text-anchor="middle">'
                 f"tool_track_rms_mm (dev, mm{', log' if use_log else ''})</text>")

    # best so far: a step line over the admissible solutions, carried to the last solution
    path = []
    current = None
    for p in points:
        if p["new_best"]:
            if current is None:
                path.append(f"M{x_of(p['x']):.1f},{y_of(p['y']):.1f}")
            else:
                path.append(f"H{x_of(p['x']):.1f}V{y_of(p['y']):.1f}")
            current = p["y"]
    if current is not None:
        path.append(f"H{x_of(count + 0.5):.1f}")
        parts.append(f'<path d="{"".join(path)}" fill="none" stroke="{ORANGE}" stroke-width="2"/>')

    # the best solution's holdout beside its dev dot
    if pair and pair["x"] is not None:
        x = x_of(pair["x"]) + 10
        parts.append(f'<g><title>{escape(pair["solution"])}: dev {pair["dev"]:.3f} mm, holdout {pair["holdout"]:.3f} mm '
                     f"(reporting only)</title>"
                     f'<line x1="{x_of(pair["x"]):.1f}" y1="{y_of(pair["dev"]):.1f}" x2="{x:.1f}" y2="{y_of(pair["holdout"]):.1f}" '
                     f'stroke="{HOLDOUT}" stroke-width="1.2" stroke-dasharray="3 2"/>'
                     f'<path d="M{x:.1f},{y_of(pair["holdout"]) - 5:.1f}l5,5l-5,5l-5,-5z" fill="{HOLDOUT}" fill-opacity="0.55"/>'
                     f'<text x="{x + 8:.1f}" y="{y_of(pair["holdout"]) + 4:.1f}" fill="{HOLDOUT}">holdout</text></g>')

    # the dots
    for p in points:
        x = x_of(p["x"])
        if p["y"] is None:
            y, value = TOP + 4, "no objective"
        else:
            y, value = y_of(p["y"]), f"{p['y']:.3f} mm"
        if p["admissible"]:
            state = "new best" if p["new_best"] else "admissible"
            tip = f"#{p['x']} {p['solution']}: {value}, {state}"
            fill, stroke, radius = (GREEN, GREEN, 5.5) if p["new_best"] else (GREY, GREY, 4.5)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{fill}" stroke="{stroke}">'
                         f"<title>{escape(tip)}</title></circle>")
        else:
            gates = len(p["failed"])
            detail = ", ".join(f"{g} on {n} task{'s' if n != 1 else ''}" for g, n in p["failed"].items()) or "no objective"
            tip = f"#{p['x']} {p['solution']}: {value}, not admissible: {gates} gate{'s' if gates != 1 else ''} failed ({detail})"
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="none" stroke="{RED}" stroke-width="1.6">'
                         f"<title>{escape(tip)}</title></circle>")
        if p["new_best"] or (best is not None and p["y"] == best):
            parts.append(f'<text x="{x:.1f}" y="{y - 9:.1f}" fill="{TEXT}" text-anchor="middle" font-size="11">'
                         f"{escape(p['solution'])}</text>")

    # legend
    legend_y = 34
    items = [("line", ORANGE, "best so far"), ("dot", GREEN, "new best"), ("dot", GREY, "admissible"),
             ("ring", RED, "not admissible"), ("diamond", HOLDOUT, "best on holdout")]
    x = WIDTH - RIGHT - 470
    for kind, colour, text in items:
        if kind == "line":
            parts.append(f'<line x1="{x}" x2="{x + 16}" y1="{legend_y - 4}" y2="{legend_y - 4}" stroke="{colour}" stroke-width="2"/>')
        elif kind == "dot":
            parts.append(f'<circle cx="{x + 8}" cy="{legend_y - 4}" r="4.5" fill="{colour}"/>')
        elif kind == "ring":
            parts.append(f'<circle cx="{x + 8}" cy="{legend_y - 4}" r="4.5" fill="none" stroke="{colour}" stroke-width="1.6"/>')
        else:
            parts.append(f'<path d="M{x + 8},{legend_y - 9}l5,5l-5,5l-5,-5z" fill="{colour}" fill-opacity="0.55"/>')
        parts.append(f'<text x="{x + 20}" y="{legend_y}" fill="{TEXT}" font-size="11">{text}</text>')
        x += 20 + 7 * len(text) + 14
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_png(points: list[dict[str, Any]], pair: dict[str, Any] | None, path: Path) -> Path | None:
    """The same chart through matplotlib (for previews; outputs/ is gitignored). None when matplotlib is missing."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    values = [p["y"] for p in points if p["y"] is not None]
    figure, axes = plt.subplots(figsize=(7.6, 3.6), dpi=150)
    if values:
        top = max(values) * (1.3 if max(values) / min(values) > LOG_RANGE else 1.08)
        if max(values) / min(values) > LOG_RANGE:
            axes.set_yscale("log")
        steps_x, steps_y = [], []
        for p in points:
            if p["new_best"]:
                if steps_x:
                    steps_x.append(p["x"])
                    steps_y.append(steps_y[-1])
                steps_x.append(p["x"])
                steps_y.append(p["y"])
        if steps_x:
            steps_x.append(max(p["x"] for p in points) + 0.5)
            steps_y.append(steps_y[-1])
            axes.plot(steps_x, steps_y, color=ORANGE, lw=2, label="best so far")
        for p in points:
            y = p["y"] if p["y"] is not None else top
            if p["admissible"]:
                axes.plot(p["x"], y, "o", color=GREEN if p["new_best"] else GREY, ms=7 if p["new_best"] else 6)
            else:
                axes.plot(p["x"], y, "o", mfc="none", mec=RED, mew=1.5, ms=6)
            if p["new_best"]:
                axes.annotate(p["solution"], (p["x"], y), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=7)
        if pair and pair["x"] is not None:
            axes.plot([pair["x"], pair["x"] + 0.25], [pair["dev"], pair["holdout"]], "--", color=HOLDOUT, lw=1)
            axes.plot(pair["x"] + 0.25, pair["holdout"], "D", color=HOLDOUT, alpha=0.6, ms=6)
    axes.set_xlabel("solution number (creation order)")
    axes.set_ylabel("tool_track_rms_mm (dev, mm)")
    axes.grid(alpha=0.25)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path)
    plt.close(figure)
    return path


def write_chart(svg_path: Path = SVG_PATH, png_path: Path | None = PNG_PATH) -> list[Path]:
    points, pair = chart_points()
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(render_svg(points, pair))
    written = [svg_path]
    if png_path is not None:
        png = render_png(points, pair, png_path)
        if png is not None:
            written.append(png)
    return written


if __name__ == "__main__":
    for written in write_chart():
        print(written)
    sys.exit(0)
