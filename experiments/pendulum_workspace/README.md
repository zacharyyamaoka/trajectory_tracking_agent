# Shoulder pendulum workspace tracking

The CAN 11 shoulder pendulum's frozen workspace v2 uses the declared measured motion limits and 100 Hz tapes. The simulation campaign replays the 40 development tapes at the highest nominal rung, 1.0. The 12 holdout tapes are reserved for reporting after the controller is locked.

## Stock baseline prediction

Replay the stock `P3s` controller on the frozen tapes, with the nominal 10% model mismatch and stock board gains. Expect at least one development path to exceed both the 1.0 mm whole-trace RMS target and the 0.5 mm worst-stop target. The pendulum's published layout comparison showed several millimetres of error on a slower representative tape. This run measures the full workspace with the original timing, including holds.

Use the installed arm motion bench environment with the tracking agent and robot controllers source trees available on `PYTHONPATH`. The command takes an explicit output directory. A successful run saves synchronized target and measured poses, a summary, and SHA-256 hashes for the target tape and recording.

```bash
python experiments/pendulum_workspace/run.py --split dev --out outputs/pendulum-workspace/p3s-dev
```

The stock baseline completed all 40 development replays. The maxima were 6.746372 mm stop error and 6.744523 mm full-trajectory RMS. The [baseline summary](baseline-dev.json) retains the per-run admission results and recording hashes.

## Identified feedforward prediction

The [identification script](identify.py) uses only the 100 Hz JointState delivered to the controller. It estimates gravity, inertia, Coulomb friction and viscous friction from the same development paths, then writes the [fitted model](can11-fit.json). The board receives a continuous secant position/velocity command and a torque term based on those coefficients. Expect the worst development error on both metrics to drop by at least half. Compare unchanged board gains to the more rigid simulation-only setting of four times stiffness and twice damping, which may reduce residual near each stop.

Both settings met both targets on development. Before opening holdout, select the higher-margin simulation candidate with a 0.092721 mm worst stop and 0.099635 mm worst full-trajectory RMS. The [controller lock](controller-lock.json) records its exact model, source and gains. Keep the [stock-gains alternative](identified-stock-dev.json), which measured 0.484769 mm worst stop and 0.489040 mm worst RMS on development, as evidence for follow-up. The higher stiffness in the simulator has no verified hardware equivalent.

## Locked simulation qualification

The [development replays](identified-locked-dev.json) and [untouched holdout replays](identified-locked-holdout.json) cover all 52 frozen paths at 1.0. The combined maxima were **0.097285 mm** stop error, on `workspace-holdout-011`, and **0.099635 mm** full-trajectory RMS, on `workspace-dev-026`. All 52 passed the separate completion, stop-band, torque saturation and joint-limit checks.

[Verification](verify.py) independently recomputes whole-trace and stop distances from every raw recording, validates the recorded tape arrays against the original bytes, and reconciles both split summaries with the controller lock. The [qualification](qualification.json) holds the maxima and checksums. Raw traces are saved in the output directories `identified-kp4-dev` and `identified-kp4-holdout` under `outputs/pendulum-workspace`.

The stock arm motion bench verifier regenerated every frozen workspace v2 tape and sidecar with the original manifest hashes. A fresh development replay reproduced the summary and worst-RMS trace byte for byte. The holdout command refused a changed damping scale before it created an output directory.

```bash
python experiments/pendulum_workspace/run.py --split dev --record-states --out outputs/pendulum-workspace/p3s-probes
python experiments/pendulum_workspace/identify.py outputs/pendulum-workspace/p3s-probes outputs/pendulum-workspace/reproduced-fit.json
python experiments/pendulum_workspace/run.py --split dev --model experiments/pendulum_workspace/can11-fit.json --gain-scale 4 --damping-scale 2 --out outputs/pendulum-workspace/identified-kp4-dev
python experiments/pendulum_workspace/run.py --split holdout --model experiments/pendulum_workspace/can11-fit.json --lock experiments/pendulum_workspace/controller-lock.json --gain-scale 4 --damping-scale 2 --out outputs/pendulum-workspace/identified-kp4-holdout
python experiments/pendulum_workspace/verify.py --dev outputs/pendulum-workspace/identified-kp4-dev --holdout outputs/pendulum-workspace/identified-kp4-holdout --lock experiments/pendulum_workspace/controller-lock.json
```
