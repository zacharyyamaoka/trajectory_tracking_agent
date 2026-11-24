// How each score is computed, shown: one explainer per score card.
//
// An explainer is {id, name, unit, value(run), verdict(run), rule(run), how(run), plot(host, run), scene(run)} and is
// the only thing a card click touches, so another way of showing a metric's meaning (lane P's site/proposals/)
// replaces one entry of EXPLAINERS without touching the page. `run` is a saved run (assets/playback.js): every number
// on a card is the ruler's own, from the run record; the arrays drawn were computed natively at build time with the
// ruler's functions (tools/build_site.py). This file formats and draws; it computes no metric. The only arithmetic
// here is display: radians to degrees, a torque or joint state as a % of its cap or limit, an error drawn N x longer.

import {plot} from './plots.js';

const fmt = (v, digits = 3) => (v === null || v === undefined || Number.isNaN(v) ? '—' : (+v).toPrecision(digits));
const fixed = (v, digits = 2) => (v === null || v === undefined ? '—' : (+v).toFixed(digits));
const deg = (rad) => (rad * 180) / Math.PI;
const end = (run) => run.t[run.t.length - 1];
const kHz = (run) => `${run.dep.plant_rate_hz / 1000} kHz`;

function errorScale(run) {
  // errors are millimetres on a metre-sized arm: drawn exaggerated by a round factor, always labelled
  const max = Math.max(...run.error_mm.filter((v) => v !== null), 0.05);
  const want = 90 / max; // the largest error drawn ~9 cm long: out past the arm's own radius
  return [10, 20, 50, 100, 200, 500].reduce((best, s) => (Math.abs(Math.log(s / want)) < Math.abs(Math.log(best / want)) ? s : best), 50);
}

function checkLine(run, id) {
  // the ruler's function, re-run at build time on the record's saved samples, against the number the ruler scored
  const c = run.explain.checks[id];
  if (!c) return '';
  return c.ok
    ? `<div class="check">✓ The ruler's function on the record's saved samples gives ${fmt(c.record, 6)} mm; it scored
       ${fmt(c.ruler, 6)} mm (equal within ${c.tolerance} mm: the record keeps positions to 0.1 µm).</div>`
    : `<div class="check bad">✗ The saved samples give ${fmt(c.record, 6)}, the ruler ${fmt(c.ruler, 6)}: this drawing is wrong.</div>`;
}

function subsetLine(run, id, noun) {
  // the violation gates read every 4 kHz physics sample; the record keeps the 100 Hz ones, every 40th of them
  const s = run.explain.subset[id];
  if (!s) return '';
  const every = Math.round(run.dep.plant_rate_hz / run.dep.record_rate_hz);
  const bad = s.consistent === false;
  return `<div class="check${bad ? ' bad' : ''}">${bad ? '✗' : '✓'} The ruler counted all ${kHz(run)} physics samples of the run.
    The record keeps every ${every}th (${run.t.length} samples at 100 Hz), and those are what is drawn here: ${s.record_samples}
    of them ${noun}, ${bad ? 'which the ruler\'s count contradicts: this drawing is wrong' : 'consistent with the ruler\'s count'}.</div>`;
}

function zonesFromIntervals(intervals, cls) {
  return (intervals || []).map(([x0, x1]) => ({x0, x1: x1 + 0.005, cls}));
}

function notMovingZones(run) {
  const {t, moving} = run;
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

function frameAt(run, t) {
  // the last saved sample at or before t
  const dt = run.t[1] - run.t[0];
  return Math.max(0, Math.min(run.t.length - 1, Math.floor((t - run.t[0]) / dt + 1e-6)));
}

// display only: each joint's |torque| / cap, distance to a position limit, |speed| / allowed speed, in %
const torqueUse = (run, k) => (run.tau[k] ? run.tau[k].map((v, j) => (100 * Math.abs(v)) / run.dep.tau_cap[j]) : null);
const positionUse = (run, k) => (run.q[k] ? run.q[k].map((v, j) => {
  const mid = 0.5 * (run.dep.q_max[j] + run.dep.q_min[j]);
  const half = 0.5 * (run.dep.q_max[j] - run.dep.q_min[j]);
  return (100 * Math.abs(v - mid)) / half;
}) : null);
const velocityUse = (run, k) => (run.qd[k] ? run.qd[k].map((v, j) => (100 * Math.abs(v)) / (run.dep.velocity_allowance * run.dep.qd_max[j])) : null);
const worst = (run, use) => run.t.map((_, k) => { const u = use(run, k); return u ? Math.max(...u) : null; });

const JOINT_BODY = (joint) => joint + 2; // joint j moves body j + 2 (0 world, 1 base, 2 shoulder_link, ...)

function useTint(THREE, css, usePct, failAt) {
  // per joint: arm colour -> purple as the use approaches failAt (%), red at or past it
  const tint = {};
  if (!usePct) return tint;
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
  value: (run) => run.metrics.tool_track_rms_mm,
  verdict: () => null,
  rule: () => 'objective · lower is better',
  how(run) {
    const moving = run.explain.moving_samples;
    return `
      <p>At each of the task's <b>${run.t.length}</b> target samples (100 Hz) both joint vectors, the target's and the
      arm's measured joint angles at that same instant, go through the same forward kinematics to the tool point;
      the error is the distance between the two points.</p>
      <p>Only samples where the target moves count: <b>${moving}</b> of ${run.t.length} (target tool speed above 1 mm/s
      or any joint above 0.06 °/s). Rests are shaded and left out.</p>
      <div class="formula">rms = √( Σ e² / ${moving} ) = ${fmt(run.metrics.tool_track_rms_mm, 4)} mm</div>
      <p>The score of a solution is the median of this over the 42 dev tasks.</p>
      ${checkLine(run, 'tool_track_rms_mm')}`;
  },
  plot(host, run) {
    return plot(host, {
      x: [0, end(run)], yLabel: 'tool error, mm', aria: 'tool error over time',
      zones: notMovingZones(run),
      series: [{x: run.t, y: run.error_mm.map((v, i) => (run.moving[i] ? v : null)), cls: 'line-highlight'},
        {x: run.t, y: run.error_mm.map((v, i) => (run.moving[i] ? null : v)), cls: 'line-target'}],
      rules: [{y: run.metrics.tool_track_rms_mm, cls: 'cursor', label: `RMS ${fmt(run.metrics.tool_track_rms_mm, 3)} mm`, labelCls: 'plot-value'}],
    });
  },
  scene(run) {
    const scale = errorScale(run);
    return {
      note: `Each line joins the target tool point to the measured one, ${scale}× longer than the error. Coloured: the moving samples the RMS counts; grey: rests.`,
      build({THREE, group, css}) {
        const positions = [];
        const colors = [];
        const max = Math.max(...run.error_mm.filter((v, i) => run.moving[i] && v !== null), 1e-9);
        const low = new THREE.Color(css('--line'));
        const high = new THREE.Color(css('--highlight'));
        const off = new THREE.Color(css('--target'));
        const tipOf = (i) => {
          const a = run.tool_target[i];
          const b = run.tool[i];
          return b ? [a[0] + scale * (b[0] - a[0]), a[1] + scale * (b[1] - a[1]), a[2] + scale * (b[2] - a[2])] : null;
        };
        run.t.forEach((_, i) => {
          const tip = tipOf(i);
          if (!tip) return;
          positions.push(...run.tool_target[i], ...tip);
          const c = run.moving[i] ? low.clone().lerp(high, Math.min(1, run.error_mm[i] / max) ** 0.7) : off;
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
            const p = tipOf(frameAt(run, t));
            if (p) tip.position.set(...p);
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
  value: (run) => run.metrics.stop_error_max_mm,
  verdict: (run) => run.gates.stop_error_max_mm,
  rule: () => 'gate: ≤ 1.0 mm',
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
      <div class="formula">${list}\nmax = ${fmt(run.metrics.stop_error_max_mm, 4)} mm  (gate ≤ 1 mm)</div>
      ${checkLine(run, 'stop_error_max_mm')}`;
  },
  plot(host, run) {
    const hi = Math.max(1.15, ...run.error_mm.filter((v) => v !== null));
    return plot(host, {
      x: [0, end(run)], y: [0, hi * 1.05], yLabel: 'tool error, mm',
      zones: run.explain.stops.map((s) => ({x0: s.hold[0], x1: s.hold[1], cls: 'zone-hi'})),
      series: [{x: run.t, y: run.error_mm, cls: 'line-measured'}],
      rules: [{y: 1, cls: 'limit', label: '1 mm gate'}],
      dots: run.explain.stops.map((s) => ({x: s.t1, y: s.error_mm, label: `${fmt(s.error_mm, 3)} mm`})),
    });
  },
  scene(run) {
    const scale = errorScale(run);
    return {
      note: `At each stop: the target point (grey) and the measured tool point averaged over the stop's last 0.1 s (purple), drawn ${scale}× its error away. The red bar is the 1 mm gate at the same scale.`,
      build({THREE, group, css, sphere, label}) {
        const stops = run.explain.stops;
        const worstStop = stops.reduce((best, stop) => (best === null || stop.error_mm > best.error_mm ? stop : best), null);
        const purple = new THREE.Color(css('--highlight'));
        for (const stop of stops) {
          const a = stop.target_xyz;
          const b = stop.mean_xyz;
          const tip = [a[0] + scale * (b[0] - a[0]), a[1] + scale * (b[1] - a[1]), a[2] + scale * (b[2] - a[2])];
          const target = sphere(0.005, new THREE.Color(css('--target')));
          target.position.set(...a);
          const mean = sphere(stop === worstStop ? 0.008 : 0.005, purple);
          mean.position.set(...tip);
          const join = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...tip)]);
          group.add(target, mean, new THREE.Line(join, new THREE.LineBasicMaterial({color: purple})));
        }
        if (worstStop) {
          // the worst stop is the gate's number; beside it, the gate itself as a bar of the same exaggerated scale
          const a = worstStop.target_xyz;
          const b = worstStop.mean_xyz;
          const tip = [a[0] + scale * (b[0] - a[0]), a[1] + scale * (b[1] - a[1]), a[2] + scale * (b[2] - a[2])];
          const text = label(`worst stop ${fmt(worstStop.error_mm, 3)} mm`, css('--highlight'));
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
  value: (run) => run.metrics.saturation_share_pct,
  verdict: (run) => run.gates.saturation_share_pct,
  rule: () => 'gate: ≤ 2 % of samples',
  how(run) {
    const fraction = Math.round(100 * run.dep.saturation_fraction);
    const per = run.explain.saturated_per_joint.map((n, j) => `${run.dep.joint_names[j].replace('_joint', '')}: ${n}`).join(', ');
    return `
      <p>The ruler reads every physics sample of the run (${kHz(run)}). A sample is saturated when any joint's torque is
      at least ${fraction} % of its cap (${run.dep.tau_cap.join(', ')} N·m).</p>
      <div class="formula">share = saturated samples / all samples = ${fmt(run.metrics.saturation_share_pct, 3)} %  (gate ≤ 2 %)</div>
      <p>Saturated samples per joint, in the record's 100 Hz samples: ${per}. The links tint when their joint is at the cap.</p>
      ${subsetLine(run, 'saturation_share_pct', 'saturated')}`;
  },
  plot(host, run) {
    const peak = worst(run, torqueUse);
    const fraction = 100 * run.dep.saturation_fraction;
    return plot(host, {
      x: [0, end(run)], y: [0, Math.max(105, ...peak.filter((v) => v !== null)) * 1.04], yLabel: '|τ| / cap, %',
      title: 'the hardest-working joint, as % of its cap (the record\'s 100 Hz samples)',
      zones: zonesFromIntervals(run.explain.saturated_intervals, 'zone-bad'),
      series: [{x: run.t, y: peak, cls: 'line-measured'}],
      rules: [{y: fraction, cls: 'limit', label: `${Math.round(fraction)} % of cap`}],
    });
  },
  scene(run) {
    return {
      note: 'Each link is tinted by how hard its joint pushes, |τ| / cap: from its own colour (idle) to purple (near the cap); red at ≥ 98 %, a saturated sample.',
      build({THREE, viewer, css}) {
        return {
          update(t) { viewer.tint(useTint(THREE, css, torqueUse(run, frameAt(run, t)), 100 * run.dep.saturation_fraction)); },
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
  value: (run) => run.metrics.limit_violations,
  verdict: (run) => run.gates.limit_violations,
  rule: () => 'gate: 0 samples',
  how(run) {
    const d = run.dep;
    const ranges = d.q_min.map((lo, j) => `${d.joint_names[j].replace('_joint', '')} ${fixed(deg(lo), 0)}° … ${fixed(deg(d.q_max[j]), 0)}°, ${fixed(deg(d.qd_max[j]), 0)} °/s`).join('\n');
    const peakPos = Math.max(...worst(run, positionUse).filter((v) => v !== null));
    const peakVel = Math.max(...worst(run, velocityUse).filter((v) => v !== null));
    return `
      <p>At every physics sample (${kHz(run)}) each joint must stay inside its position range and below
      ${d.velocity_allowance} × its velocity limit. A sample with any joint outside counts once.</p>
      <div class="formula">${ranges}</div>
      <p>Closest in the record's 100 Hz samples: <b>${fixed(peakPos, 1)} %</b> of a position range, <b>${fixed(peakVel, 1)} %</b>
      of an allowed speed. Violations the ruler counted: <b>${run.metrics.limit_violations}</b>.</p>
      ${subsetLine(run, 'limit_violations', 'with a joint outside a limit')}`;
  },
  plot(host, run) {
    const pos = worst(run, positionUse);
    const vel = worst(run, velocityUse);
    return plot(host, {
      x: [0, end(run)], y: [0, Math.max(105, ...pos.filter((v) => v !== null), ...vel.filter((v) => v !== null)) * 1.04], yLabel: '% of limit',
      zones: zonesFromIntervals(run.explain.limit_intervals, 'zone-bad'),
      series: [{x: run.t, y: pos, cls: 'line-target'}, {x: run.t, y: vel, cls: 'line-measured'}],
      rules: [{y: 100, cls: 'limit', label: 'limit'}],
      title: 'worst joint: position (dashed) and speed (solid), as % of its limit',
    });
  },
  scene(run) {
    return {
      note: 'Each link is tinted by how close its joint is to a limit, position or speed (whichever is closer): purple as it nears it, red past it.',
      build({THREE, viewer, css}) {
        return {
          update(t) {
            const k = frameAt(run, t);
            const pos = positionUse(run, k);
            const vel = velocityUse(run, k);
            viewer.tint(useTint(THREE, css, pos && vel ? pos.map((p, j) => Math.max(p, vel[j])) : null, 100));
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
  value: (run) => run.metrics.floor_clearance_violations,
  verdict: (run) => run.gates.floor_clearance,
  rule: () => 'gate: 0 samples below',
  how(run) {
    const low = run.explain.lowest;
    const names = run.point_names;
    const fixedNames = Object.entries(low.fixed_points || {}).map(([i, z]) => `${names[i]} ${fixed(z, 3)} m`).join(', ');
    return `
      <p>The bare plant has no contacts, so the ruler checks geometry: at every physics sample (${kHz(run)}), every body
      origin and the tool point must stay at or above the floor plane, z = ${run.dep.floor_z} m under the base.</p>
      <p>Some points never change height (${fixedNames}). Of the ones that move, the arm came closest, in the record's
      100 Hz samples, at <b>${fixed(low.t, 2)} s</b>: <b>${names[low.point]}</b> at <b>${fixed(100 * low.z, 1)} cm</b> above the floor.</p>
      <div class="formula">samples below z = ${run.dep.floor_z}: ${floor.value(run)}  (gate: 0)</div>
      ${subsetLine(run, 'floor_clearance', 'with a point below the floor')}`;
  },
  plot(host, run) {
    const lows = run.lowest.map((p) => (p ? p[2] : null));
    const finite = lows.filter((v) => v !== null);
    return plot(host, {
      x: [0, end(run)], y: [Math.min(-0.03, ...finite) * 1.1, Math.max(...finite) * 1.1], yLabel: 'lowest moving point, m',
      zones: zonesFromIntervals(run.explain.floor_intervals, 'zone-bad'),
      series: [{x: run.t, y: lows, cls: 'line-measured'}],
      rules: [{y: run.dep.floor_z, cls: 'limit', label: 'floor'}],
      dots: [{x: run.explain.lowest.t, y: run.explain.lowest.z, label: `${fixed(100 * run.explain.lowest.z, 1)} cm`}],
    });
  },
  scene(run) {
    return {
      note: 'The floor plane is the gate. The purple point is the lowest moving point now, its line the gap to the floor.',
      build({THREE, group, css, sphere, label}) {
        const plane = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 2.4),
          new THREE.MeshBasicMaterial({color: new THREE.Color(css('--highlight')), transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false}));
        const point = sphere(0.012, new THREE.Color(css('--highlight')));
        const drop = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
          new THREE.LineDashedMaterial({color: new THREE.Color(css('--highlight')), dashSize: 0.015, gapSize: 0.01}));
        let text = null;
        group.add(plane, point, drop);
        const ever = sphere(0.008, new THREE.Color(css('--highlight')), 0.45);
        ever.position.set(...run.explain.lowest.xyz);
        group.add(ever);
        return {
          update(t) {
            const p = run.lowest[frameAt(run, t)];
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
  value: (run) => run.metrics.completed,
  verdict: (run) => run.gates.completed,
  rule: () => 'gate: ran to the end and settled',
  how(run) {
    const m = run.metrics;
    const notes = (run.notes || []).filter((n) => !/watchdog/.test(n));
    const items = [
      ['the build and every tick raised nothing, no command was NaN or infinite', !notes.some((n) => /raised|non-finite|abort|load/.test(n))],
      ['the physics did not diverge and the run reached the trajectory\'s end', !notes.some((n) => /diverged|did not reach/.test(n))],
      [`it settled: worst tool error over the last 0.1 s = ${fmt(m.settle_error_max_mm, 3)} mm (≤ 1 mm)`, m.settle_error_max_mm !== null && m.settle_error_max_mm <= 1],
      ['it stayed inside the time box (10 × the trajectory\'s duration of wall time)', !notes.some((n) => /time box/.test(n))],
    ];
    return `
      <p>A crash is not a score. A task is completed only if all of these hold:</p>
      <div class="formula">${items.map(([text, ok]) => `${ok ? '✓' : '✗'} ${text}`).join('\n')}</div>
      ${notes.length ? `<p>Notes from the ruler: ${notes.map((n) => `<code>${n}</code>`).join(' ')}</p>` : ''}`;
  },
  plot(host, run) {
    const last = run.error_mm[run.error_mm.length - 1];
    return plot(host, {
      x: [0, end(run)], y: [0, Math.max(1.2, ...run.error_mm.filter((v) => v !== null)) * 1.05], yLabel: 'tool error, mm',
      zones: [{x0: end(run) - 0.1, x1: end(run) + 0.01, cls: 'zone-hi'}],
      series: [{x: run.t, y: run.error_mm, cls: 'line-measured'}],
      rules: [{y: 1, cls: 'limit', label: 'settle band 1 mm'}],
      dots: last === null ? [] : [{x: end(run), y: last, label: `${fmt(last, 3)} mm at the end`}],
    });
  },
  scene() {
    return {note: 'Completed reads the whole run: scrub to the end to see the arm settle on the target.'};
  },
};

export const EXPLAINERS = [toolTrack, completed, stopError, saturation, limits, floor];
export {fmt, fixed, deg};
