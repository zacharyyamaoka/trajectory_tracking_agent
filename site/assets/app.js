// The landing page: plays back saved runs. Wires the playback data, the 3D view, the score cards and their
// explanations, the joint plots, the code view and the population. It formats and draws; every number on it is the
// ruler's, from a run record `tta evaluate` saved (tools/build_site.py exports them to data/playback/).

import {createViewer} from './viewer3d.js';
import {EXPLAINERS, fmt, deg} from './explain.js';
import {plot} from './plots.js';
import {loadIndex, loadRun, shippedTasks} from './playback.js';

const $ = (id) => document.getElementById(id);
const REPO_URL = 'https://github.com/zacharyyamaoka/trajectory_tracking_agent';
const GITHUB = 'https://github.com/zacharyyamaoka';
const HLJS = 'https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/es/core.min.js';
const HLJS_PY = 'https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/es/languages/python.min.js';
const DEFAULT_TASK = 'workspace-dev-001'; // the ISO 9283 cube: a path anyone recognises
const DEV_TASKS = 42; // ruler v1's dev split (OBJECTIVES §3)

const state = {
  page: null,
  index: null,
  viewer: null,
  run: null,          // the run on screen (assets/playback.js loadRun)
  selected: 'tool_track_rms_mm',
  playing: false,
  duration: 1,
  time: 0,
  explainPlot: null,
  jointPlots: [],
  jointView: 'position',
  busy: false,
  ticket: 0,
  firstFrameMs: null,  // performance.now() when the first run was on screen (tools/build_site.py shoot reads it)
};
window.__page = state;

// ── small helpers ─────────────────────────────────────────────────────────────────────────────────────────

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
}
function setStatus(html) { $('status').innerHTML = html; }
function solutionRow(id) { return state.index.solutions.find((s) => s.id === id); }
const short = (sha) => (sha ? sha.slice(0, 7) : '?');
const commitLink = (sha, repo = REPO_URL) => (sha ? `<a href="${repo}/commit/${sha}">${short(sha)}</a>` : 'an unknown commit');
const day = (iso) => (iso ? iso.slice(0, 10) : '');
const kindName = (kind) => kind.replaceAll('_', ' ');

// ── the hero: selection and playback ──────────────────────────────────────────────────────────────────────

function fillSolutions() {
  const {index} = state;
  const best = index.rule.full.best;
  const gen0 = index.rule.full.gen0_best;
  $('solution').innerHTML = index.solutions.map((s) => {
    const mark = s.id === best ? ' · best' : s.id === gen0 ? ' · best of gen 0' : '';
    const score = s.objective !== null && s.objective !== undefined ? ` · ${fmt(s.objective, 3)} mm` : '';
    return `<option value="${s.id}">${s.id}${score}${mark}</option>`;
  }).join('');
}

function fillTasks(solutionId, wanted) {
  // only the tasks this solution ships (site/README.md: the rule), so no option is ever dead
  const row = solutionRow(solutionId);
  const tasks = shippedTasks(state.index, solutionId);
  $('task').innerHTML = tasks.map((t) => {
    const entry = row.tasks[t.id];
    const mark = entry.pass ? '' : ' ✗';
    return `<option value="${t.id}">${t.id.replace('workspace-', '')} · ${kindName(t.kind)} · ${fmt(entry.objective, 3)} mm${mark}</option>`;
  }).join('');
  $('task-count').textContent = `· ${tasks.length} of ${DEV_TASKS} saved for ${solutionId}`;
  const ids = tasks.map((t) => t.id);
  $('task').value = ids.includes(wanted) ? wanted : ids.includes(DEFAULT_TASK) ? DEFAULT_TASK : ids[0];
}

function verdictLine() {
  const {index} = state;
  const best = solutionRow(index.rule.full.best);
  const gen0 = solutionRow(index.rule.full.gen0_best);
  const scored = state.page.leaderboard.rows.length;
  if (!best) {
    const top = index.solutions[0];
    $('verdict').innerHTML = top ? `No solution passes every gate yet. Closest: <b>${top.id}</b>, ${fmt(100 * (top.gate_pass_rate ?? 0), 3)} % of gate checks passed.`
      : 'No solution scored yet.';
    return;
  }
  $('verdict').innerHTML = `Best admissible solution: <b>${best.id}</b>, <b>${fmt(best.objective, 3)} mm</b> tool tracking error
    (median over the 42 dev tasks), out of ${scored} solutions scored${gen0 && gen0.id !== best.id
    ? `; the best of generation 0 (<b>${gen0.id}</b>) scores ${fmt(gen0.objective, 3)} mm` : ''}.`;
}

function fitPoints(run) {
  // the box the target arm and its tool path sweep (computed natively at build time), and the tool path itself
  const [lo, hi] = run.fit_box;
  return [lo, hi, [lo[0], hi[1], lo[2]], [hi[0], lo[1], hi[2]], ...run.tool_target];
}

async function show(solutionId, taskId) {
  const ticket = ++state.ticket;
  state.busy = true;
  history.replaceState(null, '', `?solution=${encodeURIComponent(solutionId)}&task=${encodeURIComponent(taskId)}`);
  setStatus(`Loading <b>${escapeHtml(solutionId)}</b> on <b>${escapeHtml(taskId)}</b>…`);
  try {
    const run = await loadRun(state.index, solutionId, taskId);
    if (ticket !== state.ticket) return; // a newer pick is loading; it owns the screen
    state.run = run;
    showRun(run);
    if (state.firstFrameMs === null) state.firstFrameMs = performance.now();
  } catch (error) {
    if (ticket !== state.ticket) return;
    setStatus(`<b>Could not load the run.</b> ${escapeHtml(error.message).slice(0, 600)}`);
    console.error(error);
  }
  if (ticket === state.ticket) state.busy = false;
}

function showRun(run) {
  const viewer = state.viewer;
  if (viewer) {
    $('boot').hidden = true;
    viewer.setGeoms(state.index.geoms);
    viewer.setArm('target', run.frames.target, run.t);
    viewer.setArm('measured', run.frames.measured, run.t);
    viewer.setPaths({target: run.tool_target, measured: run.tool.filter(Boolean)});
  }
  setDuration(run.t[run.t.length - 1]);
  const failed = Object.entries(run.gates).filter(([, ok]) => !ok).map(([gate]) => gate);
  setStatus(`<b>${run.solution}</b> on <b>${run.task.replace('workspace-', '')}</b> (${kindName(run.kind)}, ${run.duration_s.toFixed(2)} s):
    ${fmt(run.metrics.tool_track_rms_mm, 4)} mm tool tracking RMS, ${failed.length ? `failed: ${failed.join(', ')}` : 'every gate passed'}.`);
  const s = run.scored;
  // the page's one line on reproducing a run natively
  $('ran').innerHTML = `A saved run, scored by the ruler at ${commitLink(s.commit)}${s.dirty ? ' (with uncommitted changes)' : ''}
    on ${day(s.evaluated)}. Reproduce it natively: <code>uv run --all-extras tta evaluate ${run.solution}</code>`;
  $('scored-lede').innerHTML = `The run above, scored by the ruler when <code>tta evaluate</code> ran it (commit
    ${commitLink(s.commit)}): these are its numbers from the run record, the same as the per-task row of
    <a href="${REPO_URL}/blob/main/solutions/${run.solution}/scorecard.json">${run.solution}/scorecard.json</a>. Click a score to
    see how it was computed: the 3D view and the plot switch to what that number reads.`;
  renderCards();
  select(state.selected);
  renderJoints();
  renderProvenance();
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
  $('cards').innerHTML = EXPLAINERS.map((ex) => {
    const verdict = ex.verdict(run);
    const chip = ex.objective ? '<span class="chip info">objective</span>'
      : verdict ? '<span class="chip pass">pass</span>' : '<span class="chip fail">fail</span>';
    return `<button class="card${ex.objective ? ' objective' : ''}" data-id="${ex.id}" aria-pressed="false">
      <span class="name">${ex.name}</span>
      <span class="value">${cardValue(ex, run)}<small>${ex.unit && typeof ex.value(run) !== 'boolean' ? ` ${ex.unit}` : ''}</small></span>
      <span class="rule">${ex.rule(run)}</span>
      ${chip}
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
  const {viewer, run} = state;
  if (!viewer || !run) return;
  viewer.see(focus === 'tool');
  if (focus === 'tool') viewer.fit(run.tool_target, {minRadius: 0.18, scale: 1.5});
  else viewer.fit(fitPoints(run));
}

// ── joints ────────────────────────────────────────────────────────────────────────────────────────────────

function renderJoints() {
  const run = state.run;
  if (!run) return;
  const end = run.t[run.t.length - 1];
  const names = run.dep.joint_names;
  state.jointPlots = [];
  $('joint-plots').innerHTML = names.map((name, j) => `<div class="joint"><h4>${name}<span id="jv${j}"></span></h4><div id="jp${j}"></div></div>`).join('');
  names.forEach((name, j) => {
    const host = $(`jp${j}`);
    let p;
    if (state.jointView === 'position') {
      const target = run.q_target.map((q) => deg(q[j]));
      p = plot(host, {x: [0, end], height: 150, yLabel: 'deg', series: [
        {x: run.t, y: target, cls: 'line-target'},
        {x: run.t, y: run.q.map((q) => (q ? deg(q[j]) : null)), cls: 'line-measured'}]});
      $(`jv${j}`).textContent = `${Math.min(...target).toFixed(1)}° … ${Math.max(...target).toFixed(1)}°`;
    } else if (state.jointView === 'error') {
      const err = run.q.map((q, i) => (q ? deg(q[j] - run.q_target[i][j]) : null));
      p = plot(host, {x: [0, end], height: 150, yLabel: 'measured − target, deg', series: [{x: run.t, y: err, cls: 'line-highlight'}],
        rules: [{y: 0, cls: 'gridline'}]});
      $(`jv${j}`).textContent = `max |error| ${Math.max(...err.map((v) => Math.abs(v ?? 0))).toFixed(4)}°`;
    } else {
      const cap = run.dep.tau_cap[j];
      const tau = run.tau.map((row) => (row ? row[j] : null));
      const peak = Math.max(...tau.map((v) => Math.abs(v ?? 0)));
      const fraction = run.dep.saturation_fraction;
      p = plot(host, {x: [0, end], height: 150, y: [-cap * 1.08, cap * 1.08], yLabel: 'N·m', series: [{x: run.t, y: tau, cls: 'line-measured'}],
        rules: [{y: cap, cls: 'limit', label: `cap ${cap}`}, {y: -cap, cls: 'limit'}, {y: fraction * cap, cls: 'gridline'}, {y: -fraction * cap, cls: 'gridline'}],
        zones: (run.explain.saturated_intervals || []).map(([x0, x1]) => ({x0, x1: x1 + 0.005, cls: 'zone-bad'}))});
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
    {id: 'solution', label: `${solution}/solution.py`, file: `data/solutions/${solution}/solution.py`,
      caption: `The selected solution, the only thing a solution is: <a href="${REPO_URL}/blob/main/solutions/${solution}/solution.py">solutions/${solution}/solution.py</a>.`},
  ];
  if (page.best_solution && page.best_solution.id !== solution) {
    tabs.push({id: 'best', label: `best: ${page.best_solution.id}`, text: page.best_solution.code,
      caption: `The best admissible solution: <a href="${REPO_URL}/blob/main/${page.best_solution.path}">${page.best_solution.path}</a>.`});
  }
  $('code-tabs').innerHTML = tabs.map((t, i) => `<button role="tab" aria-selected="${i === 0}" data-tab="${t.id}">${escapeHtml(t.label)}</button>`).join('');
  const showTab = async (id) => {
    const tab = tabs.find((t) => t.id === id);
    for (const b of $('code-tabs').querySelectorAll('button')) b.setAttribute('aria-selected', String(b.dataset.tab === id));
    let text = tab.text;
    if (text === undefined) {
      const response = await fetch(tab.file);
      text = response.ok ? await response.text() : `# could not load ${tab.file}`;
    }
    try {
      const h = await highlighter();
      $('code').innerHTML = linkTypes(h.highlight(text, {language: 'python'}).value);
    } catch {
      $('code').textContent = text; // the highlighter is a nicety: without it the code still reads
    }
    $('code-caption').innerHTML = tab.caption;
  };
  for (const b of $('code-tabs').querySelectorAll('button')) b.addEventListener('click', () => showTab(b.dataset.tab));
  await showTab('contract');
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

function renderProvenance() {
  // what scored the run on screen (its scorecard's `code` block)
  const s = state.run.scored;
  const pkg = (name) => {
    const p = s[name] || {};
    return `${name} ${p.version ?? '?'} at ${p.commit ? `<a href="${GITHUB}/${name}/tree/${p.commit}">${short(p.commit)}</a>` : '?'}`;
  };
  $('ranlist').innerHTML = `
    <li><code>${state.run.solution}</code> was scored by the ruler (v1) at ${commitLink(s.commit)} on ${day(s.evaluated)}, with ${pkg('robot_controllers')} and ${pkg('robot_msgs')}.</li>
    <li>Its <code>solution.py</code> then: sha256 <code>${(s.solution_sha256 || '').slice(0, 16)}…</code></li>`;
}

// ── population ────────────────────────────────────────────────────────────────────────────────────────────

function pick(solutionId, taskId) {
  $('solution').value = solutionId;
  fillTasks(solutionId, taskId ?? $('task').value);
  codeTabs();
  return show(solutionId, $('task').value);
}

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
      if (!solutionRow(tr.dataset.solution)) continue; // not shipped: not clickable (never a dead option)
      tr.addEventListener('click', () => {
        $('run').scrollIntoView({behavior: 'smooth'});
        pick(tr.dataset.solution);
      });
    }
  }
  $('progress').hidden = !board.progress_svg;
  const excluded = board.excluded?.ablation || [];
  $('population-note').textContent = excluded.length
    ? `${excluded.length} ablation solution${excluded.length === 1 ? '' : 's'} (tagged ablation: which parts matter, not search progress) are left out.` : '';
}

// ── start ─────────────────────────────────────────────────────────────────────────────────────────────────

async function main() {
  const [page, index] = await Promise.all([fetch('data/page.json').then((r) => r.json()), loadIndex()]);
  state.page = page;
  state.index = index;
  const {best, gen0_best: gen0} = index.rule.full;
  $('rule').innerHTML = `${index.rule.count} saved runs ship with this page (<a href="${REPO_URL}/blob/main/site/README.md#which-runs-ship-the-rule">the rule</a>):
    every solution on one dev task of each kind, and ${best} (the best) and ${gen0} (the best of generation 0) on all ${DEV_TASKS} dev tasks.`;
  fillSolutions();
  const params = new URLSearchParams(location.search);
  const ids = index.solutions.map((s) => s.id);
  const solution = ids.includes(params.get('solution')) ? params.get('solution') : (index.rule.full.best ?? ids[0]);
  $('solution').value = solution;
  fillTasks(solution, params.get('task'));
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
  $('solution').addEventListener('change', () => pick($('solution').value));
  $('task').addEventListener('change', () => show($('solution').value, $('task').value));
  requestAnimationFrame(animate);
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (state.run) { select(state.selected); renderJoints(); } }, 200);
  });
  try {
    state.viewer = await createViewer($('viewer'));
  } catch (error) {
    $('boot-text').textContent = `The 3D view could not start (${error.message}); the scores below still play.`;
  }
  await show(solution, $('task').value);
}

main().catch((error) => { setStatus(`<b>Could not load the saved runs.</b> ${escapeHtml(error.message)}`); console.error(error); });
