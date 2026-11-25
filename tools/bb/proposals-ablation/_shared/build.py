"""Build each proposal's data.json from its study.md and the black box's metrics out (stdlib only).

    python3 proposals-ablation/_shared/build.py --repo ~/trajectory_tracking_agent

Reads ONLY: the study file (each proposal's study.md, parsed by its own format), ledger.jsonl (objective, admissible,
diagnostics), solutions/*/meta.json (parent, change, created, tags) and ideas.md (to link each component's idea line).
Never a solution's code: costs that need the code (code lines, identified parameters) are in the study file, measured by
the agent. Everything derived here (leave-one-out and add-one-in factors, interactions, the path, Pareto fronts, a
model-based Shapley estimate) is computed from those numbers, so every number on a page traces to a ledger row or a
line of the study file.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import statistics
from pathlib import Path

import formats

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIAGNOSTICS = ("host_compute_ms_p95", "energy_j", "saturation_share_pct", "tool_lag_ms", "tool_track_max_mm")
COSTS = [  # (key, label, unit, source); every one: lower is better
    ("code_lines", "code size", "lines", "study"),
    ("identified_params", "identified parameters", "numbers", "study"),
    ("host_compute_ms_p95", "host compute p95", "ms", "ledger"),
    ("energy_j", "motor energy", "J", "ledger"),
    ("saturation_share_pct", "saturation share", "%", "ledger"),
]


def read_ledger(repo: Path) -> tuple[dict, dict]:
    """(newest dev row per solution on the current ruler, every dev row per solution)."""
    rows = [json.loads(line) for line in (repo / "ledger.jsonl").read_text().splitlines() if line.strip()]
    ruler = rows[-1].get("ruler", "v1") if rows else "v1"
    newest, every = {}, {}
    for row in rows:
        if row.get("split") == "dev" and row.get("ruler") == ruler:
            newest[row["solution"]] = row
            every.setdefault(row["solution"], []).append(row)
    return newest, every


def read_metas(repo: Path) -> dict:
    out = {}
    for path in (repo / "solutions").glob("*/meta.json"):
        meta = json.loads(path.read_text())
        out[meta["id"]] = {k: meta.get(k) for k in ("parent", "change", "created", "tags", "component")}
    return out


def idea_lines(repo: Path, components: list[dict]) -> dict:
    lines = (repo / "ideas.md").read_text().splitlines() if (repo / "ideas.md").exists() else []
    out = {}
    for c in components:
        if not c.get("idea"):
            continue
        hits = [n for n, line in enumerate(lines, 1) if c["idea"] in line]
        out[c["key"]] = {"line": hits[0] if hits else None, "text": c["idea"], "found": bool(hits)}
    return out


# ── a small surrogate on log10 objective (pure Python: additive least squares + Hamming-kernel ridge) ───────


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[pivot] = M[pivot], M[col]
        if abs(M[col][col]) < 1e-14:
            continue
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                f = M[r][col] / M[col][col]
                M[r] = [x - f * y for x, y in zip(M[r], M[col], strict=True)]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-14 else 0.0 for i in range(n)]


def _lstsq(X: list[list[float]], y: list[float], ridge: float = 1e-9) -> list[float]:
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) + (ridge if i == j else 0.0) for j in range(k)] for i in range(k)]
    return _solve(A, [sum(r[i] * t for r, t in zip(X, y, strict=True)) for i in range(k)])


class Surrogate:
    def __init__(self, points: dict[frozenset, float], order: list[str]):
        self.order = order
        sets = list(points)
        self.X = [[1.0 if c in s else 0.0 for c in order] for s in sets]
        self.y = [math.log10(points[s]) for s in sets]
        best = None
        for ell in (1.0, 3.0, 6.0):
            for ridge in (0.01, 0.1, 1.0):
                errors = []
                for i in range(len(sets)):
                    keep = [j for j in range(len(sets)) if j != i]
                    model = self._fit([self.X[j] for j in keep], [self.y[j] for j in keep], ell, ridge)
                    errors.append(self.y[i] - self._predict(model, self.X[i]))
                score = math.sqrt(sum(e * e for e in errors) / len(errors))
                if best is None or score < best[0]:
                    best = (score, ell, ridge)
        self.loo_rmse_log10, self.ell, self.ridge = best
        self.model = self._fit(self.X, self.y, self.ell, self.ridge)

    @staticmethod
    def _fit(X, y, ell, ridge):
        beta = _lstsq([[1.0] + x for x in X], y)
        residual = [t - (beta[0] + sum(b * v for b, v in zip(beta[1:], x, strict=True))) for x, t in zip(X, y, strict=True)]
        K = [[math.exp(-sum(abs(a - b) for a, b in zip(xi, xj, strict=True)) / ell) + (ridge if i == j else 0.0)
              for j, xj in enumerate(X)] for i, xi in enumerate(X)]
        return {"beta": beta, "alpha": _solve(K, residual), "X": X, "ell": ell}

    @staticmethod
    def _predict(model, x):
        mean = model["beta"][0] + sum(b * v for b, v in zip(model["beta"][1:], x, strict=True))
        return mean + sum(a * math.exp(-sum(abs(p - q) for p, q in zip(x, xi, strict=True)) / model["ell"])
                          for a, xi in zip(model["alpha"], model["X"], strict=True))

    def predict(self, subset) -> float:
        return 10 ** self._predict(self.model, [1.0 if c in subset else 0.0 for c in self.order])


# ── the analysis ────────────────────────────────────────────────────────────────────────────────────────────


def ratio(a: float | None, b: float | None) -> float | None:
    return a / b if a and b else None


def build(study: dict, repo: Path, fmt: str) -> dict:
    newest, every = read_ledger(repo)
    metas = read_metas(repo)
    order = [c["key"] for c in study["components"]]
    base, target = study["meta"]["base"], study["meta"]["target"]

    def value(solution):
        row = newest.get(solution)
        if row is None:
            return None
        meta = metas.get(solution, {})
        out = {"solution": solution, "objective": row.get("objective"), "admissible": row.get("admissible") is True,
               "parent": row.get("parent"), "change": row.get("change"), "created": meta.get("created"),
               "ablation": "ablation" in (meta.get("tags") or []), "ledger_t": row.get("t")}
        for key in DIAGNOSTICS:
            out[key] = (row.get("diagnostics") or {}).get(key)
        out.update(study["costs"].get(solution, {}))
        return out

    variants = []
    for v in study["variants"]:
        row = value(v["solution"]) if v["solution"] else None
        variants.append({**v, **(row or {}), "measured": row is not None})
    by_set: dict[frozenset, dict] = {}
    for v in variants:  # frozen subsets only: a refit is a different controller
        if v["measured"] and v["removal"] == "frozen" and v.get("objective"):
            by_set.setdefault(frozenset(v["keeps"]), v)
    full, none = frozenset(order), frozenset()
    y_full, y_base = by_set[full]["objective"], by_set[none]["objective"]

    surrogate = Surrogate({s: v["objective"] for s, v in by_set.items()}, order)
    lattice = {}
    for r in range(len(order) + 1):
        for subset in itertools.combinations(order, r):
            s = frozenset(subset)
            lattice[s] = (by_set[s]["objective"], "measured", by_set[s]["solution"]) if s in by_set else \
                (surrogate.predict(s), "predicted", None)

    def lv(s):
        return math.log10(lattice[s][0])

    shapley = {}
    n = len(order)
    for c in order:
        others = [o for o in order if o != c]
        total = 0.0
        for r in range(n):
            w = math.factorial(r) * math.factorial(n - r - 1) / math.factorial(n)
            for subset in itertools.combinations(others, r):
                s = frozenset(subset)
                total += w * (lv(s | {c}) - lv(s))
        shapley[c] = 10 ** total

    ideas = idea_lines(repo, study["components"])
    components = []
    for c in study["components"]:
        k = c["key"]
        loo = by_set.get(full - {k})
        refit = next((v for v in variants if v["measured"] and v["removal"] == "refit" and set(v["keeps"]) == set(full - {k})), None)
        aoi = by_set.get(frozenset({k}))
        components.append({
            **c, "idea_line": ideas.get(k, {}).get("line"),
            "without": loo and loo["solution"], "without_mm": loo and loo["objective"],
            "without_factor": ratio(loo and loo["objective"], y_full),  # x worse than the target when removed
            "without_refit": refit and refit["solution"], "without_refit_mm": refit and refit["objective"],
            "without_refit_factor": ratio(refit and refit["objective"], y_full),
            "alone": aoi and aoi["solution"], "alone_mm": aoi and aoi["objective"],
            "alone_factor": ratio(y_base, aoi and aoi["objective"]),  # x better than the base when added alone
            "shapley_factor": shapley[k],  # model-based: average x over every order of adding the components
            "introduced_mm": [value(s) and value(s)["objective"] for s in c["introduced_by"]],
        })

    pairs = []
    for i, j in itertools.combinations(order, 2):
        for context, sets in (("at the base", (none, frozenset({i}), frozenset({j}), frozenset({i, j}))),
                              ("at the target", (full, full - {i}, full - {j}, full - {i, j}))):
            if all(s in by_set for s in sets):
                a, b, c_, d = (math.log10(by_set[s]["objective"]) for s in sets)
                # interaction: does doing both change the objective by more (or less) than doing each, multiplied?
                interaction = (d - b - c_ + a) if context == "at the base" else (d - b - c_ + a)
                pairs.append({"pair": [i, j], "context": context, "solutions": [by_set[s]["solution"] for s in sets],
                              "objectives": [by_set[s]["objective"] for s in sets], "interaction_factor": 10 ** interaction})

    path = []
    steps = sorted((v for v in variants if v.get("step") and v["measured"]), key=lambda v: v["step"])
    previous = by_set[none]
    for v in steps:
        current = frozenset(v["keeps"])
        prior = frozenset(previous["keeps"])
        candidates = []
        for c in order:
            if c in prior:
                continue
            value_, how, solution = lattice[prior | {c}]
            candidates.append({"add": c, "objective": value_, "how": how, "solution": solution})
        candidates.sort(key=lambda x: x["objective"])
        path.append({"step": v["step"], "add": sorted(current - prior, key=order.index), "solution": v["solution"],
                     "from_mm": previous["objective"], "to_mm": v["objective"], **{k: v.get(k) for k in COSTS_KEYS()},
                     "candidates": candidates, "exact": all(x["how"] == "measured" for x in candidates)})
        previous = v

    history = []
    owner = {}
    for c in study["components"]:
        for s in c["introduced_by"]:
            owner[s] = c["key"]
    prev = None
    for s in study.get("history") or []:
        row = value(s) or {"solution": s}
        history.append({**row, "component": owner.get(s), "from_mm": prev and prev.get("objective")})
        prev = row

    population = [value(s) for s in newest if not value(s)["ablation"]]
    ablation_ids = {v["solution"] for v in variants if v["measured"]}
    points = [p for p in population if p["solution"] not in ablation_ids] + [v for v in variants if v["measured"]]
    fronts = {}
    for key, *_ in COSTS:
        pts = [p for p in points if p.get("admissible") and p.get("objective") and p.get(key) is not None]
        front = [p["solution"] for p in pts if not any(
            q[key] <= p[key] and q["objective"] <= p["objective"] and (q[key] < p[key] or q["objective"] < p["objective"])
            for q in pts)]
        fronts[key] = sorted(front, key=lambda s: next(p[key] for p in pts if p["solution"] == s))

    spreads = []
    for solution, rows in every.items():
        values_ = [r["diagnostics"]["host_compute_ms_p95"] for r in rows if (r.get("diagnostics") or {}).get("host_compute_ms_p95")]
        if len(values_) >= 2:
            spreads.append({"solution": solution, "runs": len(values_), "min": min(values_), "max": max(values_)})
    noise = statistics.median(s["max"] / s["min"] for s in spreads) if spreads else None

    return {
        "format": fmt, "study": study["meta"], "findings": study.get("findings") or "", "notes": study.get("notes") or {},
        "objective": {"key": study["meta"]["objective"], "unit": "mm", "base": y_base, "target": y_full},
        "costs": [{"key": k, "label": label, "unit": unit, "source": source} for k, label, unit, source in COSTS],
        "components": components, "variants": variants, "pairs": pairs, "path": path, "history": history,
        "population": [p for p in points if p["solution"] not in ablation_ids], "fronts": fronts,
        "search": population,  # every solution not tagged ablation: the search itself
        "lattice": [{"keeps": sorted(s, key=order.index), "objective": v, "how": how, "solution": sol}
                    for s, (v, how, sol) in lattice.items()],
        "surrogate": {"points": len(by_set), "ell": surrogate.ell, "ridge": surrogate.ridge,
                      "loo_error_factor": 10 ** surrogate.loo_rmse_log10},
        "compute_noise": {"median_max_over_min": noise, "repeats": spreads},
        "sources": {"repo": repo.name, "ledger_rows": sum(len(r) for r in every.values()),
                    "ideas": "ideas.md", "study": f"{formats.FOLDERS[fmt]}/study.md"},
    }


def COSTS_KEYS():  # noqa: N802
    return [k for k, *_ in COSTS] + ["admissible"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.home() / "trajectory_tracking_agent")
    parser.add_argument("--only", choices=formats.FORMATS)
    args = parser.parse_args()
    for fmt, folder in formats.FOLDERS.items():
        if args.only and fmt != args.only:
            continue
        study = formats.PARSERS[fmt]((ROOT / folder / "study.md").read_text())
        data = build(study, args.repo, fmt)
        data["study_md"] = (ROOT / folder / "study.md").read_text()
        data["links"] = {"solution": "https://github.com/zacharyyamaoka/trajectory_tracking_agent/tree/main/solutions/",
                         "ideas": "https://github.com/zacharyyamaoka/trajectory_tracking_agent/blob/main/ideas.md#L"}
        (ROOT / folder / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        (ROOT / folder / "data.js").write_text("window.ABLATION = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
        print(f"{folder}: {len(data['variants'])} variants, {len(data['pairs'])} pair contexts, path {len(data['path'])} "
              f"steps, surrogate x{data['surrogate']['loo_error_factor']:.2f}")


if __name__ == "__main__":
    main()
