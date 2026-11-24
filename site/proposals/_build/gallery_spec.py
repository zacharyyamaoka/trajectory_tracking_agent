"""Writes the babble gallery spec for the five metric-view proposals; the babble skill's gallery.py builds it into
../index.html. The criteria and gates were fixed before the five were built; the scores were given after.

    python3 site/proposals/_build/gallery_spec.py > /tmp/spec.json
"""
import json

REQ = [
    {"id": "fr1", "name": "Verdict at a glance", "weight": 25,
     "why": "Zach: 'super easy to see at a glance exactly what is going on'. The landing page's first job.",
     "passCondition": "Within about 5 s a reader can say the objective's value, whether it is good, and whether every gate passed.",
     "anchors": {"1": "Numbers are present but the reader must assemble the verdict.",
                 "3": "The verdict is visible but split across places or needs one interaction.",
                 "5": "One sentence plus one glance answers value, good or bad, and every gate."}},
    {"id": "fr2", "name": "Provenance in the motion", "weight": 25,
     "why": "His imagined click: 'the 3D viewer shows something that indicates how that was calculated'.",
     "passCondition": "For each number, the samples or moments it came from, and how they reduce to it, are visible.",
     "anchors": {"1": "Only the number is shown.",
                 "3": "The relevant moment or signal is shown; the reduction is implied.",
                 "5": "The exact samples and their reduction to the number are shown and checkable."}},
    {"id": "fr3", "name": "Failure localisation", "weight": 20,
     "why": "A failing gate must say which gate, on which task, when and where, or nobody can act on it.",
     "passCondition": "A failing gate is named with its task, time and place without hunting.",
     "anchors": {"1": "Pass or fail only.", "3": "Which gate and roughly when, after a click or two.",
                 "5": "Which gate, which task, the exact time and place, immediately."}},
    {"id": "fr4", "name": "Black-box generality", "weight": 15,
     "why": "Zach 2026-11-24: the viz relates only to the metrics out, never the solution; he leans toward a generic blackbox-agent template.",
     "passCondition": "Driven only by outputs and the ruler; any solution renders the same; other robots, metrics and black boxes fit without a redesign.",
     "anchors": {"1": "Tied to one robot or one metric.", "3": "Generic for arms; a new metric needs custom drawing.",
                 "5": "Any black box with samples, an objective and gates renders as is."}},
    {"id": "fr5", "name": "Fits the landing page", "weight": 15,
     "why": "Lane W builds the page with scores and a basic click-to-explain; the pick must drop into it.",
     "passCondition": "Drops into 'scores, click, explanation' with little new layout; works at phone width.",
     "anchors": {"1": "Needs its own page and a new navigation model.", "3": "Fits as a secondary panel or drawer.",
                 "5": "Is the landing page's own interaction, on desktop and phone."}},
]
GATES = [
    {"id": "g1", "name": "Outputs only", "why": "Zach's rule: no controller internals; any solution renders through the same view."},
    {"id": "g2", "name": "Real data; shown numbers equal the source", "why": "Never fabricated: every number traces to a real simulation trace and the ruler."},
    {"id": "g3", "name": "Static, light and dark, no private paths", "why": "It may go public; it must work as plain files beside the site."},
]
G_ALL = {
    "g1": {"pass": True, "evidence": "Reads only _data/fixture.js (target, measured joint states, applied torques, deployment, ruler); the builder never loads the traces' controller fields."},
    "g2": {"pass": True, "evidence": "Shown numbers checked against the fixture from the rendered DOM (0 misses); the fixture is recomputed from arm_motion_bench traces and cross-checked against the traces' own tool error."},
    "g3": {"pass": True, "evidence": "Static HTML plus the shared fixture; light, dark and phone width screenshotted; displayed paths are repo-relative."},
}


def preview(slug, n, what):
    img = 'style="width:100%;vertical-align:top;border-radius:8px;border:1px solid rgba(127,127,127,.25)"'
    return (f'<div style="display:grid;gap:8px">'
            # WHY divs carry the demo classes: the shell's ".prototype img" rule outranks ".demo-alt-only" on an <img>
            f'<div class="demo-base-only" data-spot="hero"><img src="shots/{n}-hero.jpg" alt="{what}: the best solution" {img}></div>'
            f'<div class="demo-alt-only" data-spot="fail"><img src="shots/{n}-fail.jpg" alt="{what}: a failing solution" {img}></div>'
            f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
            f'<button class="demo-button" data-demo-toggle data-base-label="Show the failing solution" data-alt-label="Show the best solution">Show the failing solution</button>'
            f'<a data-open href="{slug}/index.html" target="_blank" rel="noopener" style="font-size:13px">Open the live page ↗</a>'
            f'<span style="font-size:12px;opacity:.7">Same task, same view: best (ctc_tuned) vs failing (menagerie_stock).</span></div></div>')


def still(n, label, caption):
    return {"label": label, "caption": caption, "html": f'<img src="shots/{n}.jpg" alt="{label}">'}


def live(slug):
    return {"label": "Live page", "caption": "The real page on the shared fixture; its Guide strip (top) steps through the states, every control works.",
            "html": f'<iframe src="{slug}/index.html" title="live page" loading="lazy" style="width:100%;height:860px;border:0;border-radius:8px;background:#fff"></iframe>'}


def steps(first, second, third=None):
    out = [{"label": "Best solution", "caption": first, "state": "base", "target": '[data-spot="hero"]'},
           {"label": "Failing solution", "caption": second, "state": "alt", "target": "[data-demo-toggle]"}]
    if third:
        out.append({"label": "Open it live", "caption": third, "state": "base", "target": "[data-open]"})
    return out


def sc(score, evidence, confidence="medium"):
    return {"score": score, "evidence": evidence, "confidence": confidence}


V = [
    {"id": "v1", "name": "Evidence Lens", "slug": "01-evidence-lens", "n": "01", "accent": "#2f5bd3",
     "thesis": "Click a score and the 3D replay redraws to show only the samples that number came from: error whiskers, stop balls, torque colours, the floor drop.",
     "bestWhen": "Explaining one solution's scores spatially: it is Zach's imagined 'click the score, the 3D viewer shows how'.",
     "losesWhen": "Comparing many solutions, or a black box with no geometry; sub-mm errors need a magnification the reader must notice.",
     "decisions": [{"label": "Primary object", "value": "the motion in 3D, one lens per number"},
                   {"label": "Scale", "value": "errors magnified ×M (labelled); stops get 2D close-ups"},
                   {"label": "Time", "value": "a per-sample error strip under the 3D is the scrubber"}],
     "keepParts": ["score list as lens switch", "magnified error tube + whiskers", "stop close-ups", "error-strip scrubber"],
     "proof": ["Rendered headless with WebGL (SwiftShader): every lens, both solutions, dark and phone.", "Opens from file:// as well as over http."],
     "scores": {"fr1": sc(4, "Answer line and score list with ✓/✗ on the left; the 3D takes most of the screen.", "high"),
                "fr2": sc(5, "Each lens draws the exact samples: grey = not counted, whiskers = per-sample distance, balls = the stop windows.", "high"),
                "fr3": sc(4, "Failing stops are red in 3D, in the close-ups and on the strip; the exact time needs a scrub."),
                "fr4": sc(3, "Needs FK link points and a 3D glyph per metric; a non-spatial black box keeps only the list and strip."),
                "fr5": sc(5, "It is the landing page's own interaction (score list + 3D); phone stacks the 3D first.", "high")},
     "media": [still("01-sat", "Torque lens", "Joints coloured by torque as a share of cap at the busiest instant: far from the 98 % line."),
               still("01-dark", "Stop lens, dark", "Each stop's 1 mm ball (magnified) and the close-ups, in the dark theme."),
               still("01-phone", "Phone width", "3D first, then the score list."), live("01-evidence-lens")]},
    {"id": "v2", "name": "Itemized Receipt", "slug": "02-receipt", "n": "02", "accent": "#0f766e",
     "thesis": "Every number prints as a receipt: the line items that turn raw samples into it, each a live chart, ending in a total the page recomputes.",
     "bestWhen": "Trust and audit: someone asks 'how exactly is 0.0168 mm computed?', or a new metric is being designed.",
     "losesWhen": "The question is where in space or when it went wrong, or many numbers must be read at once.",
     "decisions": [{"label": "Primary object", "value": "one number's derivation, top to bottom"},
                   {"label": "Proof", "value": "the page recomputes the total from the samples and says 'equal'"},
                   {"label": "Insight", "value": "line 04 shows which samples carry the squared error"}],
     "keepParts": ["recompute-and-compare line", "squared-error share (worst 10 %)", "PASS / FAIL stamp", "one hover across every chart"],
     "proof": ["Recomputed totals equal the scorecard for objective, stop error, saturation, limits, floor and joint tracking.", "Screenshotted light, phone and the failing case."],
     "scores": {"fr1": sc(3, "The left list shows every value with ✓/✗, but there is no single verdict sentence.", "high"),
                "fr2": sc(5, "Every reduction step is drawn and the total is recomputed in the page from the samples.", "high"),
                "fr3": sc(3, "A failing receipt is stamped FAIL with per-stop bars; the time is on a strip, the place is not shown."),
                "fr4": sc(5, "Any metric that is a chain of reductions prints as a receipt; no geometry needed.", "high"),
                "fr5": sc(3, "Fits as a 'how is this computed' drawer behind a score; not a landing view on its own.")},
     "media": [still("02-where", "Where the error lives", "Line 04: the worst tenth of the samples carries most of the squared error; the hover reads one sample on every line."),
               still("02-lag", "A diagnostic's receipt", "Tool lag: slide the measured curve until it lines up with the target."),
               still("02-phone", "Phone width", "The list becomes two columns above the receipt."), live("02-receipt")]},
    {"id": "v3", "name": "Headroom Gauges", "slug": "03-headroom", "n": "03", "accent": "#b45309",
     "thesis": "Every gate as the share of its limit used, on one log scale with one fail line, sorted into 'what fails next'; click one to see the instant it came closest, in a side view.",
     "bestWhen": "Deciding how safe a passing solution is, or which gate the next change will break first.",
     "losesWhen": "The objective is the question (it has no limit), or someone needs the full derivation.",
     "decisions": [{"label": "Primary object", "value": "each gate's margin, normalised to its limit"},
                   {"label": "Answer", "value": "'closest to failing: X, N % of its limit' as the verdict line"},
                   {"label": "Drill", "value": "worst instant in a 2D side elevation plus a draggable margin sparkline"}],
     "keepParts": ["closest-to-failing verdict line", "one-scale headroom bars", "N× headroom column", "side elevation at the worst instant"],
     "proof": ["Screenshotted light, dark, phone, the failing case and the floor row.", "Surfaced a real near-limit: the elbow at 71 % of its range on the best solution."],
     "scores": {"fr1": sc(5, "One sentence names the verdict and the gate closest to failing; every gate on one scale.", "high"),
                "fr2": sc(3, "Shows the worst instant and the margin over time, not how the number is reduced."),
                "fr3": sc(4, "A failing bar crosses into red, with its instant and side view; one task at a time."),
                "fr4": sc(4, "Any threshold metric is one more row (value ÷ limit) for any black box; the side view needs FK points."),
                "fr5": sc(4, "Gauges fit a landing page's score area well; the drill is 2D, not the 3D Zach pictured.")},
     "media": [still("03-floor", "Distance to spare", "Floor clearance is a distance, not a share: the dot sits left of the line by its millimetres."),
               still("03-dark", "Scrub the margin, dark", "The margin over the whole run; drag along it to move the instant."),
               still("03-phone", "Phone width", "Gauges stack above the moment panel."), live("03-headroom")]},
    {"id": "v4", "name": "Flight Recorder", "slug": "04-flight-recorder", "n": "04", "accent": "#7c3aed",
     "thesis": "Every metric is a lane on one shared timeline with its score at the right; failures are red flags at the moment they happen; open a lane for its six joints.",
     "bestWhen": "Diagnosing when and why: several metrics line up in time (here, the lag explains the stop misses).",
     "losesWhen": "A first-time reader wants one answer, or the question is spatial; it is dense.",
     "decisions": [{"label": "Primary object", "value": "time, shared by every number"},
                   {"label": "Disclosure", "value": "collapsed strips; a click opens per-joint small multiples"},
                   {"label": "Failures", "value": "red flags on the lane plus a clickable flag list in the answer line"}],
     "keepParts": ["shared time axis for every metric", "clickable failure flags", "lane expands to six joints", "mini 3D arm on the playhead"],
     "proof": ["Screenshotted collapsed, expanded, failing and lag states, phone width.", "Playhead drives every lane and the mini 3D arm."],
     "scores": {"fr1": sc(4, "An answer line with ✓/✗ and flags, then a score per lane; dense below it.", "high"),
                "fr2": sc(4, "Every number's per-sample signal is on the shared timeline; the reduction is labelled, not drawn."),
                "fr3": sc(5, "Red flags at the exact times, listed and clickable: 'Stop error: S3 14 mm @ 2.85 s'.", "high"),
                "fr4": sc(5, "A lane is a per-sample signal + threshold + reduction: generic for any black box with time series.", "high"),
                "fr5": sc(3, "Best as the details view under the landing page's scores; too dense to be the hero.")},
     "media": [still("04-joints", "A lane, opened", "Torque vs cap opened into its six joints, each with the 98 % saturation line."),
               still("04-lag", "Why: the lag", "Tool speed: the measured (ink) trails the target (grey) by 144 ms, so the arm is still moving when each stop window closes."),
               still("04-phone", "Phone width", "Lanes narrow, scores stay at the right."), live("04-flight-recorder")]},
    {"id": "v5", "name": "Population Map", "slug": "05-population-map", "n": "05", "accent": "#be185d",
     "thesis": "Start from every solution at once: the objective as the median of each row's task dots, the gates as a 5 × 20 fingerprint; click down to a task and its trace.",
     "bestWhen": "The landing page's top: which solution is best, which are admissible, and why not.",
     "losesWhen": "Explaining one number in depth; the trace panel is the only motion view.",
     "decisions": [{"label": "Primary object", "value": "the population, ranked by the ruler"},
                   {"label": "Objective", "value": "drawn as the median of its task dots, not a bare number"},
                   {"label": "Gates", "value": "a fingerprint: one row per gate, one cell per task"}],
     "keepParts": ["task-dot strip with the median bar", "gate fingerprint", "task × gate matrix", "best-solution sentence"],
     "proof": ["Ranking follows OBJECTIVES §4 (admissible first, then objective).", "Screenshotted light, dark, phone, drill and compare states."],
     "scores": {"fr1": sc(5, "One sentence names the best solution and why the others are not admissible; ranks at a glance.", "high"),
                "fr2": sc(2, "Shows tasks → median, but not where in the motion a number came from beyond one trace panel.", "high"),
                "fr3": sc(4, "The fingerprint shows which gate on which task at a glance; the time only after drilling."),
                "fr4": sc(5, "Reads only scorecards (per-task rows + verdicts): any black box with an objective and gates.", "high"),
                "fr5": sc(4, "The natural top of the landing page; its drill hands off to one of the other views.")},
     "media": [still("05-drill", "Drill into a solution", "menagerie_stock: the stop gate fails on every task; its task trace labels each stop's error."),
               still("05-best", "Compare the best", "ctc_tuned on the same task: stops at a thousandth of a millimetre."),
               still("05-dark", "Dark theme", "The same drill in the dark theme."), live("05-population-map")]},
]


def weighted(v):
    return sum(r["weight"] * v["scores"][r["id"]]["score"] / 5 for r in REQ)


def main():
    totals = {v["id"]: weighted(v) for v in V}
    best = max(totals, key=totals.get)
    variants = []
    for v in V:
        variants.append({
            "id": v["id"], "name": v["name"], "thesis": v["thesis"], "accent": v["accent"],
            "bestWhen": v["bestWhen"], "losesWhen": v["losesWhen"], "decisions": v["decisions"],
            "keepParts": v["keepParts"], "proof": v["proof"], "scores": v["scores"], "gateResults": G_ALL,
            "previewLabel": "best vs failing solution",
            "preview": preview(v["slug"], v["n"], v["name"]),
            "story": {"title": f"{v['name']}: same view, any solution", "steps": steps(
                "The best solution (ctc_tuned) on task workspace-dev-001: every gate passes.",
                "A failing solution (menagerie_stock) through the same view: the stop error gate fails.",
                "The live page has its own five-step Guide and every control works.")},
            "media": v["media"],
        })
    spec = {
        "schemaVersion": 3,
        "title": "Five ways to show what the metrics mean",
        "kicker": "Trajectory Tracking Agent · lane P · /babble 5",
        "brief": ("Zach, 2026-11-24: 'make 5 proposals for how to communicate what the metrics mean visually'. On the landing page "
                  "you see the scores; click one and a view shows how it was calculated. At a glance: what is this number, where did "
                  "it come from in the motion, is it good or bad, which gate failed and when. Driven only by the black box's outputs."),
        "count": 5,
        "defaultId": best,
        "defaultWhy": ("Evidence Lens scores highest (85/100): it is the interaction Zach described (click a score, the 3D view shows the "
                       "samples behind it) and it explains every number in the motion. Flight Recorder is a co-leader at 84 and wins "
                       "'which gate failed and when'. Recommended splice for lane W: Population Map's leaderboard on top, Evidence Lens as "
                       "the click-to-explain, Headroom's 'closest to failing' line in the verdict, Flight Recorder as the details view, "
                       "Receipt as the 'how is it computed' drawer."),
        "decisionHinge": ("Generality versus landing-page fit. Move 15 points from 'Fits the landing page' to 'Black-box generality' "
                          "(a template repo first, this page second) and Flight Recorder leads 90 to Evidence Lens 79."),
        "invariants": [
            "Same fixture for all five: arm_motion_bench UR5e, workspace v1 dev, speed 1.0; task workspace-dev-001 for traces; 4 solutions × 20 tasks.",
            "Only black-box outputs: target, measured joint states, applied torques, deployment, ruler v1. No controller internals.",
            "Same solution switcher (best vs failing) and the same five-step Guide strip shape on every page.",
            "Static pages, light and dark, phone width; numbers recomputed per OBJECTIVES §4.",
        ],
        "boundary": ("Five runnable static pages on real simulation traces. Not yet ruler v1's own deployment (500 Hz arm_motion_bench "
                     "traces of arm_motion_bench's UR5e cell, 20 of its 42 dev tasks); lane E's scorecards drop in through the same fixture."),
        "axes": [
            {"name": "Primary object", "values": ["the motion in 3D (V1)", "a number's derivation (V2)", "a gate's margin (V3)",
                                                   "time (V4)", "the population (V5)"]},
            {"name": "Entry point", "values": ["score list (V1)", "one number (V2)", "verdict sentence (V3)", "timeline (V4)",
                                                "ranking (V5)"]},
            {"name": "Explanation mode", "values": ["spatial lens (V1)", "step-by-step reduction (V2)", "normalised headroom (V3)",
                                                     "aligned signals (V4)", "comparison (V5)"]},
        ],
        "requirements": REQ,
        "hardGates": GATES,
        "variants": variants,
    }
    print(json.dumps(spec, indent=1, ensure_ascii=False))
    import sys
    print({k: round(t, 1) for k, t in totals.items()}, file=sys.stderr)


if __name__ == "__main__":
    main()
