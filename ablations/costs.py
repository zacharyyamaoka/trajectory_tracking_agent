"""The costs an ablation study needs that no scorecard holds, measured from each solution's folder (stdlib only).

    python3 ablations/costs.py p5s p5s-pass3 abl-no-bus ...     # one JSON object per solution
    python3 ablations/costs.py --all                              # every solution

- `code_lines`: lines holding code (not blank, not a comment, not a docstring) in solution.py and every .py of the
  folder it imports, transitively (the controller as it runs; shared packages such as robot_controllers not counted).
- `code_lines_folder`: the same count over every .py in the folder (identification and merge scripts too).
- `identified_params`: non-zero numbers under "joints" in the folder's data files (*.json but meta and scorecards),
  reporting keys left out (samples, rms, tasks); `identified_bytes`: those files' size.
- `imports_from`: other solution folders whose .py it imports (counted into code_lines; none so far).

The objective and the scorecard's diagnostics (host_compute_ms_p95, energy_j, saturation_share_pct) are not measured
here: the views read them from ledger.jsonl and the scorecards. This tool reads solution code; the views never do.
"""

from __future__ import annotations

import ast
import io
import json
import math
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOLUTIONS = REPO / "solutions"
NOT_DATA = {"meta.json", "scorecard.json", "scorecard_holdout.json"}
REPORTING = ("samples", "rms", "tasks", "residual", "raw_")


def code_lines(source: str) -> int:
    tree = ast.parse(source)
    prose: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            prose.update(range(node.lineno, node.end_lineno + 1))
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
            tokenize.ENDMARKER}  # fmt: skip
    lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in skip:
            lines.update(n for n in range(token.start[0], token.end[0] + 1) if n not in prose)
    return len(lines)


def _imported_files(path: Path) -> list[Path]:
    """The .py files a module imports from its own folder or another solution folder (static, by name)."""
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    found = []
    for name in names:
        local = path.parent / f"{name}.py"
        if local.exists():
            found.append(local)
        else:
            found += [p for p in SOLUTIONS.glob(f"*/{name}.py") if p.parent != path.parent and name != "solution"]
    return found


def _numbers(value, key: str = "") -> list[float]:
    if any(word in key for word in REPORTING):
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item, key)]
    if isinstance(value, dict):
        return [n for k, v in value.items() for n in _numbers(v, k)]
    return []


def costs(solution: str) -> dict:
    folder = SOLUTIONS / solution
    runtime, queue = set(), [folder / "solution.py"]
    while queue:
        path = queue.pop()
        if path in runtime or not path.exists():
            continue
        runtime.add(path)
        queue += _imported_files(path)
    data = [p for p in folder.glob("*.json") if p.name not in NOT_DATA]
    params = [n for p in data for n in _numbers(json.loads(p.read_text()).get("joints", {}))]
    return {
        "solution": solution,
        "code_lines": sum(code_lines(p.read_text()) for p in runtime),
        "code_lines_folder": sum(code_lines(p.read_text()) for p in folder.glob("*.py")),
        "identified_params": sum(1 for n in params if n != 0.0 and math.isfinite(n)),
        "identified_bytes": sum(p.stat().st_size for p in data),
        "imports_from": sorted({p.parent.name for p in runtime if p.parent != folder}),
    }


def main(argv: list[str]) -> None:
    ids = sorted(p.parent.name for p in SOLUTIONS.glob("*/meta.json")) if argv == ["--all"] else argv
    for solution in ids:
        print(json.dumps(costs(solution)))


if __name__ == "__main__":
    main(sys.argv[1:])
