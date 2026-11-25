// The landing page: plays back saved runs. The run on screen is the blackbox_agent viewer's <bb-evidence> (vendored:
// vendor/bb-evidence.js), the metric explainer, Lens <-> Recorder over one bb-run/1 record; this file wires the
// solution and dev-task pickers to which record it plays, draws each joint's tracking error from the same record,
// the code view and the population. It formats and draws; every number on it is the ruler's, from a run record
// `tta evaluate` saved (tools/build_site.py exports them to data/runs/ and lists them in data/state.json).

import {plot} from './plots.js';

const $ = (id) => document.getElementById(id);
const REPO_URL = 'https://github.com/zacharyyamaoka/trajectory_tracking_agent';
const GITHUB = 'https://github.com/zacharyyamaoka';
const HLJS = 'https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/es/core.min.js';
const HLJS_PY = 'https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/es/languages/python.min.js';
const STATE = 'data/state.json';
const DEFAULT_TASK = 'workspace-dev-001'; // the ISO 9283 cube: a path anyone recognises
const DEV_TASKS = 42; // ruler v1's dev split (OBJECTIVES §3)
const KEEP_RECORDS = 6; // parsed records kept for the joint plots and a quick switch back

const state = {
  page: null,
  index: null,         // data/runs/index.json: the pickers
  full: null,          // data/state.json (bb-state/1): its playback slice lists every record
  context: null,
  run: null,           // {solution, task, path, metrics, gates}: the run bb-evidence shows (tools/build_site.py reads it)
  busy: false,
  ticket: 0,
  jointPlots: [],
  firstFrameMs: null,  // performance.now() when the first run was drawn
};
window.__page = state;

// ── small helpers ─────────────────────────────────────────────────────────────────────────────────────────

const fmt = (v, digits = 3) => (v === null || v === undefined || Number.isNaN(v) ? '—' : (+v).toPrecision(digits));
function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
}
function solutionRow(id) { return state.index.solutions.find((s) => s.id === id); }
const short = (sha) => (sha ? sha.slice(0, 7) : '?');
const commitLink = (sha, repo = REPO_URL) => (sha ? `<a href="${repo}/commit/${sha}">${short(sha)}</a>` : 'an unknown commit');
const day = (iso) => (iso ? iso.slice(0, 10) : '');
const kindName = (kind) => kind.replaceAll('_', ' ');
const frame = () => new Promise((resolve) => requestAnimationFrame(resolve));
async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

// ── the host context bb-evidence loads through (the viewer's CONTRACT §4, §7, §14) ────────────────────────────
// WHY a host context: state.json lists all the shipped records, and a standalone <bb-evidence state-src> fetches every
// listed record up front (to colour its run chips), which suits 2-5 runs, not 244. The page hands the element a state
// whose playback lists only the run the pickers chose, and this context: it loads a record only when the full
// listing has it (the contract's refusal), resolves it beside state.json, and shares one fetch with the joint plots.

function hostContext(full, stateUrl) {
  const listed = new Set(full.playback.runs.map((r) => r.path));
  const cache = new Map();
  return {
    page: 'overview',
    links: {},
    stateUrl,
    follow: false,
    href() { return ''; },
    load(path) {
      if (!listed.has(path)) return Promise.reject(new Error(`refused: ${path} is not a playback record listed in state.playback.runs`));
      if (!cache.has(path)) {
        cache.set(path, getJson(new URL(path, stateUrl)).catch((error) => { cache.delete(path); throw error; }));
        while (cache.size > KEEP_RECORDS) cache.delete(cache.keys().next().value);
      }
      return cache.get(path);
    },
    asset(path) { return Promise.reject(new Error(`refused: ${path}: this page has no page assets`)); },
    open(el, detail) {
      return el.dispatchEvent(new CustomEvent('bb-open', {bubbles: true, composed: true, cancelable: true, detail}));
    },
  };
}

// ── the pickers ───────────────────────────────────────────────────────────────────────────────────────────

function fillSolutions() {
  const {index} = state;
  const {best, gen0_best: gen0} = index.rule.full;
  $('solution').innerHTML = index.solutions.map((s) => {
    const mark = s.id === best ? ' · best' : s.id === gen0 ? ' · best of gen 0' : '';
    const score = s.objective !== null && s.objective !== undefined ? ` · ${fmt(s.objective, 3)} mm` : '';
    return `<option value="${escapeHtml(s.id)}">${escapeHtml(s.id)}${score}${mark}</option>`;
  }).join('');
}

function shippedTasks(solutionId) {
  // dataset order, only the tasks this solution ships (site/README.md: the rule), so no option is ever dead
  const row = solutionRow(solutionId);
  return state.index.tasks.filter((t) => row.tasks[t.id]);
}

function fillTasks(solutionId, wanted) {
  const row = solutionRow(solutionId);
  const tasks = shippedTasks(solutionId);
  $('task').innerHTML = tasks.map((t) => {
    const entry = row.tasks[t.id];
    return `<option value="${t.id}">${t.id.replace('workspace-', '')} · ${kindName(t.kind)} · ${fmt(entry.objective, 3)} mm${entry.pass ? '' : ' ✗'}</option>`;
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

// ── the run on screen ─────────────────────────────────────────────────────────────────────────────────────

async function show(solutionId, taskId) {
  const ticket = ++state.ticket;
  state.busy = true;
  history.replaceState(null, '', `?solution=${encodeURIComponent(solutionId)}&task=${encodeURIComponent(taskId)}`);
  const entry = solutionRow(solutionId)?.tasks[taskId];
  const listed = entry && state.full.playback.runs.find((r) => r.path === entry.record);
  const evidence = $('evidence');
  try {
    if (!listed) throw new Error(`${solutionId} on ${taskId} has no record listed in state.json`);
    const record = await state.context.load(listed.path);
    if (ticket !== state.ticket) return;
    // WHY loaded first: the element then finds it in the context's cache and draws at once, so a quick second pick
    // can never land between its load and its draw. It reads only this state's playback slice: the one run chosen.
    evidence.state = {...state.full, playback: {...state.full.playback, runs: [listed]}};
    const id = `${solutionId}/${taskId}`;
    for (let k = 0; k < 600 && !(evidence.rec?.id === id && evidence.querySelector('.bbe-card, .bbe-lane')); k++) await frame();
    if (ticket !== state.ticket) return; // a newer pick is loading; it owns the screen
    if (evidence.rec?.id !== id) throw new Error(`the explainer did not draw ${id}`);
    $('boot').hidden = true;
    evidence.hidden = false;
    state.run = {solution: solutionId, task: taskId, path: listed.path, record: record.id,
      metrics: Object.fromEntries(record.metrics.map((m) => [m.id, m.value])),
      gates: Object.fromEntries(record.metrics.filter((m) => m.kind === 'gate').map((m) => [m.id, m.passed]))};
    provenance(solutionId, taskId, entry);
    renderJoints(record);
    if (state.firstFrameMs === null) state.firstFrameMs = performance.now();
  } catch (error) {
    if (ticket !== state.ticket) return;
    $('boot').hidden = false;
    $('boot-text').innerHTML = `<b>Could not load the run.</b> ${escapeHtml(error.message).slice(0, 600)}`;
    console.error(error);
  }
  if (ticket === state.ticket) state.busy = false;
}

function provenance(solutionId, taskId, entry) {
  // what scored the run on screen, and the build's check of the drawing against the ruler's number
  const s = solutionRow(solutionId).scored;
  const check = entry.checks?.tool_track_rms_mm;
  const agrees = check && check.ruler !== null
    ? ` The ruler's function re-run on this run's saved samples gives ${fmt(check.record, 6)} mm; it scored ${fmt(check.ruler, 6)} mm
      (${check.ok ? `equal within ${check.tolerance} mm` : '<b>they disagree: this drawing is wrong</b>'}).` : '';
  $('ran').innerHTML = `A saved run, scored by the ruler at ${commitLink(s.commit)}${s.dirty ? ' (with uncommitted changes)' : ''}
    on ${day(s.evaluated)}: the numbers are its record's, the per-task row of
    <a href="${REPO_URL}/blob/main/solutions/${encodeURIComponent(solutionId)}/scorecard.json">${escapeHtml(solutionId)}/scorecard.json</a>
    for <code>${taskId}</code>.${agrees} Reproduce it natively: <code>uv run --all-extras tta evaluate ${escapeHtml(solutionId)}</code>`;
}

// ── each joint's tracking error (the one joint view bb-evidence does not draw) ───────────────────────────────

function renderJoints(record) {
  const channel = (id) => record.channels.find((c) => c.id === id);
  const q = channel('q');
  const qTarget = channel('q_target');
  const t = record.time.t;
  if (!q || !qTarget) { $('joint-plots').innerHTML = '<div class="empty">This run saved no joint angles.</div>'; return; }
  const mask = record.metrics.find((m) => m.id === 'tool_track_rms_mm')?.evidence?.counted?.mask; // the moving samples
  const end = t[t.length - 1] + (t.length > 1 ? t[1] - t[0] : 0);
  const evidence = $('evidence');
  state.jointPlots = [];
  $('joint-plots').innerHTML = q.columns.map((name, j) => `<div class="joint"><h4>${escapeHtml(q.names?.[j] || name)}<span id="jv${j}"></span></h4><div id="jp${j}"></div></div>`).join('');
  q.columns.forEach((_, j) => {
    // display arithmetic only: measured minus target, both in the record's degrees
    const error = q.values.map((row, i) => (row && row[j] !== null && qTarget.values[i][j] !== null ? row[j] - qTarget.values[i][j] : null));
    const moving = mask ? error.map((v, i) => (mask[i] ? v : null)) : error;
    const resting = mask ? error.map((v, i) => (mask[i] ? null : v)) : [];
    const p = plot($(`jp${j}`), {x: [t[0], end], height: 150, yLabel: 'deg', series: [
      {x: t, y: resting, cls: 'line-target'}, {x: t, y: moving, cls: 'line-highlight'}], rules: [{y: 0, cls: 'gridline'}]});
    const peak = Math.max(...error.map((v) => Math.abs(v ?? 0)));
    $(`jv${j}`).textContent = `max |error| ${peak.toPrecision(3)}°`;
    p.onSeek((time) => { evidence.stop?.(); evidence.seek?.(time); });
    state.jointPlots.push(p);
  });
}

let lastCursor = null;
function followCursor() {
  // the explainer owns the one time cursor; the joint plots follow it
  const t = $('evidence').t;
  if (t !== lastCursor) {
    lastCursor = t;
    for (const p of state.jointPlots) p.cursor(t);
  }
  requestAnimationFrame(followCursor);
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

function renderScoredBy(solutionId) {
  // what scored the selected solution (its scorecard's `code` block)
  const s = solutionRow(solutionId).scored;
  const pkg = (name) => {
    const p = s[name] || {};
    return `${name} ${p.version ?? '?'} at ${p.commit ? `<a href="${GITHUB}/${name}/tree/${p.commit}">${short(p.commit)}</a>` : '?'}`;
  };
  $('ranlist').innerHTML = `
    <li><code>${escapeHtml(solutionId)}</code> was scored by the ruler (v1) at ${commitLink(s.commit)} on ${day(s.evaluated)}, with ${pkg('robot_controllers')} and ${pkg('robot_msgs')}.</li>
    <li>Its <code>solution.py</code> then: sha256 <code>${(s.solution_sha256 || '').slice(0, 16)}…</code></li>`;
}

// ── population ────────────────────────────────────────────────────────────────────────────────────────────

function pick(solutionId, taskId) {
  $('solution').value = solutionId;
  fillTasks(solutionId, taskId ?? $('task').value);
  codeTabs();
  renderScoredBy(solutionId);
  return show(solutionId, $('task').value);
}

function renderLeaderboard() {
  const board = state.page.leaderboard;
  if (!board.scored) {
    $('leaderboard').innerHTML = '<div class="empty">Not scored yet. The leaderboard fills in as <code>tta evaluate</code> writes each solution\'s scorecard.</div>';
  } else {
    const rows = board.rows.map((row, i) => `
      <tr data-solution="${escapeHtml(row.id)}" class="${row.id === board.best ? 'best' : ''}">
        <td class="num">${i + 1}</td><td><code>${escapeHtml(row.id)}</code></td>
        <td class="num">${fmt(row.objective, 4)}</td>
        <td>${row.admissible ? '<span class="chip pass">admissible</span>' : '<span class="chip fail">fails a gate</span>'}</td>
        <td class="num">${fmt(100 * (row.gate_pass_rate ?? 0), 3)} %</td>
        <td><code>${escapeHtml(row.parent ?? '—')}</code></td>
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
  const excluded = board.excluded?.ablation || [];
  $('population-note').textContent = excluded.length
    ? `${excluded.length} ablation solution${excluded.length === 1 ? '' : 's'} (tagged ablation: which parts matter, not search progress) are left out.` : '';
}

// ── start ─────────────────────────────────────────────────────────────────────────────────────────────────

async function main() {
  const stateUrl = new URL(STATE, document.baseURI).href;
  const [page, full] = await Promise.all([getJson('data/page.json'), getJson(stateUrl)]);
  const index = await getJson(new URL(full.playback.index, stateUrl));
  Object.assign(state, {page, full, index});
  const {best, gen0_best: gen0} = index.rule.full;
  $('rule').innerHTML = `${index.rule.count} saved runs ship with this page (<a href="${REPO_URL}/blob/main/site/README.md#which-runs-ship-the-rule">the rule</a>):
    every solution on one dev task of each kind, and ${best} (the best) and ${gen0} (the best of generation 0) on all ${DEV_TASKS} dev tasks.`;
  await customElements.whenDefined('bb-evidence');
  state.context = hostContext(full, stateUrl);
  $('evidence').context = state.context;
  fillSolutions();
  const params = new URLSearchParams(location.search);
  const ids = index.solutions.map((s) => s.id);
  const solution = ids.includes(params.get('solution')) ? params.get('solution') : (best ?? ids[0]);
  $('solution').value = solution;
  fillTasks(solution, params.get('task'));
  verdictLine();
  renderLeaderboard();
  renderTypes();
  renderScoredBy(solution);
  codeTabs();
  $('solution').addEventListener('change', () => pick($('solution').value));
  $('task').addEventListener('change', () => show($('solution').value, $('task').value));
  requestAnimationFrame(followCursor);
  await show(solution, $('task').value);
}

main().catch((error) => {
  $('boot-text').innerHTML = `<b>Could not load the saved runs.</b> ${escapeHtml(error.message)}`;
  console.error(error);
});
