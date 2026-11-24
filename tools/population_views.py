"""The population views: where the search stands, as three small static SVGs regenerated from the ledger.

    uv run --all-extras python tools/population_views.py      # or `tta progress`: site/views/{lineage,gates,specialists}.svg

- `lineage.svg`: one Graphviz tree per generation-0 root (roots left to right in creation order, wrapped into rows);
  node fill = dev tool_track_rms_mm on one sequential blue scale (darker = lower = better), a red outline and a faded
  fill = not admissible, edge label = Δ mm vs the parent, the path from its root to the current best thick orange,
  dead ends (a child no better than its parent, with no children) faded.
- `gates.svg`: every scored solution (creation order) x the five gates; a cell = how many dev tasks fail that gate
  (blank when none), with the dev objective as a bar at the row's end.
- `specialists.svg`: the top admissible solutions (at most 12, every per-task winner included) x the dev tasks grouped
  by task kind; a cell = the solution's task error / the best admissible error on that task (1.0 = the winner, dotted).

Solutions tagged `ablation` in meta.json are left out of all three views (an ablation study measures what a finished
line's parts were worth; it is not search progress); the lineage title counts them (Zach, 2026-11-24).

WHY only metrics out + provenance (Zach, 2026-11-24: "the blackbox viz is not related to the solution, only to the
metrics out"): the views read ledger rows (objective, admissible, failed_gates, task_objectives, split, ruler, parent,
change), meta.json's `created` for the creation order, the dataset's task kinds, and, for a row without
task_objectives, the evaluator-written `solutions/<id>/scorecard.json`. They never open a solution.py.
Prior art and the view spec: vault note "Visualizing Population-Level Search — Prior Art and Best Practices (2026-11-24)".

Explicit mid greys (no currentColor: an SVG in an <img> does not inherit the page's colour), so each view reads on a
white page and on a dark one; no external fonts or scripts; each file well under 150 KB at ~150 solutions.
"""

import datetime as _dt
import json
import math
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "ledger.jsonl"
TASKS_PATH = REPO_ROOT / "datasets" / "ur5e_alone" / "workspace" / "v2" / "tasks.jsonl"
SOLUTIONS_DIR = REPO_ROOT / "solutions"
OUT_DIR = REPO_ROOT / "site" / "views"
VIEWS = ("lineage", "gates", "specialists")

GATES = ("completed", "stop_error_max_mm", "saturation_share_pct", "limit_violations", "floor_clearance")
GATE_LABELS = {  # readable names; the contract's code name is in each header's tooltip
    "completed": "completed",
    "stop_error_max_mm": "stop error ≤ 1 mm",
    "saturation_share_pct": "saturation ≤ 2 %",
    "limit_violations": "within limits",
    "floor_clearance": "above the floor",
}
GATE_INITIALS = {"completed": "C", "stop_error_max_mm": "S", "saturation_share_pct": "T", "limit_violations": "L",
                 "floor_clearance": "F"}  # fmt: skip
KIND_GROUPS = (  # (label, kinds): the dataset's task kinds in the order OBJECTIVES §3 lists them
    ("joint A→B", ("a_to_b_joint",)),
    ("tool line A→B", ("a_to_b_line",)),
    ("via points", ("via_points",)),
    ("ISO 9283", ("iso9283_path", "iso9283_cube")),
)

FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
# WHY Helvetica's metric twins for the lineage: Graphviz places each label line by Helvetica's widths (Nimbus Sans here)
HELVETICA = "Helvetica, Arial, 'Liberation Sans', 'Nimbus Sans', sans-serif"
TEXT = "#8c8c8c"  # the progress chart's mid grey: readable on white and on a dark page
FAINT = "#8c8c8c"
ORANGE = "#f28c28"  # the progress chart's "best so far"
GREEN = "#2ca02c"
RED = "#d62728"
BAR = "#2a78d6"
NO_VALUE = "#9e9e9e"
# one sequential blue, darker = better; both ends stay visible on white and on #111 (dataviz palette steps 600 → 200)
BLUES = ("#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4")
ORANGES = ("#f9d3bd", "#f4a77f", "#eb6834", "#c4501f", "#8f3510")  # gate failures: more = darker
RATIO_CAP = 3.0
SPECIALISTS_MAX = 12
LINEAGE_ROW_WIDTH = 960.0
SIZE_LIMIT_BYTES = 150 * 1024


# ── reading the ledger (metrics out + provenance only) ──────────────────────────────────────────────────────


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _natural(text: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def _instant(text: Any) -> float:
    try:
        instant = _dt.datetime.fromisoformat(str(text))
    except ValueError:
        return math.inf
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_dt.UTC)
    return instant.timestamp()


def read_rows(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def newest_rows(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """The newest row per (solution, split, ruler): the last in file order (the ledger is appended in time order)."""
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        out[(str(row.get("solution")), str(row.get("split")), str(row.get("ruler")))] = dict(row)
    return out


def dev_tasks(tasks_path: Path) -> list[tuple[str, str]]:
    """[(task_id, kind)] of the dev split, in task-id order (only the id, split and kind of each task are read)."""
    path = Path(tasks_path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            task = json.loads(line)
            if task.get("split") == "dev":
                out.append((str(task["task_id"]), str(task.get("kind", "other"))))
    return sorted(out, key=lambda pair: _natural(pair[0]))


def ablation_ids(solutions_dir: Path) -> list[str]:
    """Solutions whose meta.json carries the tag `ablation` (provenance only: never a solution.py)."""
    out = []
    folder = Path(solutions_dir)
    for meta in sorted(folder.glob("*/meta.json")) if folder.exists() else []:
        try:
            if "ablation" in (json.loads(meta.read_text()).get("tags") or []):
                out.append(meta.parent.name)
        except (OSError, ValueError):
            continue
    return out


def creation_order(solutions_dir: Path, scored: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every solution oldest first, as the progress chart numbers them: meta.json `created`, then the id (naturally).
    A scored solution without a meta.json goes by its first ledger row's time."""
    first_seen: dict[str, float] = {}
    for row in rows:
        first_seen.setdefault(str(row.get("solution")), _instant(row.get("t")))
    stamps: dict[str, float] = {}
    folder = Path(solutions_dir)
    if folder.exists():
        for meta in folder.glob("*/meta.json"):  # provenance only: never a solution.py
            try:
                stamps[meta.parent.name] = _instant(json.loads(meta.read_text()).get("created"))
            except (OSError, ValueError):
                continue
    for solution in scored:
        stamps.setdefault(solution, first_seen.get(solution, math.inf))
    return sorted(stamps, key=lambda s: (stamps[s], _natural(s)))


@dataclass
class Population:
    """The dev rows of the current ruler and everything the three views need beside them."""

    ruler: str
    dev: dict[str, dict[str, Any]]  # solution -> its newest dev row
    order: list[str]  # every solution in creation order (the progress chart's x axis)
    tasks: list[tuple[str, str]]  # dev (task_id, kind)
    task_objectives: dict[str, dict[str, float | None]] = field(default_factory=dict)  # backfilled where needed
    backfilled: list[str] = field(default_factory=list)
    ablations: list[str] = field(default_factory=list)  # tagged `ablation`: left out of every view, counted

    def number(self, solution: str) -> int | None:
        return self.order.index(solution) + 1 if solution in self.order else None

    def scored_in_order(self) -> list[str]:
        return [s for s in self.order if s in self.dev] + sorted(set(self.dev) - set(self.order), key=_natural)

    def objective(self, solution: str) -> float | None:
        row = self.dev.get(solution)
        return None if row is None else _finite(row.get("objective"))

    def admissible(self, solution: str) -> bool:
        row = self.dev.get(solution)
        return bool(row and row.get("admissible") is True and _finite(row.get("objective")) is not None)

    def best(self) -> str | None:
        """The lowest-objective admissible solution (ties by id), as OBJECTIVES §4 and the leaderboard pick it."""
        pool = [s for s in self.dev if self.admissible(s)]
        return min(pool, key=lambda s: (self.objective(s), s)) if pool else None


def _scorecard_task_objectives(solutions_dir: Path, solution: str, ruler: str) -> dict[str, float | None]:
    """A dev scorecard's per-task objectives (evaluator-written outputs), for a ledger row older than task_objectives."""
    path = Path(solutions_dir) / solution / "scorecard.json"
    if not path.exists():
        return {}
    try:
        card = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if card.get("split") != "dev" or str(card.get("ruler")) != ruler or card.get("solution", solution) != solution:
        return {}
    return {str(task["task"]): _finite(task.get("objective")) for task in card.get("tasks") or [] if "task" in task}


def load(
    ledger_path: Path = LEDGER_PATH,
    tasks_path: Path = TASKS_PATH,
    solutions_dir: Path = SOLUTIONS_DIR,
    order: Sequence[str] | None = None,
) -> Population:
    rows = read_rows(ledger_path)
    ruler = str(rows[-1].get("ruler", "v1")) if rows else "v1"  # the ruler the ledger is on now
    newest = newest_rows(rows)
    left_out = ablation_ids(solutions_dir)
    dev = {solution: row for (solution, split, rule), row in newest.items()
           if split == "dev" and rule == ruler and solution not in left_out}  # fmt: skip
    full_order = list(order) if order is not None else creation_order(solutions_dir, list(dev), rows)
    full_order = [s for s in full_order if s not in left_out]
    population = Population(ruler=ruler, dev=dev, order=full_order, tasks=dev_tasks(tasks_path), ablations=left_out)
    for solution, row in dev.items():
        values = row.get("task_objectives")
        if isinstance(values, Mapping) and values:
            population.task_objectives[solution] = {str(k): _finite(v) for k, v in values.items()}
        else:
            backfill = _scorecard_task_objectives(solutions_dir, solution, ruler)
            population.task_objectives[solution] = backfill
            if backfill:
                population.backfilled.append(solution)
    if not population.tasks:  # no dataset file: the union of the rows' task ids, one group
        ids = sorted({t for values in population.task_objectives.values() for t in values}, key=_natural)
        population.tasks = [(t, "other") for t in ids]
    return population


# ── colours ─────────────────────────────────────────────────────────────────────────────────────────────────


def _rgb(hex_colour: str) -> tuple[float, float, float]:
    value = hex_colour.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _hex(rgb: Sequence[float]) -> str:
    return "#" + "".join(f"{round(255 * min(1.0, max(0.0, c))):02x}" for c in rgb)


def ramp(stops: Sequence[str], t: float) -> str:
    """Piecewise-linear colour along `stops` at t in [0, 1]."""
    t = min(1.0, max(0.0, t))
    position = t * (len(stops) - 1)
    low = min(int(position), len(stops) - 2)
    frac = position - low
    a, b = _rgb(stops[low]), _rgb(stops[low + 1])
    return _hex([a[i] + (b[i] - a[i]) * frac for i in range(3)])


def _luminance(hex_colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ink_on(fill: str) -> str:
    """Near-black or white text, whichever reads on `fill`."""
    return "#ffffff" if _luminance(fill) < 0.22 else "#111111"


def _mm(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _signed(value: float) -> str:
    return ("−" if value < 0 else "+") + f"{abs(value):.3f}"


def _svg_open(width: float, height: float, title: str, extra: str = "", font: str = FONT, style: str = "") -> list[str]:
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg"{extra} width="{width:.0f}" height="{height:.0f}" '
             f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="{font}" font-size="11" fill="{TEXT}" role="img" '
             f'aria-label="{escape(title)}">', f"<title>{escape(title)}</title>"]  # fmt: skip
    if style:
        parts.append(f"<style>{style}</style>")
    return parts


def _text(x: float, y: float, body: str, size: float = 11, anchor: str = "start", fill: str = TEXT,
          weight: str | None = None, extra: str = "") -> str:  # fmt: skip
    attrs = "".join((f' fill="{fill}"' if fill != TEXT else "", f' font-size="{size:g}"' if size != 11 else "",
                     f' text-anchor="{anchor}"' if anchor != "start" else "",
                     f' font-weight="{weight}"' if weight else "", extra))  # fmt: skip
    return f'<text x="{x:.1f}" y="{y:.1f}"{attrs}>{body}</text>'


# ── 1 · lineage ─────────────────────────────────────────────────────────────────────────────────────────────


def _better(population: Population, child: str, parent: str | None) -> bool:
    """Is `child` better than `parent`: admissible, and the parent is not (or scores higher)."""
    if not population.admissible(child):
        return False
    if parent is None or not population.admissible(parent):
        return True
    return population.objective(child) < population.objective(parent)  # type: ignore[operator]


def lineage_model(population: Population) -> dict[str, Any]:
    """The forest: parent/children per node, roots in creation order, the root-to-best path and the dead ends.
    A parent named by a row but never scored is a placeholder node (it is drawn, dashed, as "not scored")."""
    scored = population.scored_in_order()
    parent: dict[str, str | None] = {}
    for solution in scored:
        named = population.dev[solution].get("parent")
        parent[solution] = str(named) if named else None
    placeholders = sorted({p for p in parent.values() if p and p not in population.dev}, key=_natural)
    for p in placeholders:
        parent[p] = None
    rank = {s: i for i, s in enumerate(population.order)}

    def position(solution: str) -> tuple[float, list[Any]]:
        return (rank.get(solution, math.inf), _natural(solution))

    # a cycle in the provenance (never expected) is cut where it closes, so every node has exactly one root
    for solution in list(parent):
        seen, node = {solution}, parent[solution]
        while node is not None:
            if node in seen:
                parent[solution] = None
                break
            seen.add(node)
            node = parent.get(node)
    children: dict[str, list[str]] = {s: [] for s in parent}
    for solution, p in parent.items():
        if p is not None:
            children[p].append(solution)
    for kids in children.values():
        kids.sort(key=position)

    def root_of(solution: str) -> str:
        while parent[solution] is not None:
            solution = parent[solution]  # type: ignore[assignment]
        return solution

    def first_member(root: str) -> tuple[float, list[Any]]:
        stack, best = [root], position(root)
        while stack:
            node = stack.pop()
            best = min(best, position(node))
            stack.extend(children[node])
        return best

    roots = sorted({root_of(s) for s in parent}, key=first_member)
    top = population.best()
    path: list[str] = []
    node = top
    while node is not None:
        path.append(node)
        node = parent[node]
    path.reverse()
    dead_ends = sorted((s for s in parent if parent[s] is not None and not children[s]
                        and s in population.dev and not _better(population, s, parent[s])), key=position)  # fmt: skip
    return {"parent": parent, "children": children, "roots": roots, "best": top, "path_to_best": path,
            "dead_ends": dead_ends, "placeholders": placeholders}  # fmt: skip


def _colour_scale(population: Population) -> tuple[float, float] | None:
    values = [population.objective(s) for s in population.dev if population.admissible(s)]
    values = [v for v in values if v is not None and v > 0]
    return (min(values), max(values)) if values else None


def objective_colour(value: float | None, scale: tuple[float, float] | None) -> str:
    if value is None or scale is None or value <= 0:
        return NO_VALUE
    low, high = scale
    if high <= low * 1.0001:
        return ramp(BLUES, 0.0)
    t = (math.log(value) - math.log(low)) / (math.log(high) - math.log(low))
    return ramp(BLUES, t)


def _dot_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tree_dot(population: Population, model: Mapping[str, Any], root: str,
              scale: tuple[float, float] | None) -> tuple[str, int]:
    parent, children = model["parent"], model["children"]
    on_path, dead = set(model["path_to_best"]), set(model["dead_ends"])
    members, stack = [], [root]
    while stack:
        node = stack.pop(0)
        members.append(node)
        stack.extend(children[node])
    # WHY stagger wide fan-outs (unflatten): a parent with dozens of children would otherwise be one very wide rank
    fan_out = max((sum(1 for c in children[m] if not children[c]) for m in members), default=0)
    lines = ["digraph T {",
             '  graph [rankdir=TB, nodesep=0.10, ranksep=0.22, margin=0, bgcolor="transparent", fontname="Helvetica"];',
             '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, width=0.3, height=0.3, '
             'margin="0.06,0.04", penwidth=1];',
             '  edge [fontname="Helvetica", fontsize=9, arrowsize=0.5, penwidth=1];']  # fmt: skip
    for node in members:
        number = population.number(node)
        tag = f"#{number} " if number else ""
        if node not in population.dev:
            lines.append(f"  {_dot_quote(node)} [label=<{escape(node)}<BR/><FONT POINT-SIZE=\"9\">not scored</FONT>>, "
                         f'style="rounded,dashed", color="{FAINT}", fontcolor="{TEXT}", '
                         f'tooltip={_dot_quote(f"{node}: named as a parent, no dev row in the ledger")}];')
            continue
        row = population.dev[node]
        value = population.objective(node)
        admissible = population.admissible(node)
        fill = objective_colour(value, scale)
        faded = (not admissible) or node in dead
        failed = {g: int(n) for g, n in (row.get("failed_gates") or {}).items() if n}
        initials = "".join(GATE_INITIALS.get(g, "?") for g in GATES if g in failed)
        sub = _mm(value) + ("" if admissible else f" ✗{initials}" if initials else " ✗")
        state = "admissible" if admissible else ("not admissible: " + ", ".join(f"{g} {n} tasks" for g, n in failed.items())
                                                   if failed else "not admissible")  # fmt: skip
        tip = f"{tag}{node} · {_mm(value)} mm · {state}"
        if parent[node] is not None:
            tip += f" · parent {parent[node]}"
        if node in dead:
            tip += " · dead end"
        change = str(row.get("change") or "")
        if change:
            # WHY cut at 140 with an ellipsis: ~150 tooltips must fit 150 KB; the full line is in the ledger and meta.json
            tip += " · change: " + (change if len(change) <= 140 else change[:139] + "…")
        if faded:
            border, width = (RED, 1.6) if not admissible else (FAINT + "99", 1)
            attrs = f'fillcolor="{fill}59", color="{border}", fontcolor="{TEXT}", penwidth={width}'
        else:
            attrs = f'fillcolor="{fill}", color="{FAINT}", fontcolor="{ink_on(fill)}"'
        if node in on_path:
            attrs += f', color="{ORANGE}", penwidth={3 if node == model["best"] else 2}'
        css = " ".join(c for c, on in (("best", node == model["best"]), ("path", node in on_path), ("dead", node in dead),
                                       ("inadmissible", not admissible)) if on)  # fmt: skip
        lines.append(f'  {_dot_quote(node)} [label=<<B>{escape(node)}</B><BR/><FONT POINT-SIZE="10">{escape(sub)}</FONT>>, '
                     f"{attrs},{f' class={_dot_quote(css)},' if css else ''} tooltip={_dot_quote(tip)}];")
    for node in members:
        for child in children[node]:
            a, b = population.objective(node), population.objective(child)
            delta = None if a is None or b is None else b - a
            better = _better(population, child, node)
            colour = GREEN if better else TEXT
            label = _signed(delta) if delta is not None else "—"
            attrs = f'label={_dot_quote(label)}, fontcolor="{colour}", color="{GREEN if better else FAINT}"'
            if node in on_path and child in on_path:
                attrs += f', color="{ORANGE}", penwidth=3, class="path"'
            elif child in dead:
                attrs += ', style="dashed"'
            # WHY no edge tooltip: the label already says Δ, and ~150 tooltips would push the file past 150 KB
            lines.append(f"  {_dot_quote(node)} -> {_dot_quote(child)} [{attrs}];")
    lines.append("}")
    return "\n".join(lines) + "\n", fan_out


def _run_graphviz(dot_source: str, fan_out: int) -> str:
    source = dot_source
    if fan_out > 8 and shutil.which("unflatten"):
        stagger = min(4, math.ceil(fan_out / 8))
        source = subprocess.run(["unflatten", "-l", str(stagger), "-f"], input=source, capture_output=True, text=True,
                                check=True).stdout  # fmt: skip
    dot = shutil.which("dot") or "/usr/bin/dot"
    return subprocess.run([dot, "-Tsvg"], input=source, capture_output=True, text=True, check=True).stdout


def _box(match: re.Match[str]) -> str:
    """A rounded node box: Graphviz's 20-point path as one <rect rx> (a third of the bytes)."""
    numbers = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", match.group(2))]
    xs, ys = numbers[0::2], numbers[1::2]
    return (f'<rect{match.group(1)} x="{min(xs):.1f}" y="{min(ys):.1f}" width="{max(xs) - min(xs):.1f}" '
            f'height="{max(ys) - min(ys):.1f}" rx="5"/>')


def _embed(svg: str) -> tuple[str, float, float]:
    """Graphviz's SVG as a group: its content without the XML prologue and root; comments, ids, default <title>s and
    font families dropped (the root sets the font); node boxes as rects; and its size in layout units."""
    match = re.search(r'viewBox="([\d.\-]+) ([\d.\-]+) ([\d.]+) ([\d.]+)"', svg)
    width, height = (float(match.group(3)), float(match.group(4))) if match else (0.0, 0.0)
    body = svg[svg.index(">", svg.index("<svg")) + 1 : svg.rindex("</svg>")]
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"<title>.*?</title>\n?", "", body, flags=re.S)
    body = re.sub(r' (font-family|id)="[^"]*"| text-anchor="start"| font-size="11\.00"', "", body)
    body = re.sub(r' font-size="(\d+)\.00"', r' font-size="\1"', body)
    body = body.replace("<g><a ", "<a ").replace("</a>\n</g>", "</a>")
    chunks = body.split('<g class="node')
    body = chunks[0] + "".join('<g class="node' + re.sub(r'<path((?: [a-z-]+="[^"]*")*) d="M([^"]+)"/>', _box, chunk, count=1)
                               for chunk in chunks[1:])  # fmt: skip
    # 2 decimals is sub-pixel; only geometry is rounded, never a label's digits
    body = re.sub(r' (points|d|x|y|width|height|transform|fill-opacity|stroke-opacity)="([^"]*)"',
                  lambda m: f' {m.group(1)}="' + _short_numbers(m.group(2)) + '"', body)
    return body.strip(), width, height


def _short_numbers(text: str) -> str:
    """Every number to at most 2 decimals, trailing zeros dropped: 0.349020 -> 0.35, -27.0 -> -27."""
    return re.sub(r"\d+\.\d+", lambda m: f"{float(m.group(0)):.2f}".rstrip("0").rstrip("."), text)


def render_lineage(population: Population) -> str:
    model = lineage_model(population)
    scale = _colour_scale(population)
    scored = len(population.dev)
    admissible = sum(1 for s in population.dev if population.admissible(s))
    top = model["best"]
    title = (f"Lineage · {scored} solutions in {len(model['roots'])} trees · {admissible} admissible · best "
             + (f"{top} {population.objective(top):.3f} mm" if top else "none yet") + " (dev, tool_track_rms_mm)"
             + (f" · {len(population.ablations)} ablation variants not shown" if population.ablations else ""))
    pad, gap_x, gap_y, header = 12.0, 14.0, 18.0, 74.0
    if not model["roots"]:
        parts = _svg_open(640, 120, title, font=HELVETICA)
        parts += [_text(pad, 22, escape(title), 14, weight="600"),
                  _text(pad, 60, "No solutions scored yet: tta evaluate &lt;id&gt;"), "</svg>"]
        return "\n".join(parts) + "\n"
    trees = []
    for root in model["roots"]:
        source, fan_out = _tree_dot(population, model, root, scale)
        trees.append(_embed(_run_graphviz(source, fan_out)))
    # roots left to right in creation order, wrapped into rows like text
    placed, x, y, row_h = [], pad, header, 0.0
    width_limit = max(LINEAGE_ROW_WIDTH, max(w for _, w, _ in trees) + 2 * pad)
    for body, w, h in trees:
        if x > pad and x + w > width_limit - pad:
            x, y, row_h = pad, y + row_h + gap_y, 0.0
        placed.append((body, x, y))
        x += w + gap_x
        row_h = max(row_h, h)
    total_w = width_limit
    total_h = y + row_h + pad
    parts = _svg_open(total_w, total_h, title, ' xmlns:xlink="http://www.w3.org/1999/xlink"', font=HELVETICA)
    parts.append(_text(pad, 20, escape(title), 13.5, weight="600"))
    # legend: the colour scale, then the encodings
    legend_y = 40.0
    if scale:
        parts.append(_text(pad, legend_y + 4, "dev mm", 10.5))
        x0 = pad + 46
        steps = 5
        for i in range(steps):
            t = i / (steps - 1)
            value = math.exp(math.log(scale[0]) + t * (math.log(scale[1]) - math.log(scale[0]))) if scale[1] > scale[0] else scale[0]
            fill = objective_colour(value, scale)
            parts.append(f'<rect x="{x0 + i * 44:.1f}" y="{legend_y - 8}" width="42" height="16" rx="3" fill="{fill}"/>')
            parts.append(_text(x0 + i * 44 + 21, legend_y + 4, f"{value:.3g}", 10, "middle", ink_on(fill)))
            if scale[1] <= scale[0]:
                break
        x0 += steps * 44 + 10
    else:
        x0 = pad
    keys = [(f'<line x1="{{x}}" x2="{{x2}}" y1="{legend_y}" y2="{legend_y}" stroke="{ORANGE}" stroke-width="3"/>', "path to the best"),
            (f'<rect x="{{x}}" y="{legend_y - 6}" width="16" height="12" rx="3" fill="{BLUES[2]}" fill-opacity="0.35" stroke="{RED}" stroke-width="1.6"/>', "not admissible (✗ gates)"),
            (f'<rect x="{{x}}" y="{legend_y - 6}" width="16" height="12" rx="3" fill="{BLUES[2]}" fill-opacity="0.35" stroke="{FAINT}" stroke-opacity="0.6"/>', "dead end"),
            (f'<text x="{{x}}" y="{legend_y + 4}" fill="{GREEN}" font-size="10">−Δ</text>', "edge: Δ mm vs parent")]  # fmt: skip
    for mark, label in keys:
        parts.append(mark.format(x=f"{x0:.1f}", x2=f"{x0 + 16:.1f}"))
        parts.append(_text(x0 + 21, legend_y + 4, escape(label), 10.5))
        x0 += 21 + 5.6 * len(label) + 16
    parts.append(_text(pad, 62, escape("Gates failed: C completed · S stop error · T saturation · L limits · F floor. "
                                       "Darker = lower error. Hover a node for its change (the proposer's claim)."), 10))
    for body, x, y in placed:
        parts.append(f'<g transform="translate({x:.1f} {y:.1f})">{body}</g>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ── 2 · gates ───────────────────────────────────────────────────────────────────────────────────────────────


def gates_model(population: Population) -> list[dict[str, Any]]:
    """One row per scored solution in creation order: failing dev tasks per gate (None = the row has no count)."""
    out = []
    for solution in population.scored_in_order():
        row = population.dev[solution]
        failed = row.get("failed_gates")
        counts = {g: (int(failed[g]) if isinstance(failed, Mapping) and failed.get(g) is not None else None) for g in GATES}
        out.append({"solution": solution, "number": population.number(solution), "counts": counts,
                    "objective": population.objective(solution), "admissible": population.admissible(solution)})
    return out


def _nice_ticks(high: float) -> list[float]:
    step = 10.0 ** math.floor(math.log10(high / 3.0)) if high > 0 else 1.0
    for factor in (1, 2, 5, 10):
        if high / (step * factor) <= 4:
            step *= factor
            break
    return [k * step for k in range(math.ceil(high / step - 1e-9) + 1)]  # the last tick at or past `high`


GATES_MAX_ROWS = 200


def render_gates(population: Population) -> str:
    every = gates_model(population)
    rows = every[-GATES_MAX_ROWS:]
    n_tasks = len(population.tasks) or max((max((c or 0) for c in r["counts"].values()) for r in rows), default=1) or 1
    admissible = sum(1 for r in every if r["admissible"])
    top = population.best()
    title = f"Gates on dev · {len(every)} solutions · {admissible} admissible · {n_tasks} dev tasks"
    pad, row_h, cell_w, header = 12.0, 18.0, 46.0, 128.0
    label_w = max([7.0 * len(r["solution"]) for r in rows] + [60.0]) + 10
    num_w = 34.0
    x_cells = pad + num_w + label_w
    x_bar = x_cells + len(GATES) * cell_w + 18
    bar_w = 190.0
    width = x_bar + bar_w + 92
    height = header + max(1, len(rows)) * row_h + 50
    parts = _svg_open(width, height, title)
    parts.append(_text(pad, 20, escape(title), 13.5, weight="600"))
    shown = "" if len(rows) == len(every) else f" · the newest {len(rows)} shown"
    parts.append(_text(pad, 37, escape(f"cell = dev tasks failing that gate (of {n_tasks}; blank = none, ? = no count, "
                                       f"which fails closed) · bar = tool_track_rms_mm, newest dev row each{shown}"), 10))
    if not rows:
        parts += [_text(pad, header, "No solutions scored yet: tta evaluate &lt;id&gt;"), "</svg>"]
        return "\n".join(parts) + "\n"
    # column headers: readable names, the contract's code name in the tooltip
    for i, gate in enumerate(GATES):
        cx = x_cells + i * cell_w + cell_w / 2
        parts.append(f'<g transform="translate({cx + 4:.1f} {header - 8:.1f}) rotate(-45)"><title>{gate}</title>'
                     f'<text x="0" y="0">{escape(GATE_LABELS[gate])}</text></g>')
    parts.append(_text(x_cells - 6, header - 8, "solution", 10.5, "end"))
    best_value = population.objective(top) if top else None
    # WHY the axis spans the admissible solutions: one blown-up reject must not flatten every bar that matters
    scale_values = [r["objective"] for r in rows if r["objective"] is not None and r["admissible"]]
    scale_values = scale_values or [r["objective"] for r in rows if r["objective"] is not None] or [1.0]
    ticks = _nice_ticks(max(scale_values))
    axis_max = ticks[-1]
    parts.append(_text(x_bar, header - 24, "objective (dev mm)", 10.5))
    bottom = header + len(rows) * row_h
    for tick in ticks:
        tx = x_bar + bar_w * tick / axis_max
        parts.append(f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="{header - 4}" y2="{bottom}" stroke="{FAINT}" '
                     'stroke-opacity="0.25"/>')
        parts.append(_text(tx, header - 8, f"{tick:g}", 9.5, "middle"))
    if best_value:
        bx = x_bar + bar_w * best_value / axis_max
        parts.append(f'<line x1="{bx:.1f}" x2="{bx:.1f}" y1="{header - 4}" y2="{bottom}" stroke="{ORANGE}" '
                     f'stroke-width="1.2" stroke-dasharray="3 2"><title>best {top} {best_value:.3f} mm</title></line>')
    empty = []  # every gate a row passes: one faint outline path, no element per cell
    for j, r in enumerate(rows):
        y = header + j * row_h
        mid = y + row_h / 2 + 4
        if j % 2 == 0:
            parts.append(f'<rect x="{pad}" y="{y:.0f}" width="{width - 2 * pad:.0f}" height="{row_h:g}" fill="{FAINT}" '
                         'fill-opacity="0.07"/>')
        weight = "600" if r["solution"] == top else None
        parts.append(_text(pad + num_w - 6, mid, f"#{r['number']}" if r["number"] else "", 9.5, "end"))
        parts.append(_text(x_cells - 6, mid, escape(r["solution"]), 11, "end", weight=weight))
        for i, gate in enumerate(GATES):
            count = r["counts"][gate]
            x = x_cells + i * cell_w
            if count == 0:
                empty.append(f"M{x + 2:.0f} {y + 2:.0f}h{cell_w - 4:g}v{row_h - 4:g}h{4 - cell_w:g}z")
                continue
            tip = f"{r['solution']}: {gate} fails on " + (f"{count} of {n_tasks} dev tasks" if count is not None else
                                                          "an unknown number of tasks (no count: fails closed)")
            if count is None:
                parts.append(f'<g><title>{escape(tip)}</title><rect x="{x + 2:.0f}" y="{y + 2:.0f}" width="{cell_w - 4:g}" '
                             f'height="{row_h - 4:g}" rx="2" fill="none" stroke="{RED}" stroke-dasharray="2 2"/>'
                             + _text(x + cell_w / 2, mid, "?", 10.5, "middle", RED) + "</g>")
            else:
                fill = ramp(ORANGES, math.sqrt(min(1.0, count / n_tasks)))
                parts.append(f'<g><title>{escape(tip)}</title><rect x="{x + 2:.0f}" y="{y + 2:.0f}" width="{cell_w - 4:g}" '
                             f'height="{row_h - 4:g}" rx="2" fill="{fill}"/>'
                             + _text(x + cell_w / 2, mid, str(count), 10.5, "middle", ink_on(fill)) + "</g>")
        value = r["objective"]
        if value is None:
            parts.append(_text(x_bar, mid, "no objective", 10, fill=RED))
            continue
        length = bar_w * min(value, axis_max) / axis_max
        tip = f"{r['solution']}: {value:.3f} mm, " + ("admissible" if r["admissible"] else "not admissible")
        if r["admissible"]:
            bar = f'<rect x="{x_bar:.0f}" y="{y + 4:.0f}" width="{max(length, 1):.1f}" height="{row_h - 8:g}" rx="2" fill="{BAR}">'
        else:
            bar = (f'<rect x="{x_bar + 0.8:.1f}" y="{y + 4.8:.1f}" width="{max(length - 1.6, 1):.1f}" height="{row_h - 9.6:.1f}" '
                   f'rx="2" fill="none" stroke="{RED}" stroke-width="1.4">')
        clipped = "›" if value > axis_max else ""
        parts.append(f"{bar}<title>{escape(tip)}</title></rect>"
                     + _text(x_bar + length + 5, mid, f"{value:.3f}{clipped}", 10, weight=weight))
    if empty:
        parts.append(f'<path d="{"".join(empty)}" fill="none" stroke="{FAINT}" stroke-opacity="0.3"/>')
    foot = bottom + 22
    parts.append(f'<rect x="{x_bar:.0f}" y="{foot - 9}" width="14" height="10" rx="2" fill="{BAR}"/>')
    parts.append(_text(x_bar + 18, foot, "admissible", 10))
    parts.append(f'<rect x="{x_bar + 80:.0f}" y="{foot - 9}" width="14" height="10" rx="2" fill="none" stroke="{RED}" stroke-width="1.4"/>')
    parts.append(_text(x_bar + 98, foot, "not admissible", 10))
    parts.append(_text(pad, foot + 16, "# = creation order (the progress chart's x axis) · dashed orange = the best · "
                                       "› = past the axis", 10))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ── 3 · specialists ─────────────────────────────────────────────────────────────────────────────────────────


def _groups(tasks: Sequence[tuple[str, str]]) -> list[tuple[str, list[tuple[str, str]]]]:
    out, taken = [], set()
    for label, kinds in KIND_GROUPS:
        members = [t for t in tasks if t[1] in kinds]
        if members:
            out.append((label, members))
            taken |= {t[0] for t in members}
    rest = [t for t in tasks if t[0] not in taken]
    if rest:
        out.append(("other", rest))
    return out


def specialists_model(population: Population, k: int = SPECIALISTS_MAX) -> dict[str, Any]:
    """Per dev task: the best admissible error and its winner; the rows to show (every winner, then the best by
    objective, at most k, ordered by objective); per row and task the error ratio to the best; the headline numbers."""
    k = min(k, SPECIALISTS_MAX)
    pool = sorted((s for s in population.dev if population.admissible(s) and population.task_objectives.get(s)),
                  key=lambda s: (population.objective(s), s))  # fmt: skip
    task_ids = [t for t, _ in population.tasks]
    best: dict[str, float] = {}
    winner: dict[str, str] = {}
    for task in task_ids:
        for solution in pool:  # in objective order, so a tie goes to the better overall solution
            value = population.task_objectives[solution].get(task)
            if value is not None and value > 0 and (task not in best or value < best[task]):
                best[task], winner[task] = value, solution
    wins: dict[str, int] = {}
    for solution in winner.values():
        wins[solution] = wins.get(solution, 0) + 1
    winners = sorted(wins, key=lambda s: (-wins[s], population.objective(s), s))
    chosen = winners[:k]
    for solution in pool:
        if len(chosen) >= k:
            break
        if solution not in chosen:
            chosen.append(solution)
    chosen.sort(key=lambda s: (population.objective(s), s))
    ratios = {s: {t: (None if (v := population.task_objectives[s].get(t)) is None or t not in best else v / best[t])
                  for t in task_ids} for s in chosen}  # fmt: skip
    within = {s: sum(1 for r in ratios[s].values() if r is not None and r <= 1.1) for s in chosen}
    top = population.best()
    weakest = None
    if top in ratios:
        medians = []
        for label, members in _groups(population.tasks):
            values = sorted(r for t, _ in members if (r := ratios[top].get(t)) is not None)
            if values:
                medians.append((values[len(values) // 2] if len(values) % 2 else
                                0.5 * (values[len(values) // 2 - 1] + values[len(values) // 2]), label))
        # WHY a 5 % floor: a best that wins (nearly) everything has no weak family worth naming
        if medians and max(medians)[0] >= 1.05:
            weakest = max(medians)
    return {"pool": pool, "rows": chosen, "best": best, "winner": winner, "wins": wins, "within_10pct": within,
            "ratios": ratios, "distinct_winners": len(wins), "weakest_family": weakest, "best_solution": top}  # fmt: skip


def ratio_colour(ratio: float) -> str:
    return ramp(BLUES, math.log(max(1.0, ratio)) / math.log(RATIO_CAP))


def render_specialists(population: Population) -> str:
    model = specialists_model(population)
    rows, groups = model["rows"], _groups(population.tasks)
    title = (f"Specialists on dev · {model['distinct_winners']} distinct per-task winners among "
             f"{len(model['pool'])} admissible solutions")
    pad, cell, gap, group_gap, header = 12.0, 15.0, 2.0, 10.0, 124.0
    label_w = max([7.0 * len(s) + 46 for s in rows] + [90.0])
    x_cells = pad + label_w
    x = x_cells
    columns = []  # (task_id, kind, x)
    group_spans = []
    for label, members in groups:
        start = x
        for task, kind in members:
            columns.append((task, kind, x))
            x += cell + gap
        group_spans.append((label, start, x - gap))
        x += group_gap
    x_stats = x + 4
    width = x_stats + 150
    height = header + max(1, len(rows)) * (cell + gap) + 54
    parts = _svg_open(width, height, title)
    parts.append(_text(pad, 20, escape(title), 13.5, weight="600"))
    top, weakest = model["best_solution"], model["weakest_family"]
    sub = "cell = the solution's task error ÷ the best admissible error on that task; ● = the task's winner (1.0×)"
    parts.append(_text(pad, 37, escape(sub), 10))
    if weakest and top:
        parts.append(_text(pad, 52, escape(f"The best ({top}) is weakest on {weakest[1]}: median {weakest[0]:.2f}× the "
                                           "per-task best. Branch from a winner to grow that niche."), 10))
    elif top:
        parts.append(_text(pad, 52, escape(f"The best ({top}) is within 5 % of the per-task best in every task kind "
                                           "(median per kind)."), 10))
    if not rows:
        parts += [_text(pad, header, "No admissible solution with per-task values yet."), "</svg>"]
        return "\n".join(parts) + "\n"
    for label, start, end in group_spans:
        parts.append(f'<line x1="{start:.1f}" x2="{end:.1f}" y1="{header - 40}" y2="{header - 40}" stroke="{FAINT}" '
                     'stroke-width="1"/>')
        name = label if (end - start) >= 7.5 * len(label) else label.split(" ")[0]
        parts.append(_text((start + end) / 2, header - 45, escape(name), 10.5, "middle"))
    for task, kind, cx in columns:
        short = task.rsplit("-", 1)[-1]
        parts.append(f'<g transform="translate({cx + cell / 2 + 3:.1f} {header - 6:.1f}) rotate(-90)"><title>{escape(task)} '
                     f'({escape(kind)})</title><text x="0" y="0" font-size="8.5">{escape(short)}</text></g>')
    parts.append(_text(x_stats, header - 6, "won", 10))
    parts.append(_text(x_stats + 72, header - 6, "within 10 %", 10))
    kind_names = {kind: label for label, kinds in KIND_GROUPS for kind in kinds}
    for j, solution in enumerate(rows):
        y = header + j * (cell + gap)
        mid = y + cell / 2 + 4
        weight = "600" if solution == top else None
        parts.append(_text(x_cells - 8, mid, escape(solution) + f' <tspan font-size="9.5">{_mm(population.objective(solution))}</tspan>',
                           11, "end", weight=weight))
        for task, kind, cx in columns:
            ratio = model["ratios"][solution].get(task)
            where = f"{escape(solution)} · {escape(task.rsplit('-', 1)[-1])} {escape(kind_names.get(kind, kind))}"
            if ratio is None:
                parts.append(f'<rect x="{cx:.0f}" y="{y:.0f}" width="{cell:g}" height="{cell:g}" rx="2" fill="{NO_VALUE}" '
                             f'fill-opacity="0.3"><title>{where} · no value</title></rect>')
                continue
            fill = ratio_colour(ratio)
            value = population.task_objectives[solution][task]
            win = model["winner"].get(task) == solution
            # WHY a short tooltip: 12 rows x 42 tasks of them are most of the file's bytes
            tip = f"{where} · {value:.3f} mm · " + ("the winner" if win else f"{ratio:.2f}× {model['winner'][task]}")
            rect = f'<rect x="{cx:.0f}" y="{y:.0f}" width="{cell:g}" height="{cell:g}" rx="2" fill="{fill}">'
            if win:
                parts.append(f'<g><title>{tip}</title>{rect}</rect><circle cx="{cx + cell / 2:.1f}" cy="{y + cell / 2:.1f}" '
                             f'r="2.6" fill="{ink_on(fill)}"/></g>')
            else:
                parts.append(f"{rect}<title>{tip}</title></rect>")
        won, within = model["wins"].get(solution, 0), model["within_10pct"][solution]
        n = max(1, len(columns))
        for x0, count, opacity in ((x_stats, won, "1"), (x_stats + 72, within, "0.55")):
            length = 40 * count / n
            if count:
                parts.append(f'<rect x="{x0:.0f}" y="{y + 3:.0f}" width="{length:.1f}" height="{cell - 6:g}" fill="{BAR}" '
                             f'fill-opacity="{opacity}"/>')
            parts.append(_text(x0 + length + 4, mid, str(count), 9.5))
    # legend
    ly = header + len(rows) * (cell + gap) + 22
    parts.append(_text(pad, ly + 4, "÷ best", 10.5))
    lx = pad + 44
    for ratio in (1.0, 1.25, 1.5, 2.0, RATIO_CAP):
        fill = ratio_colour(ratio)
        parts.append(f'<rect x="{lx:.1f}" y="{ly - 8}" width="40" height="16" rx="2" fill="{fill}"/>')
        label = f"≥{ratio:g}×" if ratio == RATIO_CAP else f"{ratio:g}×"
        parts.append(_text(lx + 20, ly + 4, label, 10, "middle", ink_on(fill)))
        lx += 42
    parts.append(f'<circle cx="{lx + 12:.1f}" cy="{ly:.1f}" r="2.6" fill="{TEXT}"/>')
    parts.append(_text(lx + 20, ly + 4, "winner", 10))
    parts.append(f'<rect x="{lx + 66:.1f}" y="{ly - 7}" width="14" height="14" rx="2" fill="{NO_VALUE}" fill-opacity="0.3"/>')
    parts.append(_text(lx + 84, ly + 4, f"no value · scale capped at {RATIO_CAP:g}× · rows: every winner, then the best, "
                                        f"≤ {SPECIALISTS_MAX}", 10))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ── writing ─────────────────────────────────────────────────────────────────────────────────────────────────


def summary(population: Population) -> dict[str, Any]:
    """The numbers PROGRESS.md quotes beside the views (text, so the agent reads them without the pictures)."""
    model = specialists_model(population)
    wins = sorted(model["wins"].items(), key=lambda kv: (-kv[1], population.objective(kv[0]), kv[0]))
    return {"niche_winners": wins, "distinct_winners": model["distinct_winners"], "admissible": len(model["pool"]),
            "tasks": len(population.tasks), "weakest_family": model["weakest_family"], "best": population.best()}


def write_views(
    out_dir: Path = OUT_DIR,
    ledger_path: Path = LEDGER_PATH,
    tasks_path: Path = TASKS_PATH,
    solutions_dir: Path = SOLUTIONS_DIR,
    order: Sequence[str] | None = None,
) -> tuple[list[Path], dict[str, Any]]:
    """Write the three SVGs into `out_dir`; returns the paths written and `summary()`. Without Graphviz the lineage
    view is skipped with a note on stderr (the other two never need it)."""
    population = load(ledger_path, tasks_path, solutions_dir, order)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    renderers = {"lineage": render_lineage, "gates": render_gates, "specialists": render_specialists}
    for name in VIEWS:
        try:
            svg = renderers[name](population)
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            print(f"population_views: {name}.svg not written ({error}); install Graphviz (dot)", file=sys.stderr)
            continue
        path = out_dir / f"{name}.svg"
        path.write_text(svg)
        written.append(path)
    return written, summary(population)


if __name__ == "__main__":
    paths, numbers = write_views()
    for written_path in paths:
        print(f"{written_path.relative_to(REPO_ROOT)} ({written_path.stat().st_size / 1024:.1f} KB)")
    print(json.dumps(numbers, default=str))
