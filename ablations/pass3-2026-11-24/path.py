"""The ablation path p5s -> p5s-pass3, greedy (Fawcett & Hoos 2016), each choice made on a surrogate (Biedenkapp et al.
2017) and each chosen step then measured for real; plus model-based Shapley values over the nine components.

    uv run --all-extras python ablations/pass3-2026-11-24/path.py            # the path so far + the next set to measure
    uv run --all-extras python ablations/pass3-2026-11-24/path.py --json     # everything, for the study file and views

Data: every measured subset of the components: the ablation variants (meta.json `ablation.keeps`) and the lineage
solutions that are exactly a subset (LINKED below, each one reproduced through make_variant.py to <= 4e-12 relative).
Objective = the newest dev tool_track_rms_mm in ledger.jsonl, modelled as log10 (the components' effects multiply).

Surrogate: log10 y = additive least squares over the nine components + a Hamming-kernel ridge on its residual
(exp(-d/ell), ell and the ridge picked by leave-one-out error). Fawcett & Hoos's full ablation needs 8+7+...+1 = 36
runs past the first step; Biedenkapp et al. replaced runs by a surrogate. Here the surrogate only picks the next
component; that step is then run as an ordinary solution, added to the data, and the surrogate refitted, so every
value on the path is measured. Steps 1, 8 and 9 are exact (their candidates are all measured).
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
COMPONENTS = ("bus", "lead", "fric", "chord", "grav", "fric2", "stiff", "vlag", "reid")
LINKED = {  # lineage solutions that are exactly one subset of p5s-pass3's components (frozen weights)
    "p5s": (),
    "p5s-bus": ("bus",),
    "p5s-bus-enc": ("bus", "lead"),
    "p5s-fric": ("bus", "lead", "fric"),
    "p5s-chord": ("bus", "lead", "fric", "chord"),
    "p5s-grav": ("bus", "lead", "fric", "chord", "grav"),
    "p5s-fric2": ("bus", "lead", "fric", "chord", "grav", "fric2"),
    "p5s-kp4": ("bus", "lead", "fric", "chord", "grav", "fric2", "stiff"),
    "p5s-vlag": ("bus", "lead", "fric", "chord", "grav", "fric2", "stiff", "vlag"),
    "p5s-pass3": COMPONENTS,
    "p5s-pass3-g1": tuple(c for c in COMPONENTS if c != "stiff"),
    "p5s-pass3-g1-nolag": tuple(c for c in COMPONENTS if c not in ("stiff", "vlag")),
}


def objectives() -> dict[str, float]:
    out = {}
    for line in (REPO / "ledger.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["split"] == "dev" and row.get("objective") is not None:
            out[row["solution"]] = float(row["objective"])
    return out


def measured() -> dict[frozenset, tuple[str, float]]:
    """{component set: (solution, dev objective)}: frozen variants only (refits are a different controller)."""
    values = objectives()
    data = {}
    for solution, keeps in LINKED.items():
        if solution in values:
            data[frozenset(keeps)] = (solution, values[solution])
    for meta_path in sorted((REPO / "solutions").glob("abl-*/meta.json")):
        meta = json.loads(meta_path.read_text())
        info = meta.get("ablation") or {}
        if info.get("removal", "frozen") != "frozen" or meta["id"] not in values:
            continue
        data.setdefault(frozenset(info["keeps"]), (meta["id"], values[meta["id"]]))
    return data


def _x(subset) -> np.ndarray:
    return np.array([1.0 if c in subset else 0.0 for c in COMPONENTS])


class Surrogate:
    def __init__(self, data: dict[frozenset, tuple[str, float]]):
        sets = list(data)
        self.X = np.array([_x(s) for s in sets])
        self.y = np.array([math.log10(data[s][1]) for s in sets])
        A = np.column_stack([np.ones(len(sets)), self.X])
        self.beta = np.linalg.lstsq(A, self.y, rcond=None)[0]
        residual = self.y - A @ self.beta
        best = None
        for ell in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.5, 6.0):
            for ridge in (1e-4, 1e-3, 1e-2, 1e-1, 0.3, 1.0):
                K = self._kernel(self.X, self.X, ell)
                errors = []
                for i in range(len(sets)):  # leave-one-out on the whole model (mean refitted too)
                    keep = np.arange(len(sets)) != i
                    b = np.linalg.lstsq(A[keep], self.y[keep], rcond=None)[0]
                    r = self.y[keep] - A[keep] @ b
                    alpha = np.linalg.solve(K[np.ix_(keep, keep)] + ridge * np.eye(keep.sum()), r)
                    errors.append(self.y[i] - (A[i] @ b + K[i, keep] @ alpha))
                score = float(np.sqrt(np.mean(np.square(errors))))
                if best is None or score < best[0]:
                    best = (score, ell, ridge)
        self.loo_rmse_log10, self.ell, self.ridge = best
        K = self._kernel(self.X, self.X, self.ell)
        self.alpha = np.linalg.solve(K + self.ridge * np.eye(len(sets)), residual)

    @staticmethod
    def _kernel(a: np.ndarray, b: np.ndarray, ell: float) -> np.ndarray:
        distance = np.abs(a[:, None, :] - b[None, :, :]).sum(-1)
        return np.exp(-distance / ell)

    def predict(self, subset) -> float:
        x = _x(subset)
        return float(self.beta[0] + x @ self.beta[1:] + self._kernel(x[None], self.X, self.ell)[0] @ self.alpha)


def greedy_path(data) -> dict:
    """Fawcett & Hoos's forward path from the base (no components) to the target (all nine): at each step the
    candidate with the lowest objective, measured where it is, else the surrogate's prediction."""
    surrogate = Surrogate(data)
    current: frozenset = frozenset()
    steps = []
    for k in range(1, len(COMPONENTS) + 1):
        candidates = []
        for c in COMPONENTS:
            if c in current:
                continue
            subset = current | {c}
            if subset in data:
                candidates.append((math.log10(data[subset][1]), c, "measured", data[subset][0]))
            else:
                candidates.append((surrogate.predict(subset), c, "predicted", None))
        candidates.sort()
        value, choice, how, solution = candidates[0]
        steps.append({"step": k, "add": choice, "keeps": sorted(current | {choice}, key=COMPONENTS.index),
                      "chosen_on": how, "solution": solution,
                      "objective_mm": data[current | {choice}][1] if current | {choice} in data else None,
                      "predicted_mm": 10 ** surrogate.predict(current | {choice}),
                      "candidates": [{"add": c, "log10_mm": v, "how": h, "solution": s} for v, c, h, s in candidates]})
        current = current | {choice}
        if how == "predicted":
            return {"steps": steps, "next_to_measure": steps[-1]["keeps"], "surrogate": _about(surrogate, data)}
    return {"steps": steps, "next_to_measure": None, "surrogate": _about(surrogate, data)}


def shapley(data) -> dict[str, float]:
    """Each component's Shapley value on log10 objective over all 2^9 subsets (measured where measured, else the
    surrogate): its average marginal effect over every order of adding the components. A model-based estimate."""
    surrogate = Surrogate(data)
    value = {}
    for r in range(len(COMPONENTS) + 1):
        for subset in itertools.combinations(COMPONENTS, r):
            s = frozenset(subset)
            value[s] = math.log10(data[s][1]) if s in data else surrogate.predict(s)
    n = len(COMPONENTS)
    out = {}
    for c in COMPONENTS:
        total = 0.0
        others = [o for o in COMPONENTS if o != c]
        for r in range(n):
            weight = math.factorial(r) * math.factorial(n - r - 1) / math.factorial(n)
            for subset in itertools.combinations(others, r):
                s = frozenset(subset)
                total += weight * (value[s | {c}] - value[s])
        out[c] = total
    return out


def _about(surrogate: Surrogate, data) -> dict:
    return {"points": len(data), "ell": surrogate.ell, "ridge": surrogate.ridge,
            "loo_rmse_log10": surrogate.loo_rmse_log10,
            "loo_rmse_factor": 10 ** surrogate.loo_rmse_log10}


def main() -> None:
    data = measured()
    path = greedy_path(data)
    if "--json" in sys.argv:
        print(json.dumps({"path": path, "shapley_log10": shapley(data),
                          "measured": {",".join(sorted(s, key=COMPONENTS.index)): v for s, v in data.items()}}, indent=1))
        return
    about = path["surrogate"]
    print(f"{about['points']} measured subsets; surrogate ell {about['ell']}, ridge {about['ridge']}, "
          f"leave-one-out error x{about['loo_rmse_factor']:.2f}")
    for step in path["steps"]:
        shown = f"{step['objective_mm']:.4f} mm ({step['solution']})" if step["objective_mm"] else \
            f"predicted {step['predicted_mm']:.4f} mm"
        print(f"{step['step']}. + {step['add']:6s} [{step['chosen_on']}] -> {shown}")
    if path["next_to_measure"]:
        print("next to measure:", ",".join(path["next_to_measure"]))


if __name__ == "__main__":
    main()
