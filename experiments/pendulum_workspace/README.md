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
