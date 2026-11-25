"""Build the ablation page's data from the black box's own files (stdlib only, read-only).

    python3 proposals-ablation-page/_build/build.py --repo ~/trajectory_tracking_agent

Reads ONLY, from the box: ablations/<study>.md parsed by the box's own ablations/study.py (imported, never copied),
ledger.jsonl (objective, admissible, diagnostics), solutions/*/meta.json (parent, change, created, tags) and
solutions/*/scorecard.json (the ruler's output: each objective is checked against its ledger row), plus ideas.md for
the line each component's idea quote sits on. Never a solution's code: code lines and identified parameters are in the
study file's ## Costs table, measured by the box's ablations/costs.py.

The per-view numbers (leave-one-out, add-one-in, pairs, the path, fronts, the surrogate and its Shapley estimate) come
from proposals-ablation/_shared/build.py's `build()`, reused unchanged so these pages and the five view proposals agree.
This file adds `overall`: the overall-importance statistics (Zach 2026-11-24: "there is almost even just overall
importance; I am sure there are statistical measures for that"). Each one says whether it is MEASURED (computed from
measured runs only, exact) or an ESTIMATE (from the surrogate, with its error); see METHODS below.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OLD = ROOT.parent / "proposals-ablation" / "_shared"
sys.path.insert(0, str(OLD))
import build as view_build  # noqa: E402  (proposals-ablation/_shared/build.py: the five views' analysis)

STUDY = "ablations/pass3-2026-11-24.md"
SITE = "https://github.com/zacharyyamaoka/trajectory_tracking_agent"

METHODS = [  # (key, name, basis, one line, citation key)
    ("loo", "Removed from the best (leave-one-out)", "measured",
     "How many times worse p5s-pass3 gets with this part taken out and every other identified number frozen.", "fh16"),
    ("loo_refit", "Removed, then refit", "measured",
     "The same, after one identification pass on the variant's own runs (4 of 9 parts measured).", "fh16"),
    ("aoi", "Added alone to the base (add-one-in)", "measured",
     "How many times better p5s gets with only this part added.", "fh16"),
    ("path", "Its step on the ablation path", "measured",
     "The drop at the step where the greedy path adds it (steps 2-7 chosen on a surrogate, every step measured).", "fh16"),
    ("orders", "Average over the measured orders", "measured",
     "Its average step over every order of adding the nine parts in which every intermediate set was measured. "
     "Exact for those orders; they are not a random sample of the 362,880 orders.", "shapley53"),
    ("shapley", "Shapley value (fair share)", "estimate",
     "Its average step over all 362,880 orders; the 474 sets nobody ran come from the surrogate. Error: jackknife over "
     "the measured sets.", "shapley53"),
    ("fanova", "fANOVA main effect and total effect", "estimate",
     "Share of the error's variance over all 512 sets (log10) explained by this part alone, and by everything it is in "
     "(its interactions too). On the same surrogate table; error: jackknife.", "hutter14"),
]
REFS = {
    "fh16": ("Fawcett & Hoos 2016, Analysing differences between algorithm configurations through ablation, J. Heuristics 22(4):431-458",
             "https://doi.org/10.1007/s10732-014-9275-9"),
    "bied17": ("Biedenkapp, Lindauer, Eggensperger, Hutter, Fawcett & Hoos 2017, Efficient parameter importance analysis via ablation with surrogates, AAAI 31",
               "https://ojs.aaai.org/index.php/AAAI/article/view/10657"),
    "hutter14": ("Hutter, Hoos & Leyton-Brown 2014, An efficient approach for assessing hyperparameter importance (fANOVA), ICML, PMLR 32:754-762",
                 "https://proceedings.mlr.press/v32/hutter14.html"),
    "shapley53": ("Shapley 1953, A value for n-person games, Contributions to the Theory of Games II (Annals of Mathematics Studies 28):307-317",
                  "https://doi.org/10.1515/9781400881970-018"),
    "castro09": ("Castro, Gómez & Tejada 2009, Polynomial calculation of the Shapley value based on sampling, Computers & OR 36(5):1726-1730",
                 "https://doi.org/10.1016/j.cor.2008.04.004"),
    "owen72": ("Owen 1972, Multilinear extensions of games, Management Science 18(5-2):64-79",
               "https://doi.org/10.1287/mnsc.18.5.64"),
    "shapley71": ("Shapley 1971, Cores of convex games, Int. J. Game Theory 1:11-26", "https://doi.org/10.1007/BF01753431"),
    "grabisch99": ("Grabisch & Roubens 1999, An axiomatic approach to the concept of interaction among players in cooperative games, IJGT 28:547-565",
                   "https://doi.org/10.1007/s001820050125"),
    "homma96": ("Homma & Saltelli 1996, Importance measures in global sensitivity analysis of nonlinear models (the total-effect index), RESS 52:1-17",
                "https://doi.org/10.1016/0951-8320(96)00002-6"),
    "cave18": ("Biedenkapp, Marben, Lindauer & Hutter 2018, CAVE: configuration assessment, visualization and evaluation, LION 12",
               "https://ml.informatik.uni-freiburg.de/wp-content/uploads/papers/18-LION12-CAVE.pdf"),
    "hypershap": ("Wever, Muschalik, Fumagalli & Lindauer, HyperSHAP: Shapley values and interactions for explaining hyperparameter optimization, AAAI-26",
                  "https://arxiv.org/abs/2502.01276"),
}


def load_box_parser(repo: Path):
    spec = importlib.util.spec_from_file_location("box_study", repo / "ablations" / "study.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_scorecards(repo: Path, ids) -> dict:
    out = {}
    for s in ids:
        path = repo / "solutions" / s / "scorecard.json"
        if path.exists():
            card = json.loads(path.read_text())
            out[s] = {"objective": card.get("objective"), "gate_pass_rate": card.get("gate_pass_rate"),
                      "failed_gates": card.get("failed_gates"), "admissible": card.get("admissible")}
    return out


# ── overall importance ───────────────────────────────────────────────────────────────────────────────────────


def walsh(values: list[float]) -> list[float]:
    """Fast Walsh-Hadamard transform /n: coefficient a_U of f = sum_U a_U prod_{i in U} s_i, s_i = 2 x_i - 1."""
    a = values[:]
    h = 1
    while h < len(a):
        for i in range(0, len(a), h * 2):
            for j in range(i, i + h):
                a[j], a[j + h] = a[j] + a[j + h], a[j] - a[j + h]
        h *= 2
    n = len(a)
    # with x_i = 1 coded as bit i set; the transform above uses (+ for bit 0, - for bit 1): flip sign for odd |U|
    return [v / n * (-1 if bin(u).count("1") % 2 else 1) for u, v in enumerate(a)]


def table_stats(order: list[str], g: dict[frozenset, float]) -> dict:
    """Exact Shapley, Banzhaf and fANOVA over a COMPLETE table g(subset) = log10 error (all 2^n subsets)."""
    n = len(order)
    shap = {}
    for c in order:
        others = [o for o in order if o != c]
        total = 0.0
        for r in range(n):
            w = math.factorial(r) * math.factorial(n - r - 1) / math.factorial(n)
            for subset in itertools.combinations(others, r):
                s = frozenset(subset)
                total += w * (g[s] - g[s | {c}])  # a decrease in log10 error = a positive contribution
        shap[c] = total
    values = [g[frozenset(order[i] for i in range(n) if u >> i & 1)] for u in range(2 ** n)]
    a = walsh(values)
    var = sum(x * x for x in a[1:])
    main = {order[i]: a[1 << i] ** 2 / var for i in range(n)}
    totals = {order[i]: sum(a[u] ** 2 for u in range(1, 2 ** n) if u >> i & 1) / var for i in range(n)}
    pairs = {f"{order[i]}+{order[j]}": a[(1 << i) | (1 << j)] ** 2 / var for i in range(n) for j in range(i + 1, n)}
    by_order = [sum(a[u] ** 2 for u in range(1, 2 ** n) if bin(u).count("1") == k) / var for k in range(1, n + 1)]
    banzhaf = {order[i]: -2 * a[1 << i] for i in range(n)}  # mean drop in log10 error from adding it, over 256 contexts
    return {"shapley": shap, "main": main, "total": totals, "pairs": pairs, "by_order": by_order, "banzhaf": banzhaf}


def overall(data: dict, study: dict) -> dict:
    order = [c["key"] for c in study["components"]]
    full, none = frozenset(order), frozenset()
    measured = {}
    for v in data["variants"]:
        if v["measured"] and v["removal"] == "frozen" and v.get("objective"):
            measured.setdefault(frozenset(v["keeps"]), v)
    f = {s: math.log10(v["objective"]) for s, v in measured.items()}
    total = f[none] - f[full]

    # MEASURED 1-3: leave-one-out, add-one-in, refit, path step (log10 drops; factor = 10 ** drop)
    comp = {c["key"]: c for c in data["components"]}
    loo = {k: f[full - {k}] - f[full] for k in order}
    aoi = {k: f[none] - f[frozenset({k})] for k in order}
    refit = {k: math.log10(comp[k]["without_refit_factor"]) if comp[k].get("without_refit_factor") else None for k in order}
    path = {}
    for p in data["path"]:
        for k in p["add"]:
            path[k] = math.log10(p["from_mm"] / p["to_mm"]) / len(p["add"])

    # MEASURED 4: every order in which every intermediate set was measured
    @lru_cache(None)
    def chains(s):
        if s == full:
            return [()]
        return [(c,) + rest for c in order if c not in s and (s | {c}) in f for rest in chains(s | {c})]
    orders = chains(none)
    avg = {k: 0.0 for k in order}
    lo = {k: math.inf for k in order}
    hi = {k: -math.inf for k in order}
    for perm in orders:
        s = none
        for k in perm:
            step = f[s] - f[s | {k}]
            avg[k] += step / len(orders)
            lo[k], hi[k] = min(lo[k], step), max(hi[k], step)
            s = s | {k}

    # MEASURED check: does a part's step only grow as parts are added (a convex game)? Then its Shapley value lies
    # between add-one-in and leave-one-out (Shapley 1971). Checked on every nested pair of measured contexts.
    checks = violations = 0
    worst = None
    sets = list(f)
    for k in order:
        ctx = [s for s in sets if k not in s and (s | {k}) in f]
        for s, t in itertools.permutations(ctx, 2):
            if s < t:
                checks += 1
                ms, mt = f[s] - f[s | {k}], f[t] - f[t | {k}]
                if ms > mt + 1e-9:
                    violations += 1
                    gap = ms - mt
                    if worst is None or gap > worst["gap"]:
                        worst = {"part": k, "smaller": sorted(s, key=order.index), "larger": sorted(t, key=order.index),
                                 "gap": gap, "factor": 10 ** gap, "step_small": ms, "step_large": mt,
                                 "solutions": [measured[s]["solution"], measured[s | {k}]["solution"],
                                               measured[t]["solution"], measured[t | {k}]["solution"]]}
    midpoint_sum = sum((loo[k] + aoi[k]) / 2 for k in order)

    # ESTIMATES: the surrogate's complete table (measured where measured), exact Shapley + fANOVA on it; jackknife
    lattice = {frozenset(l["keeps"]): math.log10(l["objective"]) for l in data["lattice"]}
    est = table_stats(order, lattice)
    points = {s: v["objective"] for s, v in measured.items()}
    sur = view_build.Surrogate(points, order)
    reps = []
    for left in points:
        keep = {s: y for s, y in points.items() if s != left}
        X = [[1.0 if c in s else 0.0 for c in order] for s in keep]
        y = [math.log10(v) for v in keep.values()]
        model = view_build.Surrogate._fit(X, y, sur.ell, sur.ridge)
        table = {}
        for r in range(len(order) + 1):
            for subset in itertools.combinations(order, r):
                s = frozenset(subset)
                table[s] = math.log10(keep[s]) if s in keep else view_build.Surrogate._predict(model, [1.0 if c in s else 0.0 for c in order])
        reps.append(table_stats(order, table))
    m = len(reps)

    def jack(get):
        values = [get(r) for r in reps]
        mean = sum(values) / m
        return math.sqrt((m - 1) / m * sum((v - mean) ** 2 for v in values))

    parts = []
    for k in order:
        parts.append({
            "key": k, "name": comp[k]["name"],
            "loo": loo[k], "loo_refit": refit[k], "aoi": aoi[k], "path": path.get(k),
            "orders": avg[k], "orders_min": lo[k], "orders_max": hi[k],
            "shapley": est["shapley"][k], "shapley_se": jack(lambda r: r["shapley"][k]),
            "banzhaf": est["banzhaf"][k], "banzhaf_se": jack(lambda r: r["banzhaf"][k]),
            "main": est["main"][k], "main_se": jack(lambda r: r["main"][k]),
            "total_effect": est["total"][k], "total_effect_se": jack(lambda r: r["total"][k]),
        })
    top_pairs = sorted(est["pairs"].items(), key=lambda kv: -kv[1])[:6]
    return {
        "unit": "log10 of the error; a drop of d is a factor 10**d; shares are d / log10(base / target)",
        "total_drop": total, "total_factor": 10 ** total,
        "parts": parts,
        "measured_sets": len(f), "all_sets": 2 ** len(order), "all_orders": math.factorial(len(order)),
        "measured_orders": len(orders),
        "convexity": {"checks": checks, "violations": violations, "worst": worst},
        "sums": {"loo": sum(loo.values()), "aoi": sum(aoi.values()), "midpoint": midpoint_sum, "orders": sum(avg.values()),
                 "shapley": sum(est["shapley"].values())},
        "fanova": {"by_order": est["by_order"], "pairs": [{"pair": p.split("+"), "share": v,
                   "se": jack(lambda r, p=p: r["pairs"][p])} for p, v in top_pairs]},
        "surrogate": {"points": len(points), "loo_error_factor": 10 ** sur.loo_rmse_log10, "ell": sur.ell, "ridge": sur.ridge,
                      "jackknife_refits": m},
        "methods": [{"key": k, "name": n, "basis": b, "what": w, "ref": r} for k, n, b, w, r in METHODS],
        "refs": {k: {"text": t, "url": u} for k, (t, u) in REFS.items()},
    }


# ── rows for data-ui (one per measured study variant) ────────────────────────────────────────────────────────


def rows(data: dict, order: list[str], names: dict) -> list[dict]:
    fronts = {k: set(v) for k, v in data["fronts"].items()}
    target, base = data["objective"]["target"], data["objective"]["base"]
    out, seen = [], set()
    for v in data["variants"]:
        if not v["measured"] or v["solution"] in seen:
            continue
        seen.add(v["solution"])
        out.append({
            "id": v["solution"], "solution": v["solution"], "kind": v["kind"], "removal": v["removal"],
            "step": v.get("step"), "n_parts": len(v["keeps"]),
            "parts_in": [names[k] for k in order if k in v["keeps"]],
            "parts_out": [names[k] for k in order if k not in v["keeps"]],
            "keeps": [k for k in order if k in v["keeps"]],
            "error_mm": v["objective"], "x_best": v["objective"] / target, "x_base_better": base / v["objective"],
            "code_lines": v.get("code_lines"), "identified_params": v.get("identified_params"),
            "energy_j": v.get("energy_j"), "host_compute_ms_p95": v.get("host_compute_ms_p95"),
            "saturation_share_pct": v.get("saturation_share_pct"), "admissible": v.get("admissible"),
            "on_code_front": v["solution"] in fronts["code_lines"], "on_energy_front": v["solution"] in fronts["energy_j"],
            "ablation_tagged": bool(v.get("ablation")), "parent": v.get("parent"), "change": v.get("change"),
            "created": v.get("created"), "link": f"{SITE}/tree/main/solutions/{v['solution']}/",
            **{f"in_{k}": k in v["keeps"] for k in order},  # one column per part: the stock table as a remix matrix
        })
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.home() / "trajectory_tracking_agent")
    args = parser.parse_args()
    repo = args.repo
    box = load_box_parser(repo)
    text = (repo / STUDY).read_text()
    study = box.parse_changelog(text)
    problems = box.check(study)
    if problems:
        raise SystemExit("the study file does not check: " + "; ".join(problems))
    data = view_build.build(study, repo, "changelog")
    order = [c["key"] for c in study["components"]]
    names = {c["key"]: c["name"] for c in study["components"]}

    # the scorecards (the ruler's output) must agree with the ledger rows the views joined
    cards = read_scorecards(repo, [v["solution"] for v in data["variants"] if v["measured"]])
    mismatched = [s for s, c in cards.items() if abs((c["objective"] or 0) - (view_build.read_ledger(repo)[0][s]["objective"])) > 1e-12]
    if mismatched:
        raise SystemExit(f"scorecard.json and ledger.jsonl disagree for {mismatched}")
    for v in data["variants"]:
        if v["solution"] in cards:
            v["gate_pass_rate"] = cards[v["solution"]]["gate_pass_rate"]

    data["overall"] = overall(data, study)
    data["study_md"] = text
    data["sources"].update({
        "study": STUDY, "parser": "ablations/study.py (the box's own, imported)", "costs": "ablations/costs.py (via the study's ## Costs)",
        "scorecards_checked": len(cards), "ref": __import__("subprocess").check_output(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], text=True).strip(),
        "study_sha256": hashlib.sha256(text.encode()).hexdigest()[:12],
    })
    data["links"] = {"solution": f"{SITE}/tree/main/solutions/", "ideas": f"{SITE}/blob/main/ideas.md#L",
                     "study": f"{SITE}/blob/main/{STUDY}"}
    data["rows"] = rows(data, order, names)
    out = ROOT / "_data"
    out.mkdir(exist_ok=True)
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (out / "ablation.json").write_text(blob)
    (out / "ablation.js").write_text("window.ABLATION = " + blob + ";\n")
    (ROOT / "01-data-ui" / "variants.json").write_text(json.dumps(data["rows"], ensure_ascii=False, indent=1) + "\n")
    o = data["overall"]
    print(f"{len(data['rows'])} rows · {o['measured_sets']} measured sets of {o['all_sets']} · {o['measured_orders']} measured orders · "
          f"convexity {o['convexity']['violations']}/{o['convexity']['checks']} violations · surrogate x{o['surrogate']['loo_error_factor']:.2f}")
    for p in sorted(o["parts"], key=lambda p: -p["shapley"]):
        share = lambda d: f"{100 * d / o['total_drop']:5.1f}%"  # noqa: E731
        print(f"  {p['key']:6s} loo {share(p['loo'])} aoi {share(p['aoi'])} orders {share(p['orders'])} "
              f"shapley {share(p['shapley'])} ±{100 * p['shapley_se'] / o['total_drop']:.1f} main {100 * p['main']:.1f}% ±{100 * p['main_se']:.1f} "
              f"total {100 * p['total_effect']:.1f}%")
    print("  sums:", {k: round(v, 3) for k, v in o["sums"].items()}, "total", round(o["total_drop"], 3))
    print("  fanova by order:", [round(x, 3) for x in o["fanova"]["by_order"]])


if __name__ == "__main__":
    main()
