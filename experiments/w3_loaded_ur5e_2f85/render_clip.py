"""The W3 loaded-check clip: the loaded UR5e (2F-85 + 60 g) running p5s-pass3 on one dev task, rendered in MuJoCo.

    MUJOCO_GL=egl uv run python experiments/w3_loaded_ur5e_2f85/render_clip.py --out reports/media/w3_loaded_ur5e_2f85/clip.mp4

What is drawn is the simulation, not an animation: `loaded_check.run_case_task` runs the task exactly as the results do
(loaded plant, controller unaware of the load), and its logged joint angles (4 kHz) are replayed, frame by frame, on a
render-only model: MuJoCo Menagerie's UR5e with its meshes and Menagerie's robotiq_2f85 attached at its
`attachment_site` (the flange, the ruler's tool site). The render model never runs physics. The orange ball is the
60 g object at the TCP (flange + 0.144 m), riding on the measured joints; the green dots are the target TCP path and
the green ball the target TCP at the same instant. At this load the gap between them is about 1 mm, far below what a
frame can show: the clip shows the motion and the hardware, the numbers are in results.json.

The first part plays in real time, the second replays the same span at 0.25x. Muted H.264 (no audio track).
`--menagerie` (default $MUJOCO_MENAGERIE or ~/.cache/mujoco_menagerie) is a MuJoCo Menagerie checkout.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import loaded_check  # noqa: E402

WIDTH, HEIGHT, FPS = 1280, 720, 30
SLOW = 0.25
TAIL_S = 0.5  # show this much of the hold after the trajectory's end
JOINTS = ("shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint", "wrist_1_joint", "wrist_2_joint", "wrist_3_joint")


def render_model(menagerie: Path, target_tcp: np.ndarray):
    """Menagerie's UR5e scene with the 2F-85 on the flange, the object, the target path and a target marker."""
    import mujoco

    spec = mujoco.MjSpec.from_file(str(menagerie / "universal_robots_ur5e" / "scene.xml"))
    gripper = mujoco.MjSpec.from_file(str(menagerie / "robotiq_2f85" / "2f85.xml"))
    spec.attach(gripper, prefix="gripper/", site=spec.site("attachment_site"))
    wrist = spec.body("wrist_3_link")
    wrist.add_geom(name="object", type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.016, 0, 0],
                   pos=[0, loaded_check.FLANGE_Y_M + loaded_check.TCP_OFFSET_M, 0], rgba=[1.0, 0.45, 0.05, 1],
                   contype=0, conaffinity=0, group=1)
    for index, point in enumerate(target_tcp[::2]):
        spec.worldbody.add_geom(name=f"path{index}", type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.003, 0, 0],
                                pos=point.tolist(), rgba=[0.1, 0.85, 0.3, 0.6], contype=0, conaffinity=0, group=1)
    marker = spec.worldbody.add_body(name="target", mocap=True, pos=target_tcp[0].tolist())
    marker.add_geom(type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.010, 0, 0], rgba=[0.1, 0.9, 0.3, 0.9], contype=0,
                    conaffinity=0, group=1)
    spec.visual.global_.offwidth = WIDTH
    spec.visual.global_.offheight = HEIGHT
    return spec.compile()


def check_alignment(model, data) -> float:
    """The render model's flange vs the ruler's tool site over a few joint vectors (m): they must be the same arm."""
    import mujoco
    from robot_controllers.bench.ur5e import tool_position

    rng = np.random.default_rng(0)
    worst = 0.0
    site = model.site("attachment_site").id
    addresses = [model.joint(name).qposadr[0] for name in JOINTS]
    for _ in range(8):
        q = rng.uniform(-2.0, 2.0, 6)
        data.qpos[addresses] = q
        mujoco.mj_kinematics(model, data)
        worst = max(worst, float(np.linalg.norm(data.site_xpos[site] - tool_position(q))))
    return worst


def main(argv: list[str] | None = None) -> int:
    import mujoco

    from trajectory_tracking_agent.ruler.dataset import tasks

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", default="workspace-dev-010", help="dev task id (default: loaded p5s-pass3's worst)")
    parser.add_argument("--solution", default="p5s-pass3")
    parser.add_argument("--out", type=Path, required=True, help="the .mp4 to write")
    default_menagerie = os.environ.get("MUJOCO_MENAGERIE", str(Path.home() / ".cache" / "mujoco_menagerie"))
    parser.add_argument("--menagerie", type=Path, default=Path(default_menagerie))
    args = parser.parse_args(argv)

    task = {item.id: item for item in tasks("dev")}[args.task]
    row = loaded_check.run_case_task(args.solution, task, loaded=True, model_knows=False, keep_log=True)
    log = row.pop("_log")
    t_end = float(task.trajectory.t[-1])
    target_tcp = loaded_check.tcp_position(log["q_target"])

    model = render_model(args.menagerie, target_tcp)
    data = mujoco.MjData(model)
    misalignment = check_alignment(model, data)
    if misalignment > 1e-6:
        raise SystemExit(f"the render model's flange is {misalignment:.2e} m from the ruler's tool site")
    addresses = [model.joint(name).qposadr[0] for name in JOINTS]

    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    span = target_tcp.max(axis=0) - target_tcp.min(axis=0)
    centre = 0.5 * (target_tcp.max(axis=0) + target_tcp.min(axis=0))
    camera.lookat[:] = [0.5 * centre[0], 0.5 * centre[1], 0.5 * max(centre[2], 0.3) + 0.15]  # base to TCP
    sweep = target_tcp[-1] - target_tcp[0]
    camera.azimuth = math.degrees(math.atan2(sweep[1], sweep[0])) + 90.0  # look across the move, not along it
    camera.elevation = -15.0
    camera.distance = 1.75 + 0.3 * float(np.linalg.norm(span))

    log_t, log_q = np.asarray(log["t"]), np.asarray(log["q"])
    show_s = min(t_end + TAIL_S, float(log_t[-1]))
    real_times = np.arange(0.0, show_s, 1.0 / FPS)
    slow_times = np.arange(0.0, show_s, SLOW / FPS)
    real_s = len(real_times) / FPS
    total_s = (len(real_times) + len(slow_times)) / FPS
    args.out.parent.mkdir(parents=True, exist_ok=True)
    caption = (f"UR5e + Robotiq 2F-85 + 60 g object (0.985 kg on the flange), MuJoCo sim\n"
               f"{args.solution} on {args.task} ({task.kind}, {t_end:.2f} s), controller not told about the load")
    stop = row["kpis"]["stop_error_max_mm"]
    numbers = f"tool stop error {stop:.2f} mm (gate 1 mm), TCP {row['extra']['tcp_stop_error_max_mm']:.2f} mm"
    font = "fontcolor=white:fontsize=21:box=1:boxcolor=black@0.55:boxborderw=8:line_spacing=6"
    # WHY textfile=: commas and colons in an inline drawtext text are filtergraph separators
    texts = tempfile.TemporaryDirectory()
    lines = {"caption": caption, "numbers": numbers, "real": "real time", "slow": "0.25x slow motion (same run)"}
    for name, text in lines.items():
        (Path(texts.name) / f"{name}.txt").write_text(text)
    path = {name: Path(texts.name) / f"{name}.txt" for name in lines}
    filters = ",".join([
        f"drawtext=textfile={path['caption']}:x=20:y=20:{font}",
        f"drawtext=textfile={path['numbers']}:x=20:y=92:{font}",
        f"drawtext=textfile={path['real']}:x=20:y=h-50:{font}:enable='lt(t,{real_s:.3f})'",
        f"drawtext=textfile={path['slow']}:x=20:y=h-50:{font}:enable='gte(t,{real_s:.3f})'",
    ])
    command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
               "-r", str(FPS), "-i", "-", "-vf", filters, "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-crf", "23", "-movflags", "+faststart", str(args.out)]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
    target_t = np.asarray(log["t_target"])
    with mujoco.Renderer(model, height=HEIGHT, width=WIDTH) as renderer:
        for when in np.concatenate([real_times, slow_times]):
            index = min(int(round(when / float(log_t[1] - log_t[0]))), len(log_q) - 1)
            data.qpos[addresses] = log_q[index]
            data.mocap_pos[0] = [np.interp(min(when, t_end), target_t, target_tcp[:, axis]) for axis in range(3)]
            mujoco.mj_kinematics(model, data)
            renderer.update_scene(data, camera)
            encoder.stdin.write(renderer.render().tobytes())
    encoder.stdin.close()
    failed = encoder.wait() != 0
    texts.cleanup()
    if failed:
        raise SystemExit("ffmpeg failed")
    print(f"wrote {args.out} ({total_s:.1f} s, {args.out.stat().st_size / 1e6:.2f} MB); {numbers}; flange vs tool "
          f"site {misalignment:.1e} m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
