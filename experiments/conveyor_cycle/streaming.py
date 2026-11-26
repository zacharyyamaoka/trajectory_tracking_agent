"""Bound 4 kHz logging while replaying the same frozen conveyor cycle."""

from __future__ import annotations

import math
import time
from functools import partial

import numpy as np
from robot_controllers.bench.ur5e import Ur5ePlant

from trajectory_tracking_agent.ruler import metrics

import run

# WHY bound the physical log at the board buffer: the 30-minute slow tape needs 7M physics
# ticks. The scorer needs every tick's gate verdict, and only the exact tape instants for replay.
PHYSICS_BUFFER_ROWS = 4096


class _Ring:
    """A stock plant log's absolute indexing, backed by a bounded array."""

    def __init__(self, data):
        self.data = data
        self.capacity = len(data)
        self.keys = np.full(self.capacity, -1, dtype=np.int64)

    def __setitem__(self, index, value):
        slot = index % self.capacity
        self.data[slot] = value
        self.keys[slot] = index

    def __getitem__(self, index):
        slot = index % self.capacity
        if np.any(self.keys[slot] != index):
            raise RuntimeError("the stock plant asked for a row outside the replay ring")
        return self.data[slot]


class _Discard:
    def __setitem__(self, index, value):
        pass


class StreamingUr5ePlant(Ur5ePlant):
    """Stock board and simulator dynamics, with bounded physical samples and full-resolution gate counters."""

    _COLUMNS = {
        "t": ("_t", (), np.float64),
        "q": ("_q", (6,), np.float64),
        "qd": ("_qd", (6,), np.float64),
        "tau": ("_tau", (6,), np.float64),
        "tool_pos": ("_tool_pos", (3,), np.float64),
        "at_cap": ("_at_cap", (6,), np.bool_),
        "board_mode": ("_mode", (6,), np.int64),
    }

    def __init__(self, *, frozen_times, portal, dep, specification, **plant_kwargs):
        super().__init__(**plant_kwargs)
        self.portal = portal
        self.dep = dep
        self.specification = specification
        self.indices = np.rint(np.asarray(frozen_times) * dep.board.rate_hz).astype(np.int64)
        self.end = int(self.indices[-1]) + 1
        self.probe_wall_s = 0.0
        self._cursor = 0
        self._kept = 0
        self._slicing = False
        self._clearance_hits = 0
        self._first_hit = None
        self._limit_hits = 0
        self._saturated = 0
        self._bad_torque = False
        self._cap = np.asarray(dep.torque_cap_nm, dtype=np.float64)
        self._recorded = {key: np.empty((len(self.indices), *shape), dtype=dtype)
                          for key, (_, shape, dtype) in self._COLUMNS.items()}

    def _allocate(self, rows):
        board_rows = math.ceil(self.timing.reply_delay_s / self._dt) + 2
        self._buffer_rows = max(PHYSICS_BUFFER_ROWS, board_rows)
        super()._allocate(self._buffer_rows)
        self._capacity = rows
        names = ("_sample_q", "_sample_qd", "_sample_tau", *(column[0] for column in self._COLUMNS.values()))
        for name in names:
            setattr(self, name, _Ring(getattr(self, name)))
        for name in ("_tau_ff", "_tau_fb_board", "_latched_tick", "_tau_stop"):
            setattr(self, name, _Discard())

    def _grow(self):
        self._capacity *= 2

    def _check_divergence(self):
        # Treat the subdivision solely as a log drain. A MuJoCo reset is reported at the original host wake.
        if not self._slicing:
            super()._check_divergence()

    def advance(self, until):
        while self._cursor < self.end:
            boundary = min(self._cursor + self._buffer_rows, self.end) * self._dt
            if boundary > until:
                break
            self._slicing = True
            try:
                super().advance(boundary)
            finally:
                self._slicing = False
            self._drain()
        # The final call preserves the exact controller's wake and divergence check, including a coincident boundary.
        super().advance(until)

    def _drain(self):
        started = time.perf_counter()
        end = min(max(self._k, 0), self.end)
        if end <= self._cursor:
            return
        indices = np.arange(self._cursor, end)
        columns = {key: getattr(self, name)[indices] for key, (name, _, _) in self._COLUMNS.items()}
        kept_end = int(np.searchsorted(self.indices, end))
        if kept_end > self._kept:
            wanted = self.indices[self._kept:kept_end] - self._cursor
            for key, data in columns.items():
                self._recorded[key][self._kept:kept_end] = data[wanted]
            self._kept = kept_end

        clearance_hits, first_hit = run.scene_clearance(self.portal, columns["t"], columns["q"])
        self._clearance_hits += clearance_hits
        if first_hit is not None and self._first_hit is None:
            self._first_hit = first_hit
        self._limit_hits += metrics.limit_violations(columns["q"], columns["qd"], self.dep.position_min_rad,
                                                      self.dep.position_max_rad, self.dep.velocity_max_rad_s)
        torques = columns["tau"]
        self._bad_torque |= bool(np.isnan(torques).any())
        self._saturated += int(np.count_nonzero(np.any(np.abs(torques) >= metrics.SATURATION_FRACTION * self._cap, axis=1)))
        self._cursor = end
        elapsed = time.perf_counter() - started
        self.probe_wall_s += elapsed
        # WHY remove probe time: the stock runner checks the simulation time box before its offline collision scan.
        self.specification._deadline += elapsed
        if self.specification.watched is not None:
            self.specification.watched._deadline += elapsed

    def samples(self):
        self._drain()
        if self._kept != len(self.indices) or self._cursor != self.end:
            raise ValueError("the bounded log did not cover every frozen target instant and physics sample")
        rows = self._kept
        # The stock UR5e episode accepts no belt or pushes; these three stock channels are zero.
        return {**self._recorded, "contact_force": np.zeros((rows, 3)),
                "in_contact": np.zeros(rows, dtype=bool), "external_force": np.zeros((rows, 3))}

    def physics_summary(self):
        bad = self._bad_torque or not (np.isfinite(self._cap).all() and (self._cap > 0.0).all())
        return {
            "physics_samples": self._cursor,
            "scene_clearance_violating_samples": self._clearance_hits,
            "first_scene_violation": self._first_hit,
            "saturation_share_pct": math.nan if bad else 100.0 * (self._saturated / self._cursor),
            "limit_violations": self._limit_hits,
        }


if __name__ == "__main__":
    run.main(replay=partial(run.run_one, streaming_factory=StreamingUr5ePlant))
