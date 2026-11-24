// How each score is computed, shown: one explainer per score card.
//
// An explainer is {id, name, unit, value(run), verdict(run), rule(run), native(nativeRow), how(run), plot(host, run),
// scene(run)} and is the only thing a card click touches, so another way of showing a metric's meaning (lane P's
// site/proposals/) replaces one entry of EXPLAINERS without touching the page. Every number shown comes from the run
// the Python side returned (the ruler's own numbers, and the arrays it derived with the ruler's functions); this file
// formats and draws, it computes no metric.

import {plot} from './plots.js';

const fmt = (v, digits = 3) => (v === null || v === undefined || Number.isNaN(v) ? '—' : (+v).toPrecision(digits));
const fixed = (v, digits = 2) => (v === null || v === undefined ? '—' : (+v).toFixed(digits));
const deg = (rad) => (rad * 180) / Math.PI;

function errorScale(run) {
  // errors are millimetres on a metre-sized arm: drawn exaggerated by a round factor, always labelled
  const max = Math.max(...run.explain.error_mm.filter((v) => v !== null), 0.05);
  const want = 90 / max; // the largest error drawn ~9 cm long: out past the arm's own radius
  return [10, 20, 50, 100, 200, 500].reduce((best, s) => (Math.abs(Math.log(s / want)) < Math.abs(Math.log(best / want)) ? s : best), 50);
}

function checkLine(run, id) {
  const pair = run.explain.checks[id];
  if (!pair) return '';
  const [ruler, drawn] = pair;
  const same = ruler === drawn || (typeof ruler === 'number' && typeof drawn === 'number' && Math.abs(ruler - drawn) <= 1e-9 * Math.max(1, Math.abs(ruler)));
  return same
    ? `<div class="check">✓ What is drawn reproduces the ruler's number (${fmt(drawn, 6)}).</div>`
    : `<div class="check bad">✗ The drawing gives ${fmt(drawn, 6)}, the ruler ${fmt(ruler, 6)}: this explanation is wrong.</div>`;
}

function zonesFromIntervals(intervals, cls) {
  return (intervals || []).map(([x0, x1]) => ({x0, x1: x1 + 0.00025, cls}));
}

function notMovingZones(run) {
  const {t, moving} = run.explain;
  const zones = [];
  let start = null;
  for (let i = 0; i < t.length; i++) {
    if (!moving[i] && start === null) start = i;
    if ((moving[i] || i === t.length - 1) && start !== null) {
      zones.push({x0: t[start], x1: t[moving[i] ? i - 1 : i] + 0.005, cls: 'zone-off'});
      start = null;
    }
  }
  return zones;
}

function bucketSeries(b, joint, transform = (v) => v) {
  const x = b.t;
  return {x, y0: b.min.map((row) => transform(row[joint])), y1: b.max.map((row) => transform(row[joint]))};
}

function maxOverJoints(b) {
  return b.max.map((row) => Math.max(...row));
}

function seriesAt(b, t) {
  // the bucket covering t: [joint values]
  let lo = 0;
  let hi = b.t.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (b.t[mid] <= t) lo = mid; else hi = mid; }
  return b.max[b.t[hi] <= t ? hi : lo];
}

const JOINT_BODY = (joint) => joint + 2; // joint j moves body j + 2 (0 world, 1 base, 2 shoulder_link, ...)

function useTint(THREE, css, usePct, failAt) {
  // per joint: arm colour -> purple as the use approaches failAt (%), red at or past it
  const tint = {};
  const high = new THREE.Color(css('--highlight'));
  const base = new THREE.Color(css('--accent')).lerp(new THREE.Color(css('--surface')), 0.35);
  usePct.forEach((pct, j) => {
    tint[JOINT_BODY(j)] = pct >= failAt ? new THREE.Color(css('--fail')) : base.clone().lerp(high, Math.min(1, pct / failAt) ** 1.5);
  });
  return tint;
}

// ── the objective ─────────────────────────────────────────────────────────────────────────────────────────

const toolTrack = {
  id: 'tool_track_rms_mm',
  name: 'tool_track_rms_mm',
  title: 'Tool tracking error (RMS)',
  unit: 'mm',
  objective: true,
  focus: 'tool',
  value: (run) => run.row.objective,
  verdict: () => null,
  rule: () => 'objective · lower is better',
  native: (row) => row?.objective,
  how(run) {
    const e = run.explain;
    const moving = e.moving.filter(Boolean).length;
    return `
      <p>At each of the task's <b>${e.t.length}</b> target samples (100 Hz) both joint vectors, the target's and the
      arm's measured joint angles at that same instant, go through the same forward kinematics to the tool point;
      the error is the distance between the two points.</p>
      <p>Only samples where the target moves count: <b>${moving}</b> of ${e.t.length} (target tool speed above 1 mm/s
      or any joint above 0.06 °/s). Rests are shaded and left out.</p>
      <div class="formula">rms = √( Σ e² / ${moving} ) = ${fmt(run.row.objective, 4)} mm</div>
      <p>The score of a solution is the median of this over the 42 dev tasks.</p>
      ${checkLine(run, 'tool_track_rms_mm')}`;
  },
  plot(host, run) {
    const e = run.explain;
    return plot(host, {
      x: [0, e.t[e.t.length - 1]], yLabel: 'tool error, mm', aria: 'tool error over time',
      zones: notMovingZones(run),
      series: [{x: e.t, y: e.error_mm.map((v, i) => (e.moving[i] ? v : null)), cls: 'line-highlight'},
        {x: e.t, y: e.error_mm.map((v, i) => (e.moving[i] ? null : v)), cls: 'line-target'}],
      rules: [{y: run.row.objective, cls: 'cursor', label: `RMS ${fmt(run.row.objective, 3)} mm`, labelCls: 'plot-value'}],
    });
  },
  scene(run) {
    const scale = errorScale(run);
    return {
      note: `Each line joins the target tool point to the measured one, ${scale}× longer than the error. Coloured: the moving samples the RMS counts; grey: rests.`,
      build({THREE, group, css}) {
        const e = run.explain;
        const positions = [];
        const colors = [];
        const max = Math.max(...e.error_mm.filter((v, i) => e.moving[i] && v !== null), 1e-9);
        const low = new THREE.Color(css('--line'));
        const high = new THREE.Color(css('--highlight'));
        const off = new THREE.Color(css('--target'));
        e.t.forEach((_, i) => {
          const a = e.tool_target[i];
          const b = e.tool[i];
          if (!b || b[0] === null) return;
          const tip = [a[0] + scale * (b[0] - a[0]), a[1] + scale * (b[1] - a[1]), a[2] + scale * (b[2] - a[2])];
          positions.push(...a, ...tip);
          const c = e.moving[i] ? low.clone().lerp(high, Math.min(1, e.error_mm[i] / max) ** 0.7) : off;
          colors.push(c.r, c.g, c.b, c.r, c.g, c.b);
        });
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
        group.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({vertexColors: true})));
        const tip = new THREE.Mesh(new THREE.SphereGeometry(0.006, 14, 10), new THREE.MeshBasicMaterial({color: high}));
        group.add(tip);
        return {
          update(t) {
            const i = Math.max(0, Math.min(e.t.length - 1, Math.round(t / (e.t[1] - e.t[0]))));
            const a = e.tool_target[i];
            const b = e.tool[i];
            if (b && b[0] !== null) tip.position.set(a[0] + scale * (b[0] - a[0]), a[1] + scale * (b[1] - a[1]), a[2] + scale * (b[2] - a[2]));
          },
        };
      },
    };
  },
};

// ── the gates ─────────────────────────────────────────────────────────────────────────────────────────────

const stopError = {
  id: 'stop_error_max_mm',
  name: 'stop_error_max_mm',
  title: 'Error at the stops',
  unit: 'mm',
  focus: 'tool',
  value: (run) => run.row.kpis.stop_error_max_mm,
  verdict: (run) => run.row.verdicts.stop_error_max_mm,
  rule: () => 'gate: ≤ 1.0 mm',
  native: (row) => row?.kpis?.stop_error_max_mm,
  how(run) {
    const stops = run.explain.stops;
    if (!stops.length) {
      return `<p>A stop is where the target rests for at least 0.2 s. This task has none, so the gate passes with 0 mm.</p>${checkLine(run, 'stop_error_max_mm')}`;
    }
    const list = stops.map((s, i) => `stop ${i + 1} (${fixed(s.t0)}–${fixed(s.t1)} s): ${fmt(s.error_mm, 3)} mm`).join('\n');
    return `
      <p>A stop is where the target rests for at least 0.2 s; this task has <b>${stops.length}</b>. For each, the ruler
      averages the measured tool point over the stop's last 0.1 s (shaded) and measures how far that mean is from
      the target point. The gate reads the worst stop.</p>
      <div class="formula">${list}\nmax = ${fmt(run.row.kpis.stop_error_max_mm, 4)} mm  (gate ≤ 1 mm)</div>
      ${checkLine(run, 'stop_error_max_mm')}`;
  },
  plot(host, run) {
    const e = run.explain;
    const hi = Math.max(1.15, ...e.error_mm.filter((v) => v !== null));
    return plot(host, {
      x: [0, e.t[e.t.length - 1]], y: [0, hi * 1.05], yLabel: 'tool error, mm',
      zones: e.stops.map((s) => ({x0: s.hold[0], x1: s.hold[1], cls: 'zone-hi'})),
      series: [{x: e.t, y: e.error_mm, cls: 'line-measured'}],
      rules: [{y: 1, cls: 'limit', label: '1 mm gate'}],
      dots: e.stops.map((s) => ({x: s.t1, y: s.error_mm, label: `${fmt(s.error_mm, 3)} mm`})),
    });
  },
  scene(run) {
    const scale = errorScale(run);
    return {
      note: `At each stop: the target point (grey) and the measured tool point averaged over the stop's last 0.1 s (purple), drawn ${scale}× its error away. The red bar is the 1 mm gate at the same scale.`,
      build({THREE, group, css, sphere, label}) {
        const stops = run.explain.stops;
        const worst = stops.reduce((best, stop) => (best === null || stop.error_mm > best.error_mm ? stop : best), null);
        const purple = new THREE.Color(css('--highlight'));
        for (const stop of stops) {
          const a = stop.target_xyz;
          const b = stop.mean_xyz;
          const tip = [a[0] + scale * (b[0] - a[0]), a[1] + scale * (b[1] - a[1]), a[2] + scale * (b[2] - a[2])];
          const target = sphere(0.005, new THREE.Color(css('--target')));
          target.position.set(...a);
          const mean = sphere(stop === worst ? 0.008 : 0.005, purple);
          mean.position.set(...tip);
          const join = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...tip)]);
          group.add(target, mean, new THREE.Line(join, new THREE.LineBasicMaterial({color: purple})));
        }
        if (worst) {
          // the worst stop is the gate's number; beside it, the gate itself as a bar of the same exaggerated scale
          const a = worst.target_xyz;
          const b = worst.mean_xyz;
          const tip = [a[0] + scale * (b[0] - a[0]), a[1] + scale * (b[1] - a[1]), a[2] + scale * (b[2] - a[2])];
          const text = label(`worst stop ${fmt(worst.error_mm, 3)} mm`, css('--highlight'));
          text.position.set(tip[0], tip[1], tip[2] + 0.03);
          const bar = 0.001 * scale; // 1 mm, exaggerated like the errors
          const start = new THREE.Vector3(a[0], a[1], a[2] - 0.035);
          const gate = new THREE.Line(new THREE.BufferGeometry().setFromPoints([start, start.clone().add(new THREE.Vector3(bar, 0, 0))]),
            new THREE.LineBasicMaterial({color: new THREE.Color(css('--fail'))}));
          const gateText = label(`1 mm gate (×${scale})`, css('--fail'));
          gateText.position.set(a[0] + bar / 2, a[1], a[2] - 0.055);
          group.add(text, gate, gateText);
        }
        return {};
      },
    };
  },
};

const saturation = {
  id: 'saturation_share_pct',
  name: 'saturation_share_pct',
  title: 'Torque saturation',
  unit: '%',
  value: (run) => run.row.kpis.saturation_share_pct,
  verdict: (run) => run.row.verdicts.saturation_share_pct,
  rule: () => 'gate: ≤ 2 % of samples',
  native: (row) => row?.kpis?.saturation_share_pct,
  how(run) {
    const e = run.explain;
    const per = e.saturated_per_joint.map((n, j) => `${e.joint_names[j].replace('_joint', '')}: ${n}`).join(', ');
    return `
      <p>Every physics sample counts, <b>${e.plant_samples.toLocaleString()}</b> of them at ${e.plant_rate_hz / 1000} kHz.
      A sample is saturated when any joint's torque is at least ${Math.round(100 * e.saturation_fraction)} % of its
      cap (${e.tau_cap.join(', ')} N·m).</p>
      <div class="formula">share = saturated / ${e.plant_samples} = ${fmt(run.row.kpis.saturation_share_pct, 3)} %  (gate ≤ 2 %)</div>
      <p>Saturated samples per joint: ${per}. The links tint when their joint is at the cap.</p>
      ${checkLine(run, 'saturation_share_pct')}`;
  },
  plot(host, run) {
    const e = run.explain;
    const peak = maxOverJoints(e.tau_use_pct);
    return plot(host, {
      x: [0, e.t[e.t.length - 1]], y: [0, Math.max(105, ...peak) * 1.04], yLabel: '|τ| / cap, %',
      title: 'the hardest-working joint, as % of its cap (each 5 ms bucket keeps its peak)',
      zones: zonesFromIntervals(e.saturated_intervals, 'zone-bad'),
      series: [{x: e.tau_use_pct.t, y: peak, cls: 'line-measured'}],
      rules: [{y: 100 * e.saturation_fraction, cls: 'limit', label: `${Math.round(100 * e.saturation_fraction)} % of cap`}],
    });
  },
  scene(run) {
    return {
      note: 'Each link is tinted by how hard its joint pushes, |τ| / cap: from its own colour (idle) to purple (near the cap); red at ≥ 98 %, a saturated sample.',
      build({THREE, viewer, css}) {
        const e = run.explain;
        return {
          update(t) {
            viewer.tint(useTint(THREE, css, seriesAt(e.tau_use_pct, t), 100 * e.saturation_fraction));
          },
          dispose() { viewer.tint(null); },
        };
      },
    };
  },
};

const limits = {
  id: 'limit_violations',
  name: 'limit_violations',
  title: 'Joint limits',
  unit: 'samples',
  value: (run) => run.row.kpis.limit_violations,
  verdict: (run) => run.row.verdicts.limit_violations,
  rule: () => 'gate: 0 samples',
  native: (row) => row?.kpis?.limit_violations,
  how(run) {
    const e = run.explain;
    const ranges = e.q_min.map((lo, j) => `${e.joint_names[j].replace('_joint', '')} ±${fixed(deg(e.q_max[j]), 0)}°, ${fixed(deg(e.qd_max[j]), 0)} °/s`).join('\n');
    const peakPos = Math.max(...maxOverJoints(e.position_use_pct));
    const peakVel = Math.max(...maxOverJoints(e.velocity_use_pct));
    return `
      <p>At every physics sample (${e.plant_samples.toLocaleString()}) each joint must stay inside its position range
      and below ${e.velocity_allowance} × its velocity limit. A sample with any joint outside counts once.</p>
      <div class="formula">${ranges}</div>
      <p>Closest this run came: <b>${fixed(peakPos, 1)} %</b> of a position range, <b>${fixed(peakVel, 1)} %</b> of an allowed speed.
      Violations: <b>${run.row.kpis.limit_violations}</b>.</p>
      ${checkLine(run, 'limit_violations')}`;
  },
  plot(host, run) {
    const e = run.explain;
    const pos = maxOverJoints(e.position_use_pct);
    const vel = maxOverJoints(e.velocity_use_pct);
    return plot(host, {
      x: [0, e.t[e.t.length - 1]], y: [0, Math.max(105, ...pos, ...vel) * 1.04], yLabel: '% of limit',
      zones: zonesFromIntervals(e.limit_intervals, 'zone-bad'),
      series: [{x: e.position_use_pct.t, y: pos, cls: 'line-target'}, {x: e.velocity_use_pct.t, y: vel, cls: 'line-measured'}],
      rules: [{y: 100, cls: 'limit', label: 'limit'}],
      title: 'worst joint: position (dashed) and speed (solid), as % of its limit',
    });
  },
  scene(run) {
    return {
      note: 'Each link is tinted by how close its joint is to a limit, position or speed (whichever is closer): purple as it nears it, red past it.',
      build({THREE, viewer, css}) {
        const e = run.explain;
        return {
          update(t) {
            const pos = seriesAt(e.position_use_pct, t);
            const vel = seriesAt(e.velocity_use_pct, t);
            viewer.tint(useTint(THREE, css, pos.map((p, j) => Math.max(p, vel[j])), 100));
          },
          dispose() { viewer.tint(null); },
        };
      },
    };
  },
};

const floor = {
  id: 'floor_clearance',
  name: 'floor_clearance',
  title: 'Floor clearance',
  unit: 'samples',
  value: (run) => run.row.kpis.floor_clearance_violations ?? run.row.kpis.floor_clearance,
  verdict: (run) => run.row.verdicts.floor_clearance,
  rule: () => 'gate: 0 samples below',
  native: (row) => row?.kpis?.floor_clearance_violations ?? row?.kpis?.floor_clearance,
  how(run) {
    const e = run.explain;
    const low = e.lowest;
    const fixedNames = Object.entries(low.fixed_points || {}).map(([i, z]) => `${e.point_names[i]} ${fixed(z, 3)} m`).join(', ');
    return `
      <p>The bare plant has no contacts, so the ruler checks geometry: at every physics sample, every body origin
      and the tool point must stay at or above the floor plane, z = ${e.floor_z} m under the base.</p>
      <p>Some points never change height (${fixedNames}). Of the ones that move, the arm came closest at
      <b>${fixed(low.t, 2)} s</b>: <b>${e.point_names[low.point]}</b> at <b>${fixed(100 * low.z, 1)} cm</b> above the floor.</p>
      <div class="formula">samples below z = ${e.floor_z}: ${floor.value(run)}  (gate: 0)</div>
      ${checkLine(run, 'floor_clearance')}`;
  },
  plot(host, run) {
    const e = run.explain;
    const lows = e.lowest_z.min.map((v) => v);
    return plot(host, {
      x: [0, e.t[e.t.length - 1]], y: [Math.min(-0.03, ...lows) * 1.1, Math.max(...lows) * 1.1], yLabel: 'lowest moving point, m',
      zones: zonesFromIntervals(e.floor_intervals, 'zone-bad'),
      series: [{x: e.lowest_z.t, y: lows, cls: 'line-measured'}],
      rules: [{y: e.floor_z, cls: 'limit', label: 'floor'}],
      dots: [{x: e.lowest.t, y: e.lowest.z, label: `${fixed(100 * e.lowest.z, 1)} cm`}],
    });
  },
  scene(run) {
    return {
      note: 'The floor plane is the gate. The purple point is the lowest moving point now, its line the gap to the floor.',
      build({THREE, group, css, sphere, label, viewer}) {
        const lows = run.render.lowest;
        const times = run.render.t;
        const plane = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 2.4),
          new THREE.MeshBasicMaterial({color: new THREE.Color(css('--highlight')), transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false}));
        const point = sphere(0.012, new THREE.Color(css('--highlight')));
        const drop = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
          new THREE.LineDashedMaterial({color: new THREE.Color(css('--highlight')), dashSize: 0.015, gapSize: 0.01}));
        let text = null;
        group.add(plane, point, drop);
        const lowest = run.explain.lowest;
        const ever = sphere(0.008, new THREE.Color(css('--highlight')), 0.45);
        ever.position.set(...lowest.xyz);
        group.add(ever);
        return {
          update(t) {
            const k = viewer.frameIndex(times, t);
            const p = lows[k];
            if (!p) return;
            point.position.set(p[0], p[1], p[2]);
            drop.geometry.setFromPoints([new THREE.Vector3(p[0], p[1], p[2]), new THREE.Vector3(p[0], p[1], 0)]);
            drop.computeLineDistances();
            if (text) { group.remove(text); text.material.map.dispose(); text.material.dispose(); }
            text = label(`${(100 * p[2]).toFixed(1)} cm`, css('--highlight'));
            text.position.set(p[0], p[1], p[2] / 2);
            group.add(text);
          },
        };
      },
    };
  },
};

const completed = {
  id: 'completed',
  name: 'completed',
  title: 'Completed',
  unit: '',
  focus: 'tool',
  value: (run) => run.row.kpis.completed,
  verdict: (run) => run.row.verdicts.completed,
  rule: () => 'gate: ran to the end and settled',
  native: (row) => row?.kpis?.completed,
  how(run) {
    const d = run.row.diagnostics || {};
    const notes = (run.row.notes || []).filter((n) => !/watchdog/.test(n));
    const items = [
      ['the build and every tick raised nothing, no command was NaN or infinite', !notes.some((n) => /raised|non-finite|abort|load/.test(n))],
      ['the physics did not diverge and the run reached the trajectory\'s end', !notes.some((n) => /diverged|did not reach/.test(n))],
      [`it settled: worst tool error over the last 0.1 s = ${fmt(d.settle_error_max_mm, 3)} mm (≤ 1 mm)`, d.settle_error_max_mm !== null && d.settle_error_max_mm <= 1],
      ['it stayed inside the time box (10 × the trajectory\'s duration of wall time)', !notes.some((n) => /time box/.test(n))],
    ];
    return `
      <p>A crash is not a score. A task is completed only if all of these hold:</p>
      <div class="formula">${items.map(([text, ok]) => `${ok ? '✓' : '✗'} ${text}`).join('\n')}</div>
      ${notes.length ? `<p>Notes from the ruler: ${notes.map((n) => `<code>${n}</code>`).join(' ')}</p>` : ''}`;
  },
  plot(host, run) {
    const e = run.explain;
    const end = e.t[e.t.length - 1];
    return plot(host, {
      x: [0, end], y: [0, Math.max(1.2, ...e.error_mm.filter((v) => v !== null)) * 1.05], yLabel: 'tool error, mm',
      zones: [{x0: end - 0.1, x1: end + 0.01, cls: 'zone-hi'}],
      series: [{x: e.t, y: e.error_mm, cls: 'line-measured'}],
      rules: [{y: 1, cls: 'limit', label: 'settle band 1 mm'}],
      dots: [{x: end, y: e.error_mm[e.error_mm.length - 1], label: `${fmt(e.error_mm[e.error_mm.length - 1], 3)} mm at the end`}],
    });
  },
  scene() {
    return {note: 'Completed reads the whole run: scrub to the end to see the arm settle on the target.'};
  },
};

export const EXPLAINERS = [toolTrack, completed, stopError, saturation, limits, floor];
export {fmt, fixed, deg};
