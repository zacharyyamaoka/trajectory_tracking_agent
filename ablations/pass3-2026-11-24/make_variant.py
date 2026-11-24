"""Write an ablation variant of p5s-pass3: its solution.py with only the kept components' code, and its model.json.

    uv run --all-extras tta new abl-<slug> --parent p5s-pass3 --change "- <component>" --tag ablation ...
    uv run --all-extras python ablations/pass3-2026-11-24/make_variant.py abl-<slug> --keep bus,lead,fric,...

Study `ablations/pass3-2026-11-24.md`. The components are p5s-pass3's, named from its lineage (each one's WHY is in the
solution that introduced it). The code of each component is p5s-pass3's own, line for line, so a variant's code size
falls by exactly what its missing components cost (all nine kept renders p5s-pass3's code; `--check` proves it).

Frozen removal: model.json is the exact sum of the kept identification passes, each pass's weights taken from the files
the lineage wrote (p5s-pass2's identified/gravity/friction2/pass2.json, as merge_stack.py merged them, and pass 5 =
p5s-pass3's model.json minus p5s-onefit's). Nothing is refitted here; a refit is `identify_pass.py` run afterwards on the
variant's own dev runs (`--refit` copies it in and writes both bases so the pass has somewhere to go).
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import shutil
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOLUTIONS = REPO / "solutions"
SCALES = (0.002, 0.005, 0.01, 0.02, 0.035, 0.05, 0.075, 0.1, 0.2)
GRAVITY_BASIS = ["1", "c2", "s2", "c23", "s23", "c234", "s234", "c234c5", "s234c5", "c234s5", "s234s5", "s5", "c5"]

# component -> (introduced by, one line). Order = the lineage's order.
COMPONENTS = {
    "bus": ("p5s-bus", "lookahead = the bus's command delay per joint, not robot_controllers' calibrated lookahead"),
    "lead": ("p5s-bus-enc", "minus the board's own lead (encoder delay + one board tick, 0.75 ms) in the lookahead"),
    "fric": ("p5s-fric", "identified friction (Coulomb tanh + viscous, from board torque) replaces the given Coulomb"),
    "chord": ("p5s-chord", "chord correction: position sent minus a(s+T/2)·T²/12"),
    "grav": ("p5s-grav", "gravity identification: 13 gravity shapes fitted to joint errors"),
    "fric2": ("p5s-fric2", "second friction pass: multi-scale tanh basis vs target qd, from joint errors"),
    "stiff": ("p5s-kp2 + p5s-kp4", "stiff board gains sent with every command: kp x4, kd x2 (else the configured gains)"),
    "vlag": ("p5s-vlag", "velocity-lag term: ff minus kd·1.3 ms·qdd"),
    "reid": ("p5s-pass2 + p5s-pass3", "re-identification at the stiff gains: identification passes 4 and 5"),
}
# identification pass -> the component that owns it
PASSES = {1: "fric", 2: "grav", 3: "fric2", 4: "reid", 5: "reid"}


# ── model.json: the exact per-pass decomposition ────────────────────────────────────────────────────────────


def _zeros(names):
    return {name: {"friction_nm": [0.0] * (len(SCALES) + 1), "gravity_nm": [0.0] * len(GRAVITY_BASIS)} for name in names}


def pass_contributions() -> dict[int, dict[str, dict[str, list[float]]]]:
    """Each pass's added weights on model.json's basis (the arithmetic of p5s-onefit/merge_stack.py, pass by pass)."""
    source = SOLUTIONS / "p5s-pass2"
    identified = json.loads((source / "identified.json").read_text())
    gravity = json.loads((source / "gravity.json").read_text())
    friction2 = json.loads((source / "friction2.json").read_text())
    pass2 = json.loads((source / "pass2.json").read_text())
    names = list(identified["joints"])
    out = {k: _zeros(names) for k in PASSES}
    for name in names:
        row = identified["joints"][name]
        out[1][name]["friction_nm"][SCALES.index(row["vs_rad_s"])] = row["coulomb_nm"]
        out[1][name]["friction_nm"][-1] = row["viscous_nm_s_rad"]
        out[2][name]["gravity_nm"] = [-a for a in gravity["joints"][name]["coef_nm"]]
        for scales, weights, k in ((friction2["scales_rad_s"], friction2["joints"][name]["weights_nm"], 3),
                                   (pass2["scales_rad_s"], pass2["joints"][name]["friction_nm"], 4)):
            for s, w in zip(scales, weights[:-1], strict=True):
                out[k][name]["friction_nm"][SCALES.index(s)] = -w
            out[k][name]["friction_nm"][-1] = -weights[-1]
        out[4][name]["gravity_nm"] = [-b for b in pass2["joints"][name]["gravity_nm"]]
    onefit = json.loads((SOLUTIONS / "p5s-onefit" / "model.json").read_text())
    pass3 = json.loads((SOLUTIONS / "p5s-pass3" / "model.json").read_text())
    for name in names:
        for key in ("friction_nm", "gravity_nm"):
            out[5][name][key] = [b - a for a, b in zip(onefit["joints"][name][key], pass3["joints"][name][key], strict=True)]
    return out


def model_json(kept_passes: list[int]) -> dict:
    """model.json for the kept passes: their sum, accumulated in the lineage's order (all five = p5s-pass3's file)."""
    pass3 = json.loads((SOLUTIONS / "p5s-pass3" / "model.json").read_text())
    if kept_passes == [1, 2, 3, 4, 5]:
        return pass3  # bit for bit the lineage's own file
    contributions = pass_contributions()
    names = list(pass3["joints"])
    joints = _zeros(names)
    for k in kept_passes:
        for name in names:
            for key in ("friction_nm", "gravity_nm"):
                joints[name][key] = [a + b for a, b in zip(joints[name][key], contributions[k][name][key], strict=True)]
    return {"basis": pass3["basis"], "sign": pass3["sign"],
            "passes": [pass3["passes"][k - 1] | {"pass": k} for k in kept_passes],
            "ablation": {"study": "pass3-2026-11-24", "kept_passes": kept_passes,
                         "how": "the exact sum of the kept passes' weights (ablations/pass3-2026-11-24/make_variant.py)"},
            "joints": joints}  # fmt: skip


# ── solution.py: p5s-pass3's code with only the kept components ─────────────────────────────────────────────


def render(variant_id: str, keep: set[str], passes: list[int], parent: str, note: str, refit: bool = False) -> str:
    has_model = bool(passes) or refit
    model = model_json(passes) if passes else None
    has_friction = refit or bool(model and any(any(r["friction_nm"]) for r in model["joints"].values()))
    has_gravity = refit or bool(model and any(any(r["gravity_nm"]) for r in model["joints"].values()))
    vlag, stiff, chord = "vlag" in keep, "stiff" in keep, "chord" in keep
    identified = has_model or vlag
    kept = [c for c in COMPONENTS if c in keep]
    left = [c for c in COMPONENTS if c not in keep]
    doc = [f'"""{variant_id}: an ablation variant of p5s-pass3 (study ablations/pass3-2026-11-24.md). {note}', "",
           f"Parent {parent}. Kept: {', '.join(kept) or 'none'}. Left out: {', '.join(left) or 'none'}.",
           f"Identification passes in model.json: {', '.join(map(str, passes)) or 'none'} (frozen: p5s-pass3's own weights, "
           "never refitted here" + ("; a refit pass is added by identify_pass.py" if refit else "") + ").",
           "Generated by ablations/pass3-2026-11-24/make_variant.py: each kept component's code is p5s-pass3's own; its WHY",
           "is in the solution that introduced it (" + "; ".join(f"{c} {COMPONENTS[c][0]}" for c in kept) + ")." if kept
           else "is in the solution that introduced it.", '"""', ""]
    imports = ["from __future__ import annotations", "", "import dataclasses"]
    if has_model:
        imports += ["import json", "from pathlib import Path"]
    imports.append("")
    if identified or chord:
        imports.append("import numpy as np")
    imports += ["from robot_controllers.bench.arms import arm as registered_arm"]
    if "bus" not in keep:
        imports.append("from robot_controllers.bench.population import lookahead_for")
    imports += ["from robot_controllers.bench.scenarios import base_scenario",
                "from robot_controllers.controllers.layout import LayoutConfig, LayoutController",
                "from robot_controllers.models import PD, Layout" if stiff else "from robot_controllers.models import Layout", ""]
    head = []
    if has_model:
        head.append('MODEL = json.loads((Path(__file__).resolve().parent / "model.json").read_text())')
    head += [f"KP_SCALE = {4.0 if stiff else 1.0}", f"KD_SCALE = {2.0 if stiff else 1.0}", "", ""]
    body = []
    if has_gravity:
        body += ["def gravity_shapes(q):",
                 '    """The shapes a gravity torque takes on this arm (pan axis vertical; lift, elbow, wrist_1 parallel): (N, 6) -> (N, 13)."""',
                 "    q = np.atleast_2d(np.asarray(q, dtype=float))",
                 "    a2, a23, a234, a5 = q[:, 1], q[:, 1] + q[:, 2], q[:, 1] + q[:, 2] + q[:, 3], q[:, 4]",
                 "    return np.column_stack([",
                 "        np.ones(len(q)), np.cos(a2), np.sin(a2), np.cos(a23), np.sin(a23), np.cos(a234), np.sin(a234),",
                 "        np.cos(a234) * np.cos(a5), np.sin(a234) * np.cos(a5), np.cos(a234) * np.sin(a5), np.sin(a234) * np.sin(a5),",
                 "        np.sin(a5), np.cos(a5),", "    ])", "", ""]
    if has_friction:
        body += ["def friction_basis(qd, scales):",
                 '    """Odd in qd, zero at rest: tanh(qd / s) for each scale, then qd: (..., n) -> (..., n, S + 1)."""',
                 "    qd = np.asarray(qd, dtype=float)",
                 "    return np.concatenate([np.tanh(qd[..., None] / scales), qd[..., None]], axis=-1)", "", ""]
    if identified:
        terms = (["model.json's friction"] if has_friction else []) + (["gravity terms"] if has_gravity else [])
        what = " + ".join(["the given model"] + ([" and ".join(terms)] if terms else [])) + (" - kd tau_v qdd" if vlag else "")
        body += ["class IdentifiedModel:", f'    """`ff(q, qd, qdd)`: {what} (pure; (n,) or (N, n))."""', ""]
        body.append("    def __init__(self, given, joint_names, kd_tau_v):" if vlag else "    def __init__(self, given, joint_names):")
        if has_model:
            body.append('        rows = [MODEL["joints"][name] for name in joint_names]')
        body.append("        self.given = given")
        if has_friction:
            body += ['        self.scales = np.asarray(MODEL["basis"]["friction_scales_rad_s"], dtype=float)',
                     '        self.friction = np.array([row["friction_nm"] for row in rows])  # (n, S + 1)']
        if has_gravity:
            body.append('        self.gravity = np.array([row["gravity_nm"] for row in rows]).T  # (13, n)')
        if vlag:
            body.append("        self.kd_tau_v = np.asarray(kd_tau_v, dtype=float)")
        body += ["", "    def __call__(self, q, qd, qdd):"]
        if has_gravity:
            body += ["        gravity = gravity_shapes(q) @ self.gravity", "        if np.ndim(q) == 1:",
                     "            gravity = gravity[0]"]
        if has_friction:
            body.append("        friction = np.sum(friction_basis(qd, self.scales) * self.friction, axis=-1)")
        added = (" + friction" if has_friction else "") + (" + gravity" if has_gravity else "")
        if vlag and has_model:
            body += [f"        return (np.asarray(self.given(q, qd, qdd), dtype=float){added}",
                     "                - self.kd_tau_v * np.asarray(qdd, dtype=float))"]
        elif vlag:
            body.append("        return np.asarray(self.given(q, qd, qdd), dtype=float) - self.kd_tau_v * np.asarray(qdd, dtype=float)")
        else:
            body.append(f"        return np.asarray(self.given(q, qd, qdd), dtype=float){added}")
        body += ["", ""]
    if chord:
        body += ["class ChordCorrected:",
                 '    """The layout controller with each command\'s position moved by -a(s + T/2)·T²/12 (everything else its own)."""', "",
                 "    def __init__(self, inner, trajectory, lookahead_s, period_s):",
                 "        self._inner = inner", "        self._t = np.asarray(trajectory.t, dtype=float)",
                 "        self._end = float(self._t[-1])",
                 "        self._acceleration = np.asarray(trajectory.accelerations, dtype=float)",
                 "        self._lookahead = np.asarray(lookahead_s, dtype=float)", "        self._period = float(period_s)", "",
                 "    def __getattr__(self, name):", "        return getattr(self._inner, name)", "",
                 "    def tick(self, state, dt):", "        command, defines = self._inner.tick(state, dt)",
                 '        if self._inner.status != "running" and self._inner.status != "done":',
                 "            return command, defines  # an abort's hold is the JTC's, untouched",
                 "        middle = self._inner.clock_s + self._lookahead + 0.5 * self._period",
                 "        shift = np.zeros(len(middle))", "        for joint, when in enumerate(middle):",
                 "            if when < self._end:  # held at rest after the end: no curvature",
                 "                shift[joint] = np.interp(when, self._t, self._acceleration[:, joint]) * self._period**2 / 12.0",
                 "        position = np.asarray(command.position, dtype=float) - shift",
                 "        return dataclasses.replace(command, position=position), defines", "", ""]
    build = ["def build(trajectory, deployment):",
             '    """A robot_controllers LayoutController (a robot_msgs JointController) for `trajectory` on `deployment`."""',
             "    scenario = dataclasses.replace(",
             "        base_scenario(deployment.arm), host_rate_hz=deployment.host_rate_hz, bus=deployment.bus", "    )",
             "    board = deployment.board", "    period_s = 1.0 / deployment.host_rate_hz"]
    if stiff:
        build.append("    kp = tuple(KP_SCALE * float(k) for k in board.kp_nm_rad)")
    if stiff or vlag:
        build.append("    kd = tuple(KD_SCALE * float(k) for k in board.kd_nm_s_rad)")
    if vlag:
        build.append("    velocity_lag_s = board.encoder_delay_s + 1.0 / (2.0 * np.pi * board.velocity_filter_hz)")
    given_model = "rigid_body" if "fric" in keep else "rigid_body_coulomb"
    if identified:
        build.append(f'    given = registered_arm(deployment.arm).feedforward("{given_model}", scenario.model_error)')
        build.append("    feedforward = IdentifiedModel(given, trajectory.joint_names, np.asarray(kd) * velocity_lag_s)" if vlag
                     else "    feedforward = IdentifiedModel(given, trajectory.joint_names)")
    else:
        build.append(f'    feedforward = registered_arm(deployment.arm).feedforward("{given_model}", scenario.model_error)')
    if "lead" in keep:
        build.append("    board_lead_s = board.encoder_delay_s + 1.0 / board.rate_hz  # 0.5 ms + 0.25 ms")
    if "bus" in keep:
        build.append("    bus_delay_s = deployment.bus.per_joint(len(deployment.joint_names))")
        delays = "bus_delay_s"
    else:
        build.append('    calibrated_s = lookahead_for("P5s", scenario)  # robot_controllers\' calibrated lookahead (p5s\'s)')
        delays = "calibrated_s"
    if "lead" in keep:
        build.append(f"    lookahead_s = tuple(max(0.0, float(delay) - board_lead_s) for delay in {delays})")
    else:
        build.append(f"    lookahead_s = tuple(float(delay) for delay in {delays})")
    build.append('    layout = Layout("plan", "board", lookahead_s=lookahead_s, interpolation="secant_mid_ff")')
    feedback = "PD(kp, kd)" if stiff else "None"
    build.append(f"    config = LayoutConfig(feedforward=feedforward, feedback={feedback}, layout=layout, control_period_s=period_s)")
    build.append("    return ChordCorrected(LayoutController(trajectory, config), trajectory, lookahead_s, period_s)" if chord
                 else "    return LayoutController(trajectory, config)")
    return "\n".join(doc + imports + head + body + build) + "\n"


def code_lines(source: str) -> int:
    """Lines holding code: not blank, not a comment, not a docstring (module, class, function or a bare string)."""
    tree = ast.parse(source)
    prose = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            prose.update(range(node.lineno, node.end_lineno + 1))
    lines = set()
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
            tokenize.ENDMARKER}  # fmt: skip
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in skip:
            lines.update(n for n in range(token.start[0], token.end[0] + 1) if n not in prose)
    return len(lines)


def _strip_doc(source: str) -> str:
    tree = ast.parse(source)
    first = tree.body[0]
    lines = source.splitlines()
    return "\n".join(lines[first.end_lineno:]).strip() + "\n"


def check() -> None:
    """All nine kept renders p5s-pass3's code exactly (docstring aside): the template is the lineage's code."""
    ours = render("x", set(COMPONENTS), [1, 2, 3, 4, 5], "p5s-pass3", "")
    theirs = (SOLUTIONS / "p5s-pass3" / "solution.py").read_text()
    same = _strip_doc(ours) == _strip_doc(theirs)
    print(f"all-on render == p5s-pass3 code: {same}; code lines {code_lines(ours)} vs {code_lines(theirs)}")
    if not same:
        import difflib

        sys.stdout.writelines(difflib.unified_diff(_strip_doc(theirs).splitlines(True), _strip_doc(ours).splitlines(True)))
        raise SystemExit(1)
    total = pass_contributions()
    pass3 = json.loads((SOLUTIONS / "p5s-pass3" / "model.json").read_text())
    worst = max(abs(sum(total[k][n][key][i] for k in PASSES) - pass3["joints"][n][key][i])
                for n in pass3["joints"] for key in ("friction_nm", "gravity_nm") for i in range(len(pass3["joints"][n][key])))
    print(f"sum of the five passes vs p5s-pass3 model.json: max |difference| {worst:.2e} N·m")


def write(variant_id: str, keep: set[str], parent: str, note: str, refit: bool, passes: list[int] | None = None) -> None:
    folder = SOLUTIONS / variant_id
    if not (folder / "meta.json").exists():
        raise SystemExit(f"{folder} has no meta.json: run `tta new {variant_id} --parent {parent} ...` first")
    passes = passes if passes is not None else [k for k, owner in PASSES.items() if owner in keep]
    for path in folder.iterdir():  # the parent's copied files: only what this variant runs stays
        if path.name not in ("meta.json",) and path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    (folder / "solution.py").write_text(render(variant_id, keep, passes, parent, note, refit))
    if passes or refit:
        model = model_json(passes) if passes else {**model_json([]), "passes": []}
        if refit and parent.startswith("abl-"):
            model = json.loads((SOLUTIONS / parent / "model.json").read_text()) if (SOLUTIONS / parent / "model.json").exists() else model
        (folder / "model.json").write_text(json.dumps(model, indent=1) + "\n")
    if refit:
        shutil.copy2(SOLUTIONS / "p5s-pass3" / "identify_pass.py", folder / "identify_pass.py")
    meta = json.loads((folder / "meta.json").read_text())
    print(f"{variant_id}: kept {sorted(keep, key=list(COMPONENTS).index)}, passes {passes}, "
          f"{code_lines((folder / 'solution.py').read_text())} code lines; meta tags {meta.get('tags')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("id", nargs="?")
    parser.add_argument("--keep", default="", help="comma-separated components to keep (" + ",".join(COMPONENTS) + ")")
    parser.add_argument("--parent", default="p5s-pass3")
    parser.add_argument("--note", default="")
    parser.add_argument("--refit", action="store_true", help="copy identify_pass.py in and write both bases")
    parser.add_argument("--passes", default=None, help="override the passes (validation only), e.g. 1,2,3,4")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check()
        return
    keep = {c for c in args.keep.split(",") if c}
    unknown = keep - set(COMPONENTS)
    if unknown:
        raise SystemExit(f"unknown components {sorted(unknown)}; known: {list(COMPONENTS)}")
    passes = [int(p) for p in args.passes.split(",") if p] if args.passes is not None else None
    write(args.id, keep, args.parent, args.note, args.refit, passes)


if __name__ == "__main__":
    main()
