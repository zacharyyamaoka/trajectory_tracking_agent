// The landing page: wires the worker (Python + MuJoCo), the 3D view, the score cards and their explanations, the
// joint plots, the code view and the population. It formats and draws; every number comes from the Python side.

import {createViewer} from './viewer3d.js';
import {EXPLAINERS, fmt, deg} from './explain.js';
import {plot} from './plots.js';

const $ = (id) => document.getElementById(id);
const REPO_URL = 'https://github.com/zacharyyamaoka/trajectory_tracking_agent';
const HLJS = 'https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/es/core.min.js';
const HLJS_PY = 'https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/es/languages/python.min.js';
const DEFAULT_TASK = 'workspace-dev-001'; // the ISO 9283 cube: a path anyone recognises

const state = {
  page: null,
  manifest: null,
  viewer: null,
  run: null,          // the last run's result
  preview: null,
  selected: 'tool_track_rms_mm',
  playing: false,
  duration: 1,
  time: 0,
  explainPlot: null,
  jointPlots: [],
  jointView: 'position',
  busy: false,
};
window.__page = state; // for the headless checks (tools/build_site.py shoot)

// ── the worker ────────────────────────────────────────────────────────────────────────────────────────────

const worker = new Worker(new URL('../runtime/worker.js', import.meta.url), {type: 'module'});
const pending = new Map();
let nextId = 1;
worker.onmessage = (event) => {
  const message = event.data;
  if (message.status) setBoot(message.status);
  if (message.fatal) setStatus(`<b>Could not start the runtime.</b> ${escapeHtml(message.status || '')}`);
  if (message.id && pending.has(message.id)) {
    const {resolve, reject} = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error)); else resolve(message.result);
  }
};
function call(name, kwargs) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, {resolve, reject});
    worker.postMessage({id, call: name, kwargs});
  });
}

// ── small helpers ─────────────────────────────────────────────────────────────────────────────────────────

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
}
function setStatus(html) { $('status').innerHTML = html; }
function setBoot(text) {
  $('boot-text').textContent = text;
  if (!state.run) setStatus(escapeHtml(text));
}
function solutionMeta(id) { return state.page.solutions.find((s) => s.id === id); }
function taskMeta(id) { return state.page.tasks.find((t) => t.id === id); }

// ── the hero: selection, run, playback ────────────────────────────────────────────────────────────────────

function fillSelects() {
  const {leaderboard, solutions, tasks} = state.page;
  const params = new URLSearchParams(location.search);
  const ranked = leaderboard.rows.map((row) => row.id);
  const order = [...ranked, ...solutions.map((s) => s.id).filter((id) => !ranked.includes(id))];
  $('solution').innerHTML = order.map((id) => {
    const row = leaderboard.rows.find((r) => r.id === id);
    const score = row && row.objective !== null && row.objective !== undefined ? ` · ${fmt(row.objective, 3)} mm` : '';
    const mark = id === leaderboard.best ? ' (best)' : '';
    return `<option value="${id}">${id}${mark}${score}</option>`;
  }).join('');
  $('task').innerHTML = tasks.map((t) => `<option value="${t.id}">${t.id.replace('workspace-', '')} · ${t.kind.replaceAll('_', ' ')} · ${t.duration_s?.toFixed(2)} s</option>`).join('');
  const solution = params.get('solution') || leaderboard.best || (order.includes('p2') ? 'p2' : order[0]);
  $('solution').value = order.includes(solution) ? solution : order[0];
  $('task').value = tasks.some((t) => t.id === params.get('task')) ? params.get('task') : DEFAULT_TASK;
}

function verdictLine() {
  const {leaderboard, status} = state.page;
  if (!leaderboard.scored) {
    $('verdict').innerHTML = 'No solution scored yet: the population is being evaluated. You can still run any solution below.';
    return;
  }
  const best = leaderboard.rows.find((r) => r.id === leaderboard.best);
  if (best) {
    const others = leaderboard.rows.length;
    $('verdict').innerHTML = `Best admissible solution: <b>${best.id}</b>, <b>${fmt(best.objective, 3)} mm</b> tool tracking error
      (median over the 42 dev tasks), out of ${others} solution${others === 1 ? '' : 's'} scored.`;
  } else {
    const top = leaderboard.rows[0];
    $('verdict').innerHTML = `No solution passes every gate yet. Closest: <b>${top.id}</b>, ${fmt(100 * (top.gate_pass_rate ?? 0), 3)} % of gate checks passed.`;
  }
  const gates = ['completed', 'stop_error_max_mm', 'saturation_share_pct', 'limit_violations', 'floor_clearance'];
  if (!best && gates.includes(status?.kpi?.next_gate)) $('verdict').innerHTML += ` The gate failing most: <code>${status.kpi.next_gate}</code>.`;
}

function fitPoints(preview) {
  // the arm's body origins over the whole clip, every fifth frame, plus the tool path
  const frames = preview.render.target.body_xpos.filter((_, k) => k % 5 === 0).flat();
  return [...frames, ...preview.tool_target];
}

async function showPreview(taskId) {
  const preview = await call('preview', {task_id: taskId});
  state.preview = preview;
  if (!state.viewer) return;
  state.viewer.setGeoms(preview.render.geoms);
  state.viewer.setArm('target', preview.render.target, preview.render.t);
  state.viewer.setArm('measured', null, []);
  state.viewer.setPaths({target: preview.tool_target});
  state.viewer.fit(fitPoints(preview));
  setDuration(preview.task.duration_s);
  setTime(0);
  play(true);
}

async function runSelected() {
  if (state.busy) return;
  state.busy = true;
  const solution = $('solution').value;
  const task = $('task').value;
  history.replaceState(null, '', `?solution=${encodeURIComponent(solution)}&task=${encodeURIComponent(task)}`);
  $('run-button').disabled = true;
  const meta = solutionMeta(solution);
  const calibrated = (meta?.tags || []).some((tag) => tag === 'lookahead=calibrated');
  setStatus(`Running <b>${solution}</b> on <b>${task}</b> in your browser…${calibrated ? ' (it calibrates the bus first: two extra episodes)' : ''}`);
  try {
    state.run = null;
    if (!state.preview || state.preview.task.id !== task) await showPreview(task);
    else state.viewer?.setArm('measured', null, []);
    const started = performance.now();
    const run = await call('run', {solution_id: solution, task_id: task});
    state.run = run;
    state.run.browser.total_s = (performance.now() - started) / 1000;
    showRun(run);
  } catch (error) {
    setStatus(`<b>The run failed.</b> ${escapeHtml(error.message).slice(0, 600)}`);
    console.error(error);
  } finally {
    state.busy = false;
    $('run-button').disabled = false;
  }
}

function showRun(run) {
  const viewer = state.viewer;
  if (viewer && run.render) {
    viewer.setGeoms(run.render.geoms);
    viewer.setArm('target', run.render.target, run.render.t);
    viewer.setArm('measured', run.render.measured, run.render.t);
    viewer.setPaths({target: run.explain.tool_target, measured: run.explain.tool.filter((p) => p && p[0] !== null)});
  }
  setDuration(run.explain ? run.explain.t[run.explain.t.length - 1] : 1);
  const row = run.row;
  const pass = Object.values(row.verdicts).every(Boolean);
  setStatus(`<b>${run.setup.solution}</b> on <b>${run.setup.task}</b>: ${fmt(row.objective, 4)} mm tool tracking RMS,
    ${pass ? 'every gate passed' : `failed: ${Object.entries(row.verdicts).filter(([, ok]) => !ok).map(([gate]) => gate).join(', ')}`}.
    Ran in ${run.wall.run_task_s.toFixed(1)} s.`);
  const r = run.runtime;
  $('ran').innerHTML = `Ran here: Python ${r.python} (Pyodide ${state.manifest.pyodide}), numpy ${r.numpy}, MuJoCo ${r.mujoco} (WebAssembly),
    robot_controllers ${r.robot_controllers}, robot_msgs ${r.robot_msgs}. Host tick p95: ${fmt(run.host_compute_ms.p95, 2)} ms.`;
  renderCards();
  select(state.selected);
  renderJoints();
  renderRanList();
  setTime(0);
  play(true);
}

function setDuration(seconds) {
  state.duration = Math.max(0.01, seconds);
  $('scrub').max = String(state.duration);
  $('scrub').disabled = false;
  $('play').disabled = false;
}

function setTime(t) {
  state.time = Math.max(0, Math.min(state.duration, t));
  $('scrub').value = String(state.time);
  $('time').textContent = `${state.time.toFixed(2)} s`;
  state.viewer?.setTime(state.time);
  state.explainPlot?.cursor(state.time);
  for (const p of state.jointPlots) p.cursor(state.time);
}

let lastFrame = null;
function animate(now) {
  if (state.playing) {
    const dt = lastFrame === null ? 0 : (now - lastFrame) / 1000;
    let t = state.time + dt;
    if (t > state.duration + 0.6) t = 0; // a short hold on the final pose, then loop
    setTime(Math.min(t, state.duration));
    if (t > state.duration) state.time = t;
  }
  lastFrame = now;
  requestAnimationFrame(animate);
}

function play(on = !state.playing) {
  state.playing = on;
  $('play').textContent = on ? '❚❚' : '▶';
}

// ── score cards and their explanations ────────────────────────────────────────────────────────────────────

function cardValue(explainer, run) {
  const value = explainer.value(run);
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (value === null || value === undefined) return '—';
  if (Number.isInteger(value)) return String(value);
  return fmt(value, 3);
}

function renderCards() {
  const run = state.run;
  const native = solutionMeta(run.setup.solution)?.native?.[run.setup.task];
  $('cards').innerHTML = EXPLAINERS.map((ex) => {
    const verdict = ex.verdict(run);
    const chip = ex.objective ? '<span class="chip info">objective</span>'
      : verdict ? '<span class="chip pass">pass</span>' : '<span class="chip fail">fail</span>';
    const nativeValue = ex.native(native);
    const nativeText = native === undefined ? 'native scorecard: not scored yet'
      : `native scorecard: ${typeof nativeValue === 'boolean' ? (nativeValue ? 'yes' : 'no') : fmt(nativeValue, 4)}`;
    return `<button class="card${ex.objective ? ' objective' : ''}" data-id="${ex.id}" aria-pressed="false">
      <span class="name">${ex.name}</span>
      <span class="value">${cardValue(ex, run)}<small>${ex.unit && typeof ex.value(run) !== 'boolean' ? ` ${ex.unit}` : ''}</small></span>
      <span class="rule">${ex.rule(run)}</span>
      ${chip}
      <span class="native" title="The same solution and task in its committed scorecard, scored by native CPython and MuJoCo. The ruler is deterministic, so the two agree to about 1e-13 (runtime/parity.html).">${nativeText}</span>
    </button>`;
  }).join('');
  for (const card of $('cards').querySelectorAll('.card')) card.addEventListener('click', () => select(card.dataset.id));
}

function select(id) {
  state.selected = id;
  const run = state.run;
  if (!run) return;
  const ex = EXPLAINERS.find((e) => e.id === id) || EXPLAINERS[0];
  for (const card of $('cards').querySelectorAll('.card')) card.setAttribute('aria-pressed', String(card.dataset.id === ex.id));
  $('explain-title').textContent = `${ex.title}: ${cardValue(ex, run)}${ex.unit && typeof ex.value(run) !== 'boolean' ? ` ${ex.unit}` : ''}`;
  $('explain-how').innerHTML = ex.how(run);
  state.explainPlot = ex.plot($('explain-plot'), run);
  state.explainPlot.onSeek?.((t) => { play(false); setTime(t); });
  state.explainPlot.cursor(state.time);
  state.viewer?.setOverlay(ex.scene(run));
  frame(ex.focus);
  state.viewer?.setTime(state.time);
}

function frame(focus) {
  // where the camera looks: the tool's work (its target path, with room for the drawn errors) or the whole arm
  const viewer = state.viewer;
  const source = state.run?.render ? {render: state.run.render, tool_target: state.run.explain.tool_target} : state.preview;
  if (!viewer || !source) return;
  viewer.see(focus === 'tool');
  if (focus === 'tool') viewer.fit(source.tool_target, {minRadius: 0.18, scale: 1.5});
  else viewer.fit(fitPoints(source));
}

// ── joints ────────────────────────────────────────────────────────────────────────────────────────────────

function renderJoints() {
  const run = state.run;
  const e = run?.explain;
  if (!e) return;
  const end = e.t[e.t.length - 1];
  state.jointPlots = [];
  $('joint-plots').innerHTML = e.joint_names.map((name, j) => `<div class="joint"><h4>${name}<span id="jv${j}"></span></h4><div id="jp${j}"></div></div>`).join('');
  e.joint_names.forEach((name, j) => {
    const host = $(`jp${j}`);
    let p;
    if (state.jointView === 'position') {
      p = plot(host, {x: [0, end], height: 150, yLabel: 'deg', series: [
        {x: e.t, y: e.q_target.map((q) => deg(q[j])), cls: 'line-target'},
        {x: e.t, y: e.q.map((q) => (q[j] === null ? null : deg(q[j]))), cls: 'line-measured'}]});
      const range = e.q_target.map((q) => deg(q[j]));
      $(`jv${j}`).textContent = `${Math.min(...range).toFixed(1)}° … ${Math.max(...range).toFixed(1)}°`;
    } else if (state.jointView === 'error') {
      const err = e.joint_error_deg.map((row) => row[j]);
      p = plot(host, {x: [0, end], height: 150, yLabel: 'measured − target, deg', zones: [], series: [{x: e.t, y: err, cls: 'line-highlight'}],
        rules: [{y: 0, cls: 'gridline'}]});
      $(`jv${j}`).textContent = `max |error| ${Math.max(...err.map((v) => Math.abs(v ?? 0))).toFixed(3)}°`;
    } else {
      const cap = e.tau_cap[j];
      const band = {x: e.tau.t, y0: e.tau.min.map((row) => row[j]), y1: e.tau.max.map((row) => row[j]), cls: 'band-measured'};
      const peak = Math.max(...e.tau.max.map((row) => Math.abs(row[j])), ...e.tau.min.map((row) => Math.abs(row[j])));
      p = plot(host, {x: [0, end], height: 150, y: [-cap * 1.08, cap * 1.08], yLabel: 'N·m', series: [band],
        rules: [{y: cap, cls: 'limit', label: `cap ${cap}`}, {y: -cap, cls: 'limit'},
          {y: e.saturation_fraction * cap, cls: 'gridline'}, {y: -e.saturation_fraction * cap, cls: 'gridline'}],
        zones: (e.saturated_intervals || []).map(([x0, x1]) => ({x0, x1, cls: 'zone-bad'}))});
      $(`jv${j}`).textContent = `peak ${((100 * peak) / cap).toFixed(0)} % of cap`;
    }
    p.onSeek((t) => { play(false); setTime(t); });
    p.cursor(state.time);
    state.jointPlots.push(p);
  });
}

// ── the code view ─────────────────────────────────────────────────────────────────────────────────────────

let hljs = null;
async function highlighter() {
  if (!hljs) {
    const [core, python] = await Promise.all([import(HLJS), import(HLJS_PY)]);
    hljs = core.default;
    hljs.registerLanguage('python', python.default);
  }
  return hljs;
}

function linkTypes(html) {
  // every robot_msgs type the page lists becomes a link to its source lines (hljs output only has class attributes)
  const types = state.page.robot_msgs;
  if (!types.length) return html;
  const pattern = new RegExp(`\\b(${types.map((t) => t.name).join('|')})\\b(?![^<]*>)`, 'g');
  return html.replace(pattern, (name) => {
    const type = types.find((t) => t.name === name);
    return `<a class="type" href="${type.url}" title="robot_msgs.${type.module.split('.').pop()}.${name}: ${escapeHtml(type.summary)}">${name}</a>`;
  });
}

async function codeTabs() {
  const page = state.page;
  const solution = $('solution').value;
  const tabs = [
    {id: 'contract', label: 'The black box (OBJECTIVES §1)', text: page.objectives_block,
      caption: `The frozen contract: <a href="${REPO_URL}/blob/main/OBJECTIVES.md">OBJECTIVES.md</a> §1.`},
    {id: 'solution', label: `${solution}/solution.py`, file: `data/repo/solutions/${solution}/solution.py`,
      caption: `The selected solution, the only thing a solution is: <a href="${REPO_URL}/blob/main/solutions/${solution}/solution.py">solutions/${solution}/solution.py</a>.`},
  ];
  if (page.best_solution && page.best_solution.id !== solution) {
    tabs.push({id: 'best', label: `best: ${page.best_solution.id}`, text: page.best_solution.code,
      caption: `The best admissible solution: <a href="${REPO_URL}/blob/main/${page.best_solution.path}">${page.best_solution.path}</a>.`});
  }
  tabs.push(
    {id: 'pipeline', label: 'what this page calls', file: 'runtime/pipeline.py',
      caption: 'The page\'s driver, run in your browser: it calls the ruler\'s <code>run_task</code> and returns what is drawn.'},
    {id: 'shim', label: 'the mujoco shim', file: 'runtime/mujoco_shim.py',
      caption: 'The only code written for the browser: MuJoCo\'s Python API over its official WebAssembly build.'},
  );
  $('code-tabs').innerHTML = tabs.map((t, i) => `<button role="tab" aria-selected="${i === 0}" data-tab="${t.id}">${escapeHtml(t.label)}</button>`).join('');
  const show = async (id) => {
    const tab = tabs.find((t) => t.id === id);
    for (const b of $('code-tabs').querySelectorAll('button')) b.setAttribute('aria-selected', String(b.dataset.tab === id));
    let text = tab.text;
    if (text === undefined) {
      const response = await fetch(tab.file);
      text = response.ok ? await response.text() : `# could not load ${tab.file}`;
    }
    const h = await highlighter();
    $('code').innerHTML = linkTypes(h.highlight(text, {language: 'python'}).value);
    $('code-caption').innerHTML = tab.caption;
  };
  for (const b of $('code-tabs').querySelectorAll('button')) b.addEventListener('click', () => show(b.dataset.tab));
  await show('contract');
}

function renderTypes() {
  $('types').innerHTML = state.page.robot_msgs.map((t) => `
    <div class="type-card">
      <h4><a href="${t.url}">${t.name}</a></h4>
      <p>${escapeHtml(t.summary)}</p>
      ${t.fields.length ? `<ul>${t.fields.slice(0, 7).map((f) => `<li>${escapeHtml(f.replace(/\s*#.*$/, ''))}</li>`).join('')}</ul>` : ''}
      <span class="src"><a href="${t.url}">${t.module}, lines ${t.lines[0]}–${t.lines[1]}</a></span>
    </div>`).join('');
}

function renderRanList() {
  const wheels = state.manifest.wheels.map((w) => {
    const link = w.commit && w.source.startsWith('http') ? `<a href="${w.source}">${w.commit.slice(0, 7)}</a>` : (w.commit ? w.commit.slice(0, 7) : 'PyPI');
    return `<li><code>${w.file}</code> (${(w.bytes / 1024).toFixed(0)} KB), built from ${link}</li>`;
  }).join('');
  $('ranlist').innerHTML = `${wheels}
    <li>Pyodide ${state.manifest.pyodide} and MuJoCo ${state.manifest.mujoco_wasm} (<code>@mujoco/mujoco</code>, the same release as the native wheel), both pinned, from jsDelivr.</li>`;
}

// ── population ────────────────────────────────────────────────────────────────────────────────────────────

function renderLeaderboard() {
  const board = state.page.leaderboard;
  if (!board.scored) {
    $('leaderboard').innerHTML = '<div class="empty">Not scored yet. The leaderboard fills in as <code>tta evaluate</code> writes each solution\'s scorecard.</div>';
  } else {
    const rows = board.rows.map((row, i) => `
      <tr data-solution="${row.id}" class="${row.id === board.best ? 'best' : ''}">
        <td class="num">${i + 1}</td><td><code>${row.id}</code></td>
        <td class="num">${fmt(row.objective, 4)}</td>
        <td>${row.admissible ? '<span class="chip pass">admissible</span>' : '<span class="chip fail">fails a gate</span>'}</td>
        <td class="num">${fmt(100 * (row.gate_pass_rate ?? 0), 3)} %</td>
        <td><code>${row.parent ?? '—'}</code></td>
        <td class="change">${escapeHtml(row.change || '')}</td>
      </tr>`).join('');
    $('leaderboard').innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th class="num">#</th><th>solution</th><th class="num">tool_track_rms_mm</th><th>gates</th><th class="num">gate pass rate</th><th>parent</th><th>change</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
    for (const tr of $('leaderboard').querySelectorAll('tr[data-solution]')) {
      tr.addEventListener('click', () => {
        $('solution').value = tr.dataset.solution;
        $('run').scrollIntoView({behavior: 'smooth'});
        codeTabs();
        runSelected();
      });
    }
  }
  $('progress').hidden = !board.progress_svg;
}

// ── start ─────────────────────────────────────────────────────────────────────────────────────────────────

async function main() {
  const [page, manifest] = await Promise.all([
    fetch('data/page.json').then((r) => r.json()),
    fetch('runtime/manifest.json').then((r) => r.json()),
  ]);
  state.page = page;
  state.manifest = manifest;
  fillSelects();
  verdictLine();
  renderLeaderboard();
  renderTypes();
  codeTabs();
  for (const b of $('joint-tabs').querySelectorAll('button')) {
    b.addEventListener('click', () => {
      state.jointView = b.dataset.view;
      for (const other of $('joint-tabs').querySelectorAll('button')) other.setAttribute('aria-selected', String(other === b));
      renderJoints();
    });
  }
  $('play').addEventListener('click', () => play());
  $('scrub').addEventListener('input', () => { play(false); setTime(Number($('scrub').value)); });
  $('run-button').addEventListener('click', runSelected);
  $('solution').addEventListener('change', () => { codeTabs(); runSelected(); });
  $('task').addEventListener('change', runSelected);
  requestAnimationFrame(animate);
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (state.run) { select(state.selected); renderJoints(); } }, 200);
  });
  try {
    state.viewer = await createViewer($('viewer'));
  } catch (error) {
    $('boot-text').textContent = `The 3D view could not start (${error.message}); the scores below still run.`;
  }
  await call('preview', {task_id: $('task').value}).then((preview) => {
    state.preview = preview;
    $('boot').hidden = true;
    if (state.viewer) {
      state.viewer.setGeoms(preview.render.geoms);
      state.viewer.setArm('target', preview.render.target, preview.render.t);
      state.viewer.setArm('measured', null, []);
      state.viewer.setPaths({target: preview.tool_target});
      state.viewer.fit(fitPoints(preview));
    }
    setDuration(preview.task.duration_s);
    play(true);
  }).catch((error) => setStatus(`<b>Could not load the task.</b> ${escapeHtml(error.message)}`));
  $('run-button').disabled = false;
  await runSelected();
}

main();
