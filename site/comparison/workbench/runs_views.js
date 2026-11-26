const CSS = "/* The runs workbench's host views (assets/runs_views.js; data-ui adds a view module's `css` to the document once).\n   Promoted from the V2 Overview round's kit (docs/proposals/v2-overview-2026-11-24/kit/views-css.js). Colours from\n   data-ui's tokens; the one rule outside a view's own element: a panel holding a tc-* view grows with its content, as a\n   stock kpi panel does (data-ui gap: \"a registered view cannot say it is content-sized\", docs/RUNS_WORKBENCH.md). */\n.dd-panel:not([data-sized])[data-type^=\"tc-\"] data-views { height: auto; }\n.dd-panel[data-type^=\"tc-\"] .dv-view { overflow: visible; }\n.tc-host { min-width: 0; }\n.tc { font: 13px/1.45 var(--data-font, system-ui, sans-serif); color: var(--data-fg, #1f2328); min-width: 0; }\n.tc b { font-weight: 600; }\n.tc-mut { color: var(--data-muted, #6e7781); }\n.tc-warn-t { color: #7d4e00; background: #fff8c5; border-radius: 4px; padding: 0 4px; white-space: nowrap; }\n.tc-answer { font-size: 15px; line-height: 1.5; margin: 2px 0 10px; padding: 10px 12px; border: 1px solid var(--data-border, #d0d7de); border-radius: 8px; background: var(--data-bg, #fff); }\n.tc-answer .tc-mut { font-size: 12.5px; }\n.tc-answer-lines { margin: 4px 0 0; padding: 0; list-style: none; font-size: 12.5px; }\n.tc-answer-lines li { margin: 1px 0; }\n.tc-sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; background: var(--c); margin: 0 5px 0 1px; vertical-align: -1px; flex: none; }\n.tc-name { white-space: nowrap; }\n.tc-gname { font-weight: 600; }\n.tc-dep { font-size: 11px; font-weight: 400; color: var(--data-muted, #6e7781); margin-left: 6px; white-space: nowrap; }\n.tc-chips { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; margin: 0 0 8px; font-size: 12.5px; }\n.tc-chips .tc-k { font-size: 11px; letter-spacing: .04em; text-transform: uppercase; color: var(--data-muted, #6e7781); margin-right: 4px; }\n.tc-chips button { font: inherit; font-size: 12.5px; padding: 2px 9px; border: 1px solid var(--data-border, #d0d7de); border-radius: 6px; background: var(--data-bg, #fff); color: inherit; cursor: pointer; }\n.tc-chips button[aria-pressed=\"true\"] { background: var(--data-fg, #1f2328); color: var(--data-bg, #fff); border-color: var(--data-fg, #1f2328); }\n.tc-chips select { font: inherit; font-size: 12.5px; padding: 2px 6px; max-width: 420px; }\n.tc-sp { flex: 1; }\n.tc-link { font: inherit; font-size: 12px; padding: 1px 8px; border: 1px solid var(--data-border, #d0d7de); border-radius: 6px; background: var(--data-bg, #fff); color: var(--data-accent, #0969da); cursor: pointer; white-space: nowrap; text-decoration: none; }\n.tc-chips .tc-link { color: var(--data-accent, #0969da); }\n.tc-scroll { overflow-x: auto; max-width: 100%; }\n.tc-foot { font-size: 11.5px; color: var(--data-muted, #6e7781); margin: 6px 2px 12px; }\n.tc-u { display: block; font-size: 10.5px; font-weight: 400; color: var(--data-muted, #6e7781); white-space: nowrap; }\n.tc-h { font-size: 11.5px; font-weight: 400; color: var(--data-muted, #6e7781); }\n/* the League table */\n.tc-ltable, .tc-stable { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }\n.tc-ltable th, .tc-stable th { font-size: 12px; font-weight: 600; text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--data-border, #d0d7de); vertical-align: bottom; white-space: nowrap; }\n.tc-ltable td, .tc-stable td { text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--data-rule, #eaeef2); vertical-align: middle; white-space: nowrap; }\n.tc-ltable th.tc-l, .tc-ltable td.tc-l, .tc-stable th.tc-l, .tc-stable td.tc-l { text-align: left; }\n.tc-ltable tbody tr { cursor: pointer; }\n.tc-ltable tbody tr:hover { background: var(--data-hover, #f6f8fa); }\n.tc-rank { color: var(--data-muted, #6e7781); width: 1.5em; }\n.tc-cfg { font-weight: 600; }\n.tc-big { font-size: 15px; font-weight: 600; }\n.tc-x { font-size: 11.5px; color: var(--data-muted, #6e7781); margin: 0 6px 0 5px; }\n.tc-x.tc-best { color: #1a7f37; font-weight: 600; }\n.tc-bar { display: inline-block; width: 48px; height: 7px; border-radius: 4px; background: var(--data-rule, #eaeef2); vertical-align: middle; overflow: hidden; }\n.tc-bar i { display: block; height: 100%; background: var(--c); border-radius: 4px; }\n.tc-kcell { display: flex; align-items: center; justify-content: flex-end; gap: 6px; }\n.tc-spark { display: block; }\n.tc-axis { stroke: var(--data-rule, #e6e5e0); }\n.tc-bestchip { font-size: 10.5px; padding: 0 5px; border-radius: 8px; border: 1px solid #a7d7b4; color: #1a7f37; }\n.tc-cellbtn { font: inherit; border: 0; background: none; padding: 0; color: inherit; cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; }\n.tc-onfront td { background: color-mix(in srgb, var(--data-accent, #0969da) 6%, transparent); }\n/* the inline drill: a config's worst targets, each linking its target view */\n.tc-drillrow > td { padding: 0 0 8px 24px !important; background: var(--data-bg, #fff); cursor: default; }\n.tc-ltable tbody tr.tc-drillrow:hover { background: none; }\n.tc-drill { border: 1px solid var(--data-border, #d0d7de); border-left: 3px solid var(--data-accent, #0969da); border-radius: 6px; padding: 6px 8px; margin: 6px 0 8px; text-align: left; white-space: normal; }\n.tc-drill-h { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; font-size: 12.5px; margin-bottom: 4px; }\n.tc-drill .tc-stable td, .tc-drill .tc-stable th { padding: 2px 6px; font-size: 12px; }\n/* matrices */\n.tc-card { margin: 4px 0 8px; }\n.tc-card h3 { font-size: 13.5px; margin: 6px 0 6px; display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 10px; }\n.tc-mtable { border-collapse: separate; border-spacing: 2px; font-size: 11.5px; font-variant-numeric: tabular-nums; }\n.tc-mtable th { font-weight: 600; font-size: 11.5px; padding: 2px 4px; white-space: nowrap; }\n.tc-mtable th.tc-l { text-align: left; }\n.tc-mtable .tc-stick { position: sticky; left: 0; z-index: 1; background: var(--data-bg, #fff); }\n.tc-mtable th.tc-grp { font-size: 11px; color: var(--data-muted, #6e7781); border-bottom: 1px solid var(--data-border, #d0d7de); text-align: center; font-weight: 600; }\n.tc-mtable th.tc-col { vertical-align: bottom; cursor: pointer; min-width: 46px; max-width: 58px; }\n.tc-mtable th.tc-col .tc-vh { display: inline-block; writing-mode: vertical-rl; transform: rotate(180deg); max-height: 128px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }\n.tc-mtable th.tc-on { color: var(--data-accent, #0969da); }\n.tc-mtable td { width: 52px; min-width: 46px; height: 22px; text-align: center; border-radius: 3px; padding: 0 3px; white-space: nowrap; }\n.tc-mtable td.tc-r1 { box-shadow: inset 0 0 0 2px #2da44e; font-weight: 700; }\n.tc-mtable td.tc-on { outline: 1px solid var(--data-accent, #0969da); }\n.tc-mtable td.tc-none { background: repeating-linear-gradient(45deg, transparent 0 4px, var(--data-rule, #e3e2dc) 4px 5px); }\n.tc-nested td[data-tc-cfg] { cursor: pointer; }\n.tc-nested tr.tc-grow th { font-weight: 600; }\n.tc-nested td.tc-gcell { opacity: .92; font-weight: 600; }\n.tc-nested td.tc-roll { box-shadow: inset 2px 0 0 var(--data-border, #d0d7de); }\n.tc-nested tr.tc-rollrow th, .tc-nested tr.tc-rollrow td { font-weight: 500; color: var(--data-muted, #6e7781); background: var(--data-bg, #fff); border-bottom: 1px solid var(--data-border, #d0d7de); }\n.tc-nested tr.tc-rollrow td .tc-sw { width: 8px; height: 8px; margin: 0 2px 0 0; }\n.tc-nested .tc-dep { display: inline; margin-left: 6px; }\n.tc-chev { font: inherit; border: 0; background: none; cursor: pointer; width: 16px; padding: 0; color: var(--data-muted, #6e7781); }\n.tc-indent { display: inline-block; width: 18px; }\n.tc-ramp { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 400; color: var(--data-muted, #6e7781); }\n.tc-ramp i { display: inline-block; width: 90px; height: 9px; border-radius: 3px; }\n/* small multiples */\n.tc-multiples { display: grid; gap: 12px; margin: 4px 0 10px; }\n.tc-fig { margin: 0; border: 1px solid var(--data-rule, #eaeef2); border-radius: 8px; padding: 6px 6px 2px; min-width: 0; }\n.tc-fig figcaption { font-size: 12.5px; margin: 0 0 2px 4px; }\n.tc-figans { font-size: 12px; color: var(--data-fg, #1f2328); margin-top: 1px; }\n.tc-panel { display: block; }\n.tc-grid { stroke: var(--data-rule, #eaeef2); }\n.tc-tick { font-size: 10px; fill: var(--data-muted, #6e7781); }\n.tc-dl { font-size: 10.5px; font-weight: 600; }\n.tc-dl-on { fill: var(--data-fg, #1f2328); }\n.tc-front { fill: none; stroke: var(--data-fg, #1f2328); stroke-width: 1.4; stroke-dasharray: 5 3; opacity: .7; }\n.tc-onring { stroke: var(--data-fg, #1f2328); stroke-width: 1.6; }\n/* tiles */\n.tc-top5 { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; gap: 1px 8px; font-size: 12px; align-items: center; font-variant-numeric: tabular-nums; }\n.tc-top5 .tc-r { color: var(--data-muted, #6e7781); }\n.tc-top5 .tc-v { text-align: right; }\n.tc-tile { display: flex; flex-direction: column; gap: 4px; padding: 2px 2px 0; }\n.tc-tnum { font-size: 24px; font-weight: 650; line-height: 1.2; display: flex; align-items: baseline; flex-wrap: wrap; gap: 0 8px; }\n.tc-tnum .tc-name { font-size: 22px; }\n.tc-tval { font-size: 15px; font-weight: 500; color: var(--data-muted, #6e7781); }\n.tc-tsub { font-size: 12.5px; line-height: 1.45; }\n.tc-tsub a { color: var(--data-accent, #0969da); }\n.tc-tfig { margin-top: 4px; }\n.tc-mini { display: block; max-width: 100%; }\n.tc-fill { fill: #5a8fca; }\n.tc-empty { fill: var(--data-rule, #e3e2dc); }\n.tc-dep0 { fill: #2a78d6; } .tc-dep1 { fill: #86afdb; } .tc-dep2 { fill: #eb6834; } .tc-dep3 { fill: #2f9e44; }\n/* the Coverage tab: cards over the deployment's own coverage page, embedded */\n.tc-coverage { display: flex; flex-direction: column; gap: 8px; }\n.tc-cov-cards { display: flex; flex-wrap: wrap; gap: 8px; }\n.tc-cov-card { font: inherit; font-size: 12.5px; text-align: left; display: flex; flex-direction: column; gap: 2px; padding: 6px 10px; border: 1px solid var(--data-border, #d0d7de); border-radius: 8px; background: var(--data-bg, #fff); color: inherit; cursor: pointer; min-width: 220px; max-width: 360px; }\n.tc-cov-card[aria-selected=\"true\"] { border-color: var(--data-accent, #0969da); box-shadow: inset 0 0 0 1px var(--data-accent, #0969da); }\n.tc-cov-fact { display: flex; justify-content: space-between; gap: 10px; font-variant-numeric: tabular-nums; }\n.tc-cov-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; font-size: 12.5px; }\n/* WHY a height of its own: a tc-* panel grows with its content (above), and an iframe has none */\n.tc-cov-frame { display: block; width: 100%; height: max(480px, calc(100vh - 330px)); border: 1px solid var(--data-border, #d0d7de); border-radius: 8px; background: #fff; }\n@media (prefers-color-scheme: dark) {\n  .tc-warn-t { color: #e3b341; background: #272115; }\n  .tc-x.tc-best, .tc-bestchip { color: #57ab5a; border-color: #2b6a30; }\n}\n";
/* traj_compare's runs workbench: its host views, registered through data-ui's own registerView (CONTRACT §1) before the
   workbench reads runs.base (traj_compare.runs_workbench, traj_compare.runs_overview; docs/RUNS_WORKBENCH.md).

   Promoted from the V2 Overview round's kit (docs/proposals/v2-overview-2026-11-24/kit/model.js + views.js; Zach's pick
   O3 "Headline tiles → drill") and the tabs round's T1 "Does sim match real?" (docs/proposals/v2-tabs-2026-11-24/), and
   made generic: every name (the accuracy KPI and its unit, the costs, the deployments' order, the model types, the
   configs' colour order) comes from the writer's config (index.html's <script id="tc-views">), none from a bench.

   Each view is a stock view plugin: the workbench hands it the rows the rail keeps (update(input)), it draws inside its
   own element only, and its links go to the target view (target.html with keep= + back=, as a Targets row's do). Every
   view's numbers are on its element as `el.tcOverview` (read-only; tests/test_runs_workbench_picks_browser.py reads
   them against tests/runs_picks_oracle.py).

   Types: tc-tile (the Overview's headline tiles) · tc-league · tc-matrix · tc-sweep · tc-tradeoff · tc-worst (the
   tiles' own pages, and the Overview's other options) · tc-pairs (the "Does sim match real?" answer) · tc-coverage
   (the Coverage tab: each deployment's coverage page, embedded).

   The rule, named on every figure (V2's and Nov 23's): a target's value for a group (a config, a model type) = the
   median over its runs; the group's value = the median over its targets; n = targets; at the fastest speed the filter
   leaves. `CSS` (assets/runs_views.css) is prepended to this file by runs_workbench.py. */

let C = null;  // the writer's config, set by registerRunsViews
const ACC = 'accuracy';  // the column the writer fills: the League KPI, else traj_compare's tool RMS (flagged per row)

// ── the one aggregation (pure: no DOM) ──

const finite = (v) => typeof v === 'number' && Number.isFinite(v);
// WHY the accuracy must be > 0: V2's League filter (isValid && > 0), and a log axis has no zero
const validRun = (id, v) => (id === ACC ? finite(v) && v > 0 : finite(v));

export function median(values) {
  const s = values.slice().sort((a, b) => a - b);
  const n = s.length;
  if (!n) return null;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

/** The accuracy KPI or one cost: {id, label, short, unit, log}. */
function field(id) {
  if (id === ACC) return C.acc;
  return C.costs.find((c) => c.id === id) || { id, label: id, short: id, unit: '', log: false };
}

/** "<dataset> · <deployment>" → "<dataset>" (the deployment is said by a header beside it). */
function datasetShort(dataset) {
  const at = String(dataset).lastIndexOf(' · ');
  return at > 0 ? String(dataset).slice(0, at) : String(dataset);
}

/** The model of one set of kept runs. */
function buildModel(rows) {
  const fields = [ACC, ...C.costs.map((c) => c.id)];
  const rank = new Map((C.configOrder || []).map((c, i) => [c, i]));
  const typed = !!(C.modelTypes && C.modelTypes.length);
  const targets = new Map();
  const configs = new Map();
  const deployments = new Set();
  const raw = {};
  for (const f of fields) raw[f] = { config: new Map(), mt: new Map() };
  const push = (map, group, tk, v) => {
    let g = map.get(group);
    if (!g) map.set(group, (g = new Map()));
    let list = g.get(tk);
    if (!list) g.set(tk, (list = []));
    list.push(v);
  };
  let filled = 0;
  for (const r of rows) {
    let t = targets.get(r.target_key);
    if (!t) {
      const split = r.split === undefined || r.split === null ? null : r.split;
      t = { key: r.target_key, site: r.site, slug: r.target_slug, target: r.target, speed: finite(r.speed) ? r.speed : null,
        dataset: r.dataset, split, deployment: r.deployment, facet: split === null ? r.dataset : `${r.dataset} · ${split}`,
        lines: [], runs: [] };
      targets.set(r.target_key, t);
    }
    t.lines.push(r.line);
    t.runs.push(r);
    deployments.add(r.deployment);
    if (r.accuracy_from) filled += 1;
    let c = configs.get(r.config);
    if (!c) configs.set(r.config, (c = { name: r.config, modelType: typed ? r.model_type : null, deployments: new Set(), runs: 0 }));
    c.deployments.add(r.deployment);
    c.runs += 1;
    for (const f of fields) {
      const v = r[f];
      if (!validRun(f, v)) continue;
      push(raw[f].config, r.config, r.target_key, v);
      if (typed) push(raw[f].mt, r.model_type, r.target_key, v);
    }
  }
  // per field and grouping: group -> [{t, v (the target's median over its runs), runs: [values]}]
  const tmed = {};
  for (const f of fields) {
    tmed[f] = {};
    for (const by of ['config', 'mt']) {
      const out = new Map();
      for (const [g, byT] of raw[f][by]) out.set(g, [...byT].map(([tk, vs]) => ({ t: targets.get(tk), v: median(vs), runs: vs })));
      tmed[f][by] = out;
    }
  }
  const speeds = [...new Set([...targets.values()].map((t) => t.speed))].filter(finite).sort((a, b) => a - b);
  const accSpeeds = new Set();
  for (const list of tmed[ACC].config.values()) for (const item of list) if (finite(item.t.speed)) accSpeeds.add(item.t.speed);
  const top = accSpeeds.size ? Math.max(...accSpeeds) : null;
  const slowest = accSpeeds.size ? Math.min(...accSpeeds) : null;
  const depOrder = (d) => { const i = (C.deployments || []).indexOf(d); return i < 0 ? 99 : i; };
  const cfgList = [...configs.values()].sort((a, b) =>
    (rank.has(a.name) ? rank.get(a.name) : 1e6) - (rank.has(b.name) ? rank.get(b.name) : 1e6) || b.runs - a.runs || (a.name < b.name ? -1 : 1));
  // WHY colours handed out to the configs the filter leaves, in one stable order: there are more configs than palette
  // colours, and every figure on a page gets the same kept rows, so they agree; one deployment's configs get the first.
  cfgList.forEach((c, i) => { c.color = C.palette[i % C.palette.length]; c.index = i; });
  const cache = new Map();
  const matches = (t, where) => {
    for (const k in where) {
      if (where[k] === undefined || where[k] === null) continue;
      if (t[k] !== where[k]) return false;
    }
    return true;
  };
  /** The value of one group under `where` (keys of a target: speed, dataset, split, deployment, facet). */
  function value(f, by, group, where = {}) {
    const key = `${f}|${by}|${group}|${JSON.stringify(where)}`;
    if (cache.has(key)) return cache.get(key);
    const items = ((tmed[f] && tmed[f][by].get(group)) || []).filter((item) => matches(item.t, where));
    const out = items.length ? { v: median(items.map((i) => i.v)), n: items.length, items } : null;
    cache.set(key, out);
    return out;
  }
  /** Every config with a value under `where`, best (lowest) first; ties by the stable order. */
  function league(f = ACC, where = {}) {
    return cfgList.map((c) => ({ c, cell: value(f, 'config', c.name, where) }))
      .filter((x) => x.cell)
      .sort((a, b) => a.cell.v - b.cell.v || a.c.index - b.c.index)
      .map((x) => ({ name: x.c.name, config: x.c, v: x.cell.v, n: x.cell.n, items: x.cell.items }));
  }
  /** The distinct values of a target key among targets with an accuracy value (optionally under `where`). */
  function columns(key, where = {}) {
    const seen = new Set();
    for (const list of tmed[ACC].config.values()) for (const item of list) if (matches(item.t, where)) seen.add(item.t[key]);
    return [...seen].filter((v) => v !== null && v !== undefined);
  }
  /** Nov 23's "best in X of Y cells": every (dataset · split, speed) cell with two or more configs. */
  function wins() {
    const out = new Map(cfgList.map((c) => [c.name, { wins: 0, of: 0 }]));
    let cells = 0;
    for (const facet of columns('facet').sort()) {
      for (const speed of (speeds.length ? speeds : [null])) {
        const present = cfgList.map((c) => ({ c, cell: value(ACC, 'config', c.name, { facet, speed }) })).filter((x) => x.cell);
        if (present.length < 2) continue;
        cells += 1;
        for (const x of present) out.get(x.c.name).of += 1;
        const winner = present.reduce((a, b) => (b.cell.v < a.cell.v ? b : a));
        out.get(winner.c.name).wins += 1;
      }
    }
    return { cells, byConfig: out };
  }
  /** Configs not dominated on (cost, accuracy): no other is at most as costly and as inaccurate, and better in one. */
  function pareto(points) {
    return points.filter((p) => !points.some((q) => q !== p && q.x <= p.x && q.y <= p.y && (q.x < p.x || q.y < p.y)));
  }
  const modelTypes = typed ? [...new Set(cfgList.map((c) => c.modelType))]
    .sort((a, b) => (C.modelTypes.indexOf(a) + 999) % 999 - (C.modelTypes.indexOf(b) + 999) % 999) : [];
  const facetDeployment = new Map([...targets.values()].map((t) => [t.facet, t.deployment]));
  const datasetDeployment = new Map([...targets.values()].map((t) => [t.dataset, t.deployment]));
  return {
    rows, targets, configs: cfgList, configOf: configs, deployments: [...deployments].sort((a, b) => depOrder(a) - depOrder(b)),
    modelTypes, typed, speeds, top, slowest, has: tmed[ACC].config.size > 0, filled, value, league, columns, wins, pareto,
    depOrder, facetDeployment, datasetDeployment,
    group: (r) => (typed ? r.model_type : r.config),
  };
}

// ── formatting (Nov 23's dataset.js rules) ──
function num3(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (value === 0) return '0';
  const abs = Math.abs(value);
  if (abs >= 1000) return Math.round(value).toLocaleString('en-US');
  if (abs >= 100) return value.toFixed(0);
  let text = Number(value.toPrecision(3)).toString();
  if (/e/.test(text)) text = value.toFixed(Math.min(8, 2 - Math.floor(Math.log10(abs))));
  return text;
}
function times(ratio) {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return '—';
  if (ratio >= 100) return `${Math.round(ratio).toLocaleString('en-US')}×`;
  if (ratio >= 10) return `${ratio.toFixed(0)}×`;
  if (ratio > 0.9 && ratio < 1.1) return `${Number(ratio.toPrecision(3))}×`;
  return `${Number(ratio.toPrecision(2))}×`;
}
/** A speed as the writer's speed tag reads: "1×" when its label says ×, else "speed 1". */
function speedText(speed) {
  if (speed === null || speed === undefined) return '—';
  return C.speed && C.speed.times ? `${Number(speed)}×` : `${(C.speed && C.speed.word) || 'speed'} ${Number(speed)}`;
}
const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* a private window */ } },
};
const swatch = (c) => `<i class="tc-sw" style="--c:${c ? c.color : '#999'}"></i>`;
/** A name whole, or middle-ellipsed with the whole name on hover. WHY the middle (Zach's truthful-rendering rule):
    configs often share a long prefix and differ at the end, so a clipped tail would hide the only difference. */
function nameHtml(name, max = 34, cls = 'tc-name') {
  const s = String(name);
  if (s.length <= max) return `<span class="${cls}">${esc(s)}</span>`;
  const head = Math.max(6, Math.floor((max - 1) * 0.45)), tail = max - 1 - head;
  return `<span class="${cls}" title="${esc(s)}">${esc(s.slice(0, head))}…${esc(s.slice(s.length - tail))}</span>`;
}
const middle = (s, max) => (s.length > max ? `${s.slice(0, Math.floor((max - 1) * 0.45))}…${s.slice(s.length - (max - 1 - Math.floor((max - 1) * 0.45)))}` : s);
const depText = (c) => [...c.deployments].join(', ');
const depHtml = (c) => `<span class="tc-dep" title="${esc(depText(c))}">${esc(middle(depText(c), 40))}</span>`;
const U = () => C.acc.unit;
/** "5 configs"; a label with a note in brackets keeps it last: "5 model types (proposed)". */
const plural = (n, word) => {
  const at = String(word).search(/\s*\(/);
  const head = at > 0 ? word.slice(0, at) : word, note = at > 0 ? word.slice(at) : '';
  return `${n} ${head}${n === 1 ? '' : 's'}${note}`;
};
/** Labels pushed apart: each, in height order, moves down until no placed label overlaps it (~6 px a character). */
function placeLabels(labels, { gap = 11, top = 0, bottom = Infinity } = {}) {
  labels.sort((a, b) => a.y - b.y);
  const placed = [];
  const w = (l) => 6 * l.text.length;
  for (const l of labels) {
    let moved = true;
    while (moved) {
      moved = false;
      for (const p of placed) {
        // WHY the 0.01 px slack: (y + gap) − y can round below gap, which looped forever (measured in the round)
        if (Math.abs(p.y - l.y) < gap - 0.01 && l.x < p.x + w(p) && p.x < l.x + w(l)) { l.y = p.y + gap; moved = true; }
      }
    }
    placed.push(l);
  }
  const over = placed.length ? Math.max(...placed.map((l) => l.y)) - bottom : 0;
  if (over > 0) for (const l of placed) l.y = Math.max(top, l.y - over);
  return placed;
}
const logT = (v, lo, hi) => (hi > lo ? (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) : 0.5);
const linT = (v, lo, hi) => (hi > lo ? (v - lo) / (hi - lo) : 0.5);

// Nov 23's log ramp for the matrices (light → dark; colour is the data, never a verdict)
const RAMP = ['#f3f6fb', '#d7e5f5', '#b3cdea', '#86afdb', '#5a8fca', '#3a70b3', '#285594', '#1c3d70', '#13284b'];
function rampColor(t) {
  t = Math.max(0, Math.min(1, t));
  const at = t * (RAMP.length - 1), lo = Math.floor(at), hi = Math.min(RAMP.length - 1, lo + 1), f = at - lo;
  const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const a = hex(RAMP[lo]), b = hex(RAMP[hi]);
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(',')})`;
}
function heatCell(v, lo, hi, extra = '') {
  const t = 0.05 + 0.8 * logT(v, lo, hi);
  return `style="background:${rampColor(t)};color:${t > 0.55 ? '#fff' : '#22211f'}" ${extra}`;
}
function rampLegend(lo, hi, unit) {
  const stops = RAMP.map((c, i) => `${c} ${(100 * i) / (RAMP.length - 1)}%`).join(',');
  return `<span class="tc-ramp"><span>${num3(lo)}</span><i style="background:linear-gradient(90deg,${stops})"></i><span>${num3(hi)} ${esc(unit)}</span><span class="tc-mut">log</span></span>`;
}
function sparkline(values, { lo, hi, log, color, title, w = 76, h = 24 }) {
  const pad = 3;
  const y = (v) => (h - pad) - (log ? logT(Math.max(v, lo), lo, hi) : linT(v, lo, hi)) * (h - 2 * pad);
  const x = (i) => pad + (i * (w - 2 * pad)) / Math.max(1, values.length - 1);
  const pts = [];
  values.forEach((v, i) => { if (v !== null && v !== undefined && (!log || v > 0)) pts.push([x(i), y(v)]); });
  const t = `<title>${esc(title || '')}</title>`;
  if (!pts.length) return `<svg class="tc-spark" width="${w}" height="${h}">${t}</svg>`;
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  return `<svg class="tc-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${t}<line x1="0" x2="${w}" y1="${h - 1}" y2="${h - 1}" class="tc-axis"/>` +
    `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.4" fill="${color}"/></svg>`;
}
const extent = (vals, positive) => {
  const v = vals.filter((x) => x !== null && x !== undefined && Number.isFinite(x) && (!positive || x > 0));
  return v.length ? { lo: Math.min(...v), hi: Math.max(...v) } : { lo: positive ? 0.001 : 0, hi: 1 };
};
/** The target view of one target, as a Targets row opens it: the runs the rail keeps for it ticked, back = this page
    (its filter and tab). WHY the path, not location.href: back= travels on into playback's breadcrumb, which takes
    same-origin paths only (runs_host.js). */
function targetHref(t) {
  const q = new URLSearchParams({ site: t.site, target: t.slug, keep: t.lines.join(','), back: location.pathname + location.search + location.hash });
  return `target.html?${q.toString().replace(/%2C/g, ',')}`;
}
/** "at 1×" (the fastest speed the filter leaves), or nothing without a speed. */
const atTop = (m) => (m.top === null ? '' : ` at ${speedText(m.top)}`);
function topText(m) {
  if (m.top === null) return 'over every run';
  return `at ${speedText(m.top)}${m.speeds.length > 1 && m.top < Math.max(...m.speeds) ? ' (the fastest speed left)' : ''}`;
}
const depNote = (m) => (m.deployments.length > 1
  ? ` · <span class="tc-warn-t" title="A config on one robot ranked against one on another is not a like-for-like comparison; tick one deployment in the rail to compare like with like.">${m.deployments.length} deployments in the filter</span>`
  : '');
/** Said under every figure that reads the accuracy: where a run carries no tag of its own, what stands in. */
const fillNote = (m) => (m.filled
  ? ` ${m.filled.toLocaleString('en-US')} of these runs carry no ${esc(C.acc.label)} tag of their own: ${esc(C.acc.fill)} stands in for them.`
  : '');
const empty = (kind) => `<div class="tc ${kind}"><p class="tc-answer">No run left has a ${esc(C.acc.label)}: widen the filter.</p></div>`;

// ── the base of every host view ──
class Base {
  constructor(host, el) {
    this.host = host;
    this.el = el;
    this.draws = 0;
    el.classList.add('tc-host');
    this._click = (e) => this.onClick(e);
    this._change = (e) => this.onChange(e);
    el.addEventListener('click', this._click);
    el.addEventListener('change', this._change);
  }
  key(k) { return `traj-compare/runs-workbench${location.pathname}/${this.input && this.input.view ? this.input.view.name : 'view'}/${k}`; }
  update(input) {
    this.input = input;
    this.tc = (input.view && input.view.tc) || {};
    this.m = buildModel(input.rows || []);
    this.draw();
  }
  draw() {
    this.render();
    this.el.tcOverview = this.hook();
    this.draws += 1;
    this.el.dataset.tcView = this.constructor.type;
    this.el.dataset.tcDraws = String(this.draws);
  }
  onClick() {}
  onChange() {}
  hook() { return {}; }
  destroy() { this.el.removeEventListener('click', this._click); this.el.removeEventListener('change', this._change); }
  /** A config's worst targets under `where`, each linking its target view. WHY not the stock records peek: a row in it
      opens nothing, so it never reached a target view (data-ui gap). The same config and place again closes it. */
  openWorst(config, where) {
    const same = this.drill && this.drill.config === config && JSON.stringify(this.drill.where) === JSON.stringify(where);
    this.drill = same ? null : { config, where };
    this.draw();
    const card = this.el.querySelector('[data-tc-drill]');
    if (card && card.scrollIntoView) card.scrollIntoView({ block: 'nearest' });
  }
  drillHtml(limit = 10) {
    if (!this.drill) return '';
    const { config, where } = this.drill;
    const cell = this.m.value(ACC, 'config', config, where);
    if (!cell) { this.drill = null; return ''; }
    const c = this.m.configOf.get(config);
    const items = cell.items.slice().sort((a, b) => b.v - a.v).slice(0, limit);
    this.drillRows = items.map((i) => [i.t.key, i.v]);
    const place = [where.speed !== undefined && where.speed !== null ? `at ${speedText(where.speed)}` : (this.m.top === null ? '' : 'over every speed'),
      where.facet ? `on ${where.facet}` : '', where.dataset ? `on ${where.dataset}` : '', where.split ? `on ${where.split}` : '',
      where.deployment ? `in ${where.deployment}` : ''].filter(Boolean).join(' ');
    return `<div class="tc-drill" data-tc-drill><div class="tc-drill-h">${swatch(c)}<b>${esc(config)}</b>: its ${items.length} worst of ${cell.n} targets ${esc(place)} <span class="tc-mut">· median ${num3(cell.v)} ${esc(U())} · a target’s value = the median over its runs</span><span class="tc-sp"></span><button type="button" class="tc-link" data-tc-close>✕ close</button></div>` +
      `<table class="tc-stable"><thead><tr><th class="tc-l">#</th><th class="tc-l">target</th><th class="tc-l">dataset · split</th><th>speed</th><th>${esc(C.acc.short)}<span class="tc-u">${esc(U())}</span></th><th>× its median</th><th>runs</th><th></th></tr></thead><tbody>${items.map((i, k) =>
        `<tr><td class="tc-l tc-rank">${k + 1}</td><td class="tc-l">${nameHtml(i.t.target, 48)}</td><td class="tc-l tc-mut">${esc(datasetShort(i.t.dataset))}${i.t.split === null ? '' : ` · ${esc(i.t.split)}`}</td><td>${speedText(i.t.speed)}</td><td>${num3(i.v)}</td><td>${times(i.v / cell.v)}</td><td>${i.runs.length}</td><td><a class="tc-link" data-tc-target href="${esc(targetHref(i.t))}">Open target view</a></td></tr>`).join('')}</tbody></table></div>`;
  }
  closeDrill(e) {
    if (!e.target.closest('[data-tc-close]')) return false;
    this.drill = null; this.draw(); return true;
  }
}

// ═══ tc-league: Nov 23's answer, League table and dataset · split matrix ═══
class LeagueView extends Base {
  static type = 'tc-league';
  onClick(e) {
    if (this.closeDrill(e)) return;
    const f = e.target.closest('[data-tc-facet]');
    if (f) { this.facet = f.dataset.tcFacet; store.set(this.key('facet'), this.facet); this.draw(); return; }
    const w = e.target.closest('[data-tc-worst]');
    if (w) { e.preventDefault(); this.openWorst(w.dataset.tcWorst, this.where()); return; }
    const row = e.target.closest('tr[data-tc-config]');
    if (row && !e.target.closest('a,button,select,[data-tc-drill]')) this.openWorst(row.dataset.tcConfig, this.where());
  }
  onChange(e) {
    if (e.target.matches('select[data-tc-facet-select]')) { this.facet = e.target.value; store.set(this.key('facet'), this.facet); this.draw(); }
  }
  where() { return { speed: this.m.top, facet: this.facet === 'all' ? undefined : this.facet }; }
  facets() {
    const m = this.m;
    return m.columns('facet').sort((a, b) => m.depOrder(m.facetDeployment.get(a)) - m.depOrder(m.facetDeployment.get(b)) || (a < b ? -1 : 1));
  }
  render() {
    const m = this.m, tc = this.tc;
    this.L = [];
    if (!m.has) { this.el.innerHTML = empty('tc-league'); return; }
    const facets = this.facets();
    if (this.facet === undefined) this.facet = store.get(this.key('facet'), 'all');
    if (this.facet !== 'all' && !facets.includes(this.facet)) this.facet = 'all';
    const where = this.where();
    const L = m.league(ACC, where);
    this.L = L;
    if (this.drill && JSON.stringify(this.drill.where) !== JSON.stringify(where)) this.drill = null;
    let html = '';
    if (!L.length) { this.el.innerHTML = empty('tc-league'); return; }
    const best = L[0];
    if (tc.answer !== false) html += `<p class="tc-answer" data-tc-answer>${leagueSentence(m, L, this.facet)}</p>`;
    // the dataset · split facet: chips when they fit one line or two, else one select
    if (facets.length > 1) {
      const label = 'Dataset · split';
      if (facets.length <= 14) {
        html += `<div class="tc-chips"><span class="tc-k">${label}</span>${['all', ...facets].map((f) =>
          `<button type="button" data-tc-facet="${esc(f)}" aria-pressed="${f === this.facet}" title="${esc(f)}">${esc(f === 'all' ? 'all' : facetShort(f))}</button>`).join('')}</div>`;
      } else {
        html += `<div class="tc-chips"><span class="tc-k">${label}</span><select data-tc-facet-select aria-label="${label}"><option value="all"${this.facet === 'all' ? ' selected' : ''}>all ${facets.length}</option>${facets.map((f) =>
          `<option value="${esc(f)}"${f === this.facet ? ' selected' : ''}>${esc(f)}</option>`).join('')}</select><span class="tc-mut">or click a column of the matrix below</span></div>`;
      }
    }
    const kpis = [ACC, ...C.costs.map((c) => c.id)];
    const speeds = m.speeds.length ? m.speeds : [null];
    const fw = (s) => ({ ...where, speed: s });
    const scale = {};
    for (const k of kpis) {
      const vals = [];
      for (const r of L) for (const s of speeds) { const c = m.value(k, 'config', r.name, fw(s)); if (c) vals.push(c.v); }
      scale[k] = extent(vals, k === ACC || field(k).log);
    }
    const wins = m.wins();
    this.winsOut = wins;
    const spark = m.speeds.length > 1;
    const sp = m.speeds.map(speedText).join(' → ');
    html += `<div class="tc-scroll"><table class="tc-ltable" data-tc-league><thead><tr><th class="tc-l">#</th><th class="tc-l">config<span class="tc-u">its deployment · a row: its worst targets</span></th>` +
      `<th>n<span class="tc-u">targets</span></th><th class="tc-l tc-prim">${esc(C.acc.label)}${esc(atTop(m))}<span class="tc-u">${esc(U())} · ×best · bar log</span></th>` +
      (spark ? `<th title="${esc(sp)}">vs speed<span class="tc-u">log · ${esc(speedText(m.speeds[0]))} → ${esc(speedText(m.top))}</span></th>` : '') +
      kpis.slice(1).map((k) => `<th>${esc(field(k).label)}<span class="tc-u">${esc(field(k).unit)}${esc(atTop(m))}${spark ? ' · vs speed' : ''}</span></th>`).join('') +
      (wins.cells ? `<th title="the (dataset · split, speed) cells with two or more configs where this config has the lowest ${esc(C.acc.label)}">best in<span class="tc-u">of its cells</span></th>` : '') +
      '<th></th></tr></thead><tbody>';
    const lo = Math.log10(scale[ACC].lo), hi = Math.log10(scale[ACC].hi);
    const kpiRows = {};
    const columns = 4 + (spark ? 1 : 0) + (kpis.length - 1) + (wins.cells ? 1 : 0) + 1;
    L.forEach((r, at) => {
      const c = r.config;
      const frac = hi > lo ? (Math.log10(r.v) - lo) / (hi - lo) : 0.5;
      const sparkOf = (k) => {
        const values = m.speeds.map((s) => { const x = m.value(k, 'config', r.name, fw(s)); return x ? x.v : null; });
        return sparkline(values, { ...scale[k], log: k === ACC || field(k).log, color: c.color, w: 56,
          title: `${r.name}: ${field(k).label} vs speed (${m.speeds.map((s, i) => `${speedText(s)} → ${num3(values[i])}`).join(', ')})` });
      };
      const w = wins.byConfig.get(r.name);
      html += `<tr data-tc-config="${esc(r.name)}" data-rank="${at + 1}"><td class="tc-l tc-rank">${at + 1}</td>` +
        `<td class="tc-l tc-cfg">${swatch(c)}${nameHtml(r.name, 32)}${depHtml(c)}</td><td>${r.n}</td>` +
        `<td class="tc-l tc-prim"><span class="tc-big">${num3(r.v)}</span><span class="tc-x${at === 0 ? ' tc-best' : ''}">${at === 0 ? 'best' : times(r.v / best.v)}</span>` +
        `<span class="tc-bar" style="--c:${c.color}"><i style="width:${Math.max(3, 100 * Math.max(0, Math.min(1, frac))).toFixed(1)}%"></i></span></td>` +
        (spark ? `<td>${sparkOf(ACC)}</td>` : '');
      kpiRows[r.name] = {};
      for (const k of kpis.slice(1)) {
        const x = m.value(k, 'config', r.name, where);
        kpiRows[r.name][k] = x ? x.v : null;
        html += `<td><div class="tc-kcell">${x ? `<span>${num3(x.v)}</span>` : '<span class="tc-mut" title="no run of this config has it here">—</span>'}${spark ? sparkOf(k) : ''}</div></td>`;
      }
      html += (wins.cells ? `<td>${w && w.of ? `<b>${w.wins}</b> <span class="tc-mut">of ${w.of}</span>` : '<span class="tc-mut">—</span>'}</td>` : '') +
        `<td><button type="button" class="tc-link" data-tc-worst="${esc(r.name)}" aria-expanded="${!!(this.drill && this.drill.config === r.name)}">worst targets ${this.drill && this.drill.config === r.name ? '↑' : '→'}</button></td></tr>`;
      if (this.drill && this.drill.config === r.name) html += `<tr class="tc-drillrow"><td colspan="${columns}">${this.drillHtml()}</td></tr>`;
    });
    this.kpiRows = kpiRows;
    html += '</tbody></table></div>';
    html += `<p class="tc-foot">Each value: the ${esc(C.rule)}, from the run tags ${kpis.map((k) => esc(field(k).label)).join(', ')}; n = targets of that config${esc(atTop(m))}${this.facet !== 'all' ? ' on ' + esc(this.facet) : ''}.` +
      (wins.cells ? ` “best in” counts the (dataset · split, speed) cells with two or more configs where it has the lowest ${esc(C.acc.label)}.` : '') + ` Colour = config.${fillNote(m)}</p>`;
    if (tc.matrix !== false) html += this.matrixHtml(facets);
    this.el.innerHTML = `<div class="tc tc-league">${html}</div>`;
  }
  // Nov 23's "Every dataset · split at 1×": a config × dataset · split heatmap, best in each column ringed, hatched = no runs
  matrixHtml(facets) {
    const m = this.m;
    const order = m.league(ACC, { speed: m.top });
    const grid = {};
    const vals = [];
    for (const r of order) {
      grid[r.name] = {};
      for (const f of facets) { const c = m.value(ACC, 'config', r.name, { speed: m.top, facet: f }); grid[r.name][f] = c; if (c) vals.push(c.v); }
    }
    const { lo, hi } = extent(vals, true);
    const bestOf = {};
    for (const f of facets) {
      const present = order.filter((r) => grid[r.name][f]);
      if (present.length) bestOf[f] = Math.min(...present.map((r) => grid[r.name][f].v));
    }
    this.heat = { facets, cells: order.flatMap((r) => facets.filter((f) => grid[r.name][f]).map((f) => [r.name, f, grid[r.name][f].v, grid[r.name][f].n])), best: bestOf };
    const groups = [];
    for (const f of facets) { const d = m.facetDeployment.get(f); if (!groups.length || groups[groups.length - 1].d !== d) groups.push({ d, n: 0 }); groups[groups.length - 1].n += 1; }
    let html = `<section class="tc-card tc-heat"><h3>Every dataset · split${esc(atTop(m))} <span class="tc-h">${esc(C.acc.label)}, ${esc(U())}, the ${esc(C.rule)} · ring = best in the column · hatched = no runs · click a column to switch the table above</span> ${rampLegend(lo, hi, U())}</h3>`;
    html += '<div class="tc-scroll"><table class="tc-mtable"><thead>';
    if (m.deployments.length > 1) html += `<tr><th class="tc-l tc-stick"></th>${groups.map((g) => `<th class="tc-grp" colspan="${g.n}" title="${esc(g.d)}">${esc(middle(String(g.d), 6 * g.n + 4))}</th>`).join('')}</tr>`;
    html += `<tr><th class="tc-l tc-stick">config</th>${facets.map((f) => {
      const [ds, split] = facetParts(f);
      return `<th class="tc-col${f === this.facet ? ' tc-on' : ''}" data-tc-facet="${esc(f)}" title="${esc(f)}: click to rank the League on it"><span class="tc-vh">${esc(ds)}</span>${split === null ? '' : `<span class="tc-u">${esc(split)}</span>`}</th>`;
    }).join('')}</tr></thead><tbody>`;
    for (const r of order) {
      html += `<tr><th class="tc-l tc-stick">${swatch(r.config)}${nameHtml(r.name, 30)}</th>${facets.map((f) => {
        const c = grid[r.name][f];
        if (!c) return `<td class="tc-none" title="${esc(r.name + ' · ' + f)}: no runs"></td>`;
        const isBest = c.v === bestOf[f];
        return `<td class="${isBest ? 'tc-r1' : ''}${f === this.facet ? ' tc-on' : ''}" ${heatCell(c.v, lo, hi, `title="${esc(`${r.name} · ${f}: ${num3(c.v)} ${U()}, median over ${c.n} targets${isBest ? ' · best in the column' : ''}`)}"`)}>${num3(c.v)}</td>`;
      }).join('')}</tr>`;
    }
    return html + '</tbody></table></div></section>';
  }
  hook() {
    const L = this.L || [];
    return { drill: this.drill ? { ...this.drill, rows: this.drillRows } : null, kind: 'league', top: this.m.top, facet: this.facet, configs: L.length,
      best: L[0] ? { config: L[0].name, v: L[0].v, n: L[0].n } : null,
      league: L.map((r) => [r.name, r.v, r.n]),
      kpis: this.kpiRows || {},
      wins: this.winsOut ? { cells: this.winsOut.cells, byConfig: [...this.winsOut.byConfig].filter(([, w]) => w.of).map(([c, w]) => [c, w.wins, w.of]) } : null,
      heat: this.heat || null,
      answer: (this.el.querySelector('[data-tc-answer]') || {}).textContent || null };
  }
}
/** "<dataset> · <deployment> · <split>" → [dataset without its deployment, split | null]. */
function facetParts(f) {
  const parts = String(f).split(' · ');
  if (parts.length >= 3) return [parts.slice(0, -2).join(' · '), parts[parts.length - 1]];
  return [datasetShort(f), null];
}
function facetShort(f) { const [ds, split] = facetParts(f); return split === null ? ds : `${ds} · ${split}`; }

/** Nov 23's sentence, over whatever the rail left. */
function leagueSentence(m, L, facet = 'all') {
  const best = L[0];
  const others = L.slice(1);
  const item = (r) => `${swatch(r.config)}<b>${esc(middle(r.name, 40))}</b> ${times(r.v / best.v)}`;
  let list = '';
  if (others.length && others.length <= 5) list = others.map(item).join(', ');
  else if (others.length) list = `${others.slice(0, 3).map(item).join(', ')}, … ${others.length - 4} more, up to ${item(others[others.length - 1])}`;
  const at = topText(m);
  return `${esc(at[0].toUpperCase() + at.slice(1))}${facet !== 'all' ? ` on <b>${esc(facet)}</b>` : ''}, ${swatch(best.config)}<b>${esc(best.name)}</b> <span class="tc-mut">(${esc(depText(best.config))})</span> ` +
    `has the lowest ${esc(C.acc.label)}: <b>${num3(best.v)} ${esc(U())}</b>${list ? `; the others are at ${list} of it` : ''}. ` +
    `<span class="tc-mut">Median over ${best.n} targets of each target’s median over its runs${depNote(m)}.</span>`;
}

// ═══ tc-matrix: model type → config × deployment → dataset, the column switchable ═══
class MatrixView extends Base {
  static type = 'tc-matrix';
  axes() {
    const m = this.m;
    const out = [{ id: 'dataset', label: 'Deployment › dataset' }];
    if ([...m.targets.values()].some((t) => t.split !== null)) out.push({ id: 'split', label: 'Split' });
    if (m.speeds.length > 1) out.push({ id: 'speed', label: 'Speed' });
    out.push({ id: 'deployment', label: 'Deployment' });
    return out;
  }
  onClick(e) {
    if (this.closeDrill(e)) return;
    const a = e.target.closest('[data-tc-axis]');
    if (a) { this.axis = a.dataset.tcAxis; this.drill = null; store.set(this.key('axis'), this.axis); this.draw(); return; }
    const g = e.target.closest('[data-tc-fold]');
    if (g) { const k = g.dataset.tcFold; this.folds[k] = !this.folds[k]; store.set(this.key('folds'), this.folds); this.draw(); return; }
    const all = e.target.closest('[data-tc-foldall]');
    if (all) { const close = all.dataset.tcFoldall === 'fold'; this.folds = Object.fromEntries(this.m.modelTypes.map((t) => [t, close])); store.set(this.key('folds'), this.folds); this.draw(); return; }
    const cell = e.target.closest('td[data-tc-cfg]');
    if (cell) {
      const col = cell.dataset.tcCol !== undefined ? this.cols[Number(cell.dataset.tcCol)] : null;
      this.openWorst(cell.dataset.tcCfg, col ? col.where : this.allWhere);
    }
  }
  cols_() {
    const m = this.m, top = m.top;
    if (this.axis === 'split') return m.columns('split', { speed: top }).sort().map((s) => ({ key: s, label: s, where: { speed: top, split: s } }));
    if (this.axis === 'speed') return m.speeds.map((s) => ({ key: String(s), label: speedText(s), where: { speed: s } }));
    if (this.axis === 'deployment') return m.deployments.filter((d) => m.columns('deployment', { speed: top }).includes(d)).map((d) => ({ key: d, label: middle(d, 24), title: d, where: { speed: top, deployment: d } }));
    return m.columns('dataset', { speed: top }).map((d) => ({ d, dep: m.datasetDeployment.get(d) }))
      .sort((a, b) => m.depOrder(a.dep) - m.depOrder(b.dep) || (a.d < b.d ? -1 : 1))
      .map((x) => ({ key: x.d, label: datasetShort(x.d), title: x.d, group: x.dep, where: { speed: top, dataset: x.d } }));
  }
  render() {
    const m = this.m;
    const axes = this.axes();
    if (this.axis === undefined) this.axis = store.get(this.key('axis'), this.tc.axis || 'dataset');
    if (!axes.some((a) => a.id === this.axis)) this.axis = 'dataset';
    if (!this.folds) this.folds = store.get(this.key('folds'), {});
    this.cols = null;
    if (!m.has) { this.el.innerHTML = empty('tc-matrix'); return; }
    const cols = this.cols = this.cols_();
    const allWhere = this.allWhere = this.axis === 'speed' ? {} : { speed: m.top };
    const rows = [];
    if (m.typed) {
      for (const mt of m.modelTypes) {
        const cfgs = m.configs.filter((c) => c.modelType === mt && m.value(ACC, 'config', c.name, allWhere));
        if (!cfgs.length) continue;
        rows.push({ kind: 'group', key: mt, cfgs });
        if (!this.folds[mt]) for (const c of cfgs) rows.push({ kind: 'config', key: c.name, c });
      }
    } else {
      // WHY flat without a model-type mapping: the writer was given none, so there is nothing to nest configs under
      for (const c of m.configs) if (m.value(ACC, 'config', c.name, allWhere)) rows.push({ kind: 'config', key: c.name, c });
    }
    const cell = (r, where) => (r.kind === 'group' ? m.value(ACC, 'mt', r.key, where) : m.value(ACC, 'config', r.key, where));
    const leaves = m.configs.filter((c) => m.value(ACC, 'config', c.name, allWhere));
    const vals = [];
    const out = [];
    for (const r of rows) for (const col of cols) { const x = cell(r, col.where); if (x) { vals.push(x.v); out.push([r.kind, r.key, col.key, x.v, x.n]); } }
    for (const c of leaves) for (const col of cols) { const x = m.value(ACC, 'config', c.name, col.where); if (x) vals.push(x.v); }
    const { lo, hi } = extent(vals, true);
    const colBest = cols.map((col) => {
      let best = null;
      for (const c of leaves) { const x = m.value(ACC, 'config', c.name, col.where); if (x && (!best || x.v < best.v)) best = { c, v: x.v, n: x.n }; }
      return best;
    });
    const mtBest = m.typed ? cols.map((col) => {
      let best = null;
      for (const mt of m.modelTypes) { const x = m.value(ACC, 'mt', mt, col.where); if (x && (!best || x.v < best.v)) best = { mt, v: x.v }; }
      return best;
    }) : [];
    // the answer, read off the matrix: who holds the most column bests
    const countBy = (list, k) => { const n = new Map(); for (const b of list) if (b) n.set(k(b), (n.get(k(b)) || 0) + 1); return [...n].sort((a, b) => b[1] - a[1]); };
    const cfgWins = countBy(colBest, (b) => b.c.name);
    const mtWins = countBy(mtBest, (b) => b.mt);
    const filled = colBest.filter(Boolean).length;
    const axisWord = { dataset: 'dataset', split: 'split', speed: 'speed', deployment: 'deployment' }[this.axis];
    const cfgOf = (name) => m.configOf.get(name);
    const overall = m.league(ACC, allWhere)[0];
    const typeLabel = String(C.modelTypeLabel || 'model type').toLowerCase();
    let answer = '';
    if (cfgWins.length) {
      answer = `${swatch(cfgOf(cfgWins[0][0]))}<b>${esc(cfgWins[0][0])}</b> <span class="tc-mut">(${esc(depText(cfgOf(cfgWins[0][0])))})</span> is the best config in <b>${cfgWins[0][1]}</b> of the <b>${filled}</b> ${axisWord} columns` +
        (cfgWins[1] ? `, ${swatch(cfgOf(cfgWins[1][0]))}<b>${esc(cfgWins[1][0])}</b> in ${cfgWins[1][1]}` : '') +
        (mtWins.length ? `; the best ${esc(typeLabel)} is <b>${esc(mtWins[0][0])}</b> in <b>${mtWins[0][1]}</b>` : '') +
        `. <span class="tc-mut">Overall ${this.axis === 'speed' ? 'over every speed' : esc(topText(m))}: ${esc(overall.name)} ${num3(overall.v)} ${esc(U())}${depNote(m)}.</span>`;
    }
    this.answer = { cfgWins, mtWins, filled };
    let html = `<p class="tc-answer" data-tc-answer>${answer}</p>`;
    html += `<div class="tc-chips"><span class="tc-k">Columns</span>${axes.map((a) => `<button type="button" data-tc-axis="${a.id}" aria-pressed="${a.id === this.axis}">${esc(a.label)}</button>`).join('')}` +
      `<span class="tc-sp"></span>${m.typed ? '<button type="button" class="tc-link" data-tc-foldall="unfold">Unfold all</button><button type="button" class="tc-link" data-tc-foldall="fold">Fold all</button>' : ''}${rampLegend(lo, hi, U())}</div>`;
    const groups = [];
    if (this.axis === 'dataset') for (const col of cols) { if (!groups.length || groups[groups.length - 1].d !== col.group) groups.push({ d: col.group, n: 0 }); groups[groups.length - 1].n += 1; }
    html += `<div class="tc-scroll"><table class="tc-mtable tc-nested" data-tc-matrix data-axis="${this.axis}"><thead>`;
    if (groups.length > 1) html += `<tr><th class="tc-l tc-stick"></th>${groups.map((g) => `<th class="tc-grp" colspan="${g.n}" title="${esc(g.d)}">${esc(middle(String(g.d), 6 * g.n + 4))}</th>`).join('')}<th class="tc-grp"></th></tr>`;
    html += `<tr><th class="tc-l tc-stick">${m.typed ? `${esc(typeLabel)} <span class="tc-u">› config</span>` : 'config'}</th>${cols.map((c) => `<th class="tc-col" title="${esc(c.title || c.label)}"><span class="tc-vh">${esc(c.label)}</span></th>`).join('')}<th class="tc-col tc-roll" title="the row over every column"><span class="tc-vh">every ${axisWord}</span></th></tr>`;
    html += `<tr class="tc-rollrow"><th class="tc-l tc-stick">best config in the column</th>${colBest.map((b, i) => (b
      ? `<td title="${esc(`${cols[i].title || cols[i].label}: best ${b.c.name} ${num3(b.v)} ${U()} over ${b.n} targets`)}"><i class="tc-sw" style="--c:${b.c.color}"></i>${num3(b.v)}</td>`
      : '<td class="tc-none" title="no runs"></td>')).join('')}<td></td></tr></thead><tbody>`;
    for (const r of rows) {
      const isG = r.kind === 'group';
      const head = isG
        ? `<button type="button" class="tc-chev" data-tc-fold="${esc(r.key)}" aria-expanded="${!this.folds[r.key]}">${this.folds[r.key] ? '▸' : '▾'}</button>${nameHtml(r.key, 40, 'tc-name tc-gname')} <span class="tc-mut">${plural(r.cfgs.length, 'config')}</span>`
        : `${m.typed ? '<span class="tc-indent"></span>' : ''}${swatch(r.c)}${nameHtml(r.key, 30)}${depHtml(r.c)}`;
      html += `<tr class="${isG ? 'tc-grow' : 'tc-leaf'}"><th class="tc-l tc-stick">${head}</th>${cols.map((col, i) => {
        const x = cell(r, col.where);
        if (!x) return `<td class="tc-none" title="${esc(`${r.key} · ${col.title || col.label}`)}: no runs"></td>`;
        const ring = !isG && colBest[i] && colBest[i].c.name === r.key;
        const tip = `${r.key} · ${col.title || col.label}: ${num3(x.v)} ${U()}, median over ${x.n} targets${isG ? ' (every run of this group on a target, then over targets)' : ''}${ring ? ' · best in the column' : ''}`;
        return `<td class="${ring ? 'tc-r1' : ''}${isG ? ' tc-gcell' : ''}" ${isG ? '' : `data-tc-cfg="${esc(r.key)}" data-tc-col="${i}"`} ${heatCell(x.v, lo, hi, `title="${esc(tip)}"`)}>${num3(x.v)}</td>`;
      }).join('')}${(() => {
        const x = cell(r, allWhere);
        return x ? `<td class="tc-roll${isG ? ' tc-gcell' : ''}" ${isG ? '' : `data-tc-cfg="${esc(r.key)}"`} ${heatCell(x.v, lo, hi, `title="${esc(`${r.key} over every ${axisWord}: ${num3(x.v)} ${U()}, median over ${x.n} targets`)}"`)}>${num3(x.v)}</td>` : '<td class="tc-none"></td>';
      })()}</tr>`;
    }
    html += '</tbody></table></div>';
    html += this.drillHtml();
    html += `<p class="tc-foot">Cell: ${esc(C.acc.label)}, ${esc(U())}, the ${esc(C.rule)}${this.axis === 'speed' ? '' : `, ${esc(topText(m))}`}.` +
      (m.typed ? ` A ${esc(typeLabel)}’s row: every run of its configs on a target, then over targets; the mapping of configs to it is the caller’s.` : '') +
      ` Ring = best config in the column; hatched = no runs; a cell opens that config’s worst targets there.${fillNote(m)}</p>`;
    this.out = out;
    this.colBest = colBest;
    this.el.innerHTML = `<div class="tc tc-matrix">${html}</div>`;
  }
  hook() {
    if (!this.cols) return { kind: 'matrix', empty: true };
    return { drill: this.drill ? { ...this.drill, rows: this.drillRows } : null, kind: 'matrix', axis: this.axis, top: this.m.top, columns: this.cols.map((c) => c.key),
      cells: this.out, best: this.colBest.map((b, i) => (b ? [this.cols[i].key, b.c.name, b.v] : null)).filter(Boolean),
      rows: this.el.querySelectorAll('[data-tc-matrix] tbody tr').length, answer: this.answer,
      answerText: (this.el.querySelector('[data-tc-answer]') || {}).textContent || null };
  }
}

// ═══ tc-sweep: speed is the x axis, one line per config, small multiples ═══
class SweepView extends Base {
  static type = 'tc-sweep';
  onClick(e) {
    if (this.closeDrill(e)) return;
    const f = e.target.closest('[data-tc-by]');
    if (f) { this.by = f.dataset.tcBy; store.set(this.key('by'), this.by); this.draw(); return; }
    const w = e.target.closest('[data-tc-worst]');
    if (w) this.openWorst(w.dataset.tcWorst, { speed: Number(w.dataset.tcSpeed) });
  }
  render() {
    const m = this.m;
    if (this.by === undefined) this.by = store.get(this.key('by'), this.tc.by || (m.typed ? 'model_type' : 'deployment'));
    if (!m.typed) this.by = 'deployment';
    this.panels = [];
    if (!m.has || m.top === null) { this.el.innerHTML = empty('tc-sweep'); return; }
    const facets = this.by === 'deployment' ? m.deployments : m.modelTypes;
    const panels = [];
    const vals = [];
    for (const f of facets) {
      const lines = [];
      for (const c of m.configs) {
        if (this.by === 'deployment' ? !c.deployments.has(f) : c.modelType !== f) continue;
        const pts = m.speeds.map((s) => { const x = m.value(ACC, 'config', c.name, this.by === 'deployment' ? { speed: s, deployment: f } : { speed: s }); return x ? { s, v: x.v, n: x.n } : null; }).filter(Boolean);
        if (!pts.length) continue;
        for (const p of pts) vals.push(p.v);
        lines.push({ c, pts });
      }
      if (lines.length) panels.push({ f, lines });
    }
    const { lo, hi } = extent(vals, true);
    this.panels = panels;
    // the answer: the best config at the slowest and at the fastest speed, and how the fastest one's error grows
    const slow = m.league(ACC, { speed: m.slowest })[0];
    const fast = m.league(ACC, { speed: m.top })[0];
    const fastSlow = fast ? m.value(ACC, 'config', fast.name, { speed: m.slowest }) : null;
    this.answer = { slow: slow ? [slow.name, slow.v] : null, fast: fast ? [fast.name, fast.v] : null, growth: fastSlow ? fast.v / fastSlow.v : null };
    let html = `<p class="tc-answer" data-tc-answer>At <b>${speedText(m.slowest)}</b> the best is ${swatch(slow.config)}<b>${esc(slow.name)}</b> (${num3(slow.v)} ${esc(U())}); at <b>${speedText(m.top)}</b> ${swatch(fast.config)}<b>${esc(fast.name)}</b> (${num3(fast.v)} ${esc(U())})` +
      (fastSlow && m.slowest !== m.top ? `, whose error grows <b>${times(fast.v / fastSlow.v)}</b> from ${speedText(m.slowest)} to ${speedText(m.top)}` : '') +
      `. <span class="tc-mut">Each point: the ${esc(C.rule)} at that speed${depNote(m)}.</span></p>`;
    html += '<div class="tc-chips"><span class="tc-k">One panel per</span>' +
      (m.typed ? `<button type="button" data-tc-by="model_type" aria-pressed="${this.by === 'model_type'}">${esc(String(C.modelTypeLabel || 'model type').toLowerCase())}</button>` : '') +
      `<button type="button" data-tc-by="deployment" aria-pressed="${this.by === 'deployment'}">deployment</button>` +
      '<span class="tc-sp"></span><span class="tc-mut">one line per config · log y, shared by every panel · a name at each line’s end (hover for the whole name and every point)</span></div>';
    const width = Math.max(600, (this.el.clientWidth || 1100) - 8);
    const per = panels.length <= 2 ? panels.length || 1 : panels.length <= 4 ? 2 : 3;
    const W = Math.floor((width - (per - 1) * 12) / per), H = 250;
    html += `<div class="tc-multiples" style="grid-template-columns:repeat(${per}, ${W}px)">${panels.map((p) => this.panelSvg(p, W, H, lo, hi)).join('')}</div>`;
    // the sweep table under it: config × speed, best per speed marked
    const order = [...m.league(ACC, { speed: m.top }).map((r) => r.config), ...m.configs.filter((c) => !m.value(ACC, 'config', c.name, { speed: m.top }))];
    const bestAt = new Map(m.speeds.map((s) => { const b = m.league(ACC, { speed: s })[0]; return [s, b ? b.name : null]; }));
    this.table = [];
    html += `<div class="tc-scroll"><table class="tc-stable"><thead><tr><th class="tc-l">config</th>${m.typed ? `<th class="tc-l">${esc(String(C.modelTypeLabel).toLowerCase())}</th>` : ''}${m.speeds.map((s) => `<th>${speedText(s)}<span class="tc-u">${esc(U())} · n targets</span></th>`).join('')}</tr></thead><tbody>`;
    for (const c of order) {
      html += `<tr><td class="tc-l tc-cfg">${swatch(c)}${nameHtml(c.name, 40)}${depHtml(c)}</td>${m.typed ? `<td class="tc-l tc-mut">${esc(c.modelType)}</td>` : ''}${m.speeds.map((s) => {
        const x = m.value(ACC, 'config', c.name, { speed: s });
        if (!x) return '<td class="tc-mut">—</td>';
        this.table.push([c.name, s, x.v, x.n]);
        const best = bestAt.get(s) === c.name;
        return `<td><button type="button" class="tc-cellbtn" data-tc-worst="${esc(c.name)}" data-tc-speed="${s}" title="${esc(c.name)} at ${speedText(s)}: its worst targets">${num3(x.v)}</button> <span class="tc-mut">n ${x.n}</span>${best ? ' <span class="tc-bestchip">best</span>' : ''}</td>`;
      }).join('')}</tr>`;
      if (this.drill && this.drill.config === c.name) html += `<tr class="tc-drillrow"><td colspan="${1 + (m.typed ? 1 : 0) + m.speeds.length}">${this.drillHtml()}</td></tr>`;
    }
    html += `</tbody></table></div><p class="tc-foot">Each value: the ${esc(C.rule)} at that speed; n = targets. “best” = the lowest at that speed among every config left. A value opens that config’s worst targets at that speed.${fillNote(m)}</p>`;
    this.el.innerHTML = `<div class="tc tc-sweep">${html}</div>`;
  }
  panelSvg(p, W, H, lo, hi) {
    const m = this.m;
    const L = 40, R = 150, T = 10, B = 30;
    const s0 = Math.min(...m.speeds), s1 = Math.max(...m.speeds);
    const x = (s) => L + (s1 > s0 ? (s - s0) / (s1 - s0) : 0.5) * (W - L - R);
    const y = (v) => T + (1 - logT(v, lo, hi)) * (H - T - B);
    const decades = [];
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e += 1) { const v = 10 ** e; if (v >= lo * 0.999 && v <= hi * 1.001) decades.push(v); }
    let svg = `<svg class="tc-panel" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(p.f)}">`;
    svg += decades.map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="tc-grid"/><text x="${L - 4}" y="${(y(v) + 3).toFixed(1)}" class="tc-tick" text-anchor="end">${num3(v)}</text>`).join('');
    svg += m.speeds.map((s) => `<text x="${x(s).toFixed(1)}" y="${H - B + 14}" class="tc-tick" text-anchor="middle">${speedText(s)}</text>`).join('');
    svg += `<text x="${L}" y="${H - 4}" class="tc-tick">${esc(C.speed ? C.speed.label : 'speed')} →</text>`;
    const labels = [];
    const short = (s) => (s.length > 22 ? `${s.slice(0, 9)}…${s.slice(-12)}` : s);
    let singles = 0;
    for (const ln of p.lines) {
      const d = ln.pts.map((pt, i) => `${i ? 'L' : 'M'}${x(pt.s).toFixed(1)} ${y(pt.v).toFixed(1)}`).join('');
      const one = ln.pts.length === 1;
      if (!one) svg += `<path d="${d}" fill="none" stroke="${ln.c.color}" stroke-width="1.8"/>`;
      svg += ln.pts.map((pt) => `<circle cx="${x(pt.s).toFixed(1)}" cy="${y(pt.v).toFixed(1)}" r="${one ? 2.6 : 3}" fill="${ln.c.color}"${one ? ' fill-opacity="0.55"' : ''}><title>${esc(`${ln.c.name} · ${speedText(pt.s)}: ${num3(pt.v)} ${U()}, median over ${pt.n} targets${one ? ' (its only speed)' : ''}`)}</title></circle>`).join('');
      // WHY a single-speed config gets no label in a crowded panel: one-off configs ran at one speed only and their long
      // names crowded the lines that do sweep; each dot still names itself on hover
      if (one && p.lines.length > 6) { singles += 1; continue; }
      const last = ln.pts[ln.pts.length - 1];
      labels.push({ y: y(last.v) + 3, x: W - R + 6, c: ln.c, text: short(ln.c.name) });
    }
    placeLabels(labels, { gap: 11, top: T + 6, bottom: H - B });
    svg += labels.map((l) => `<text x="${l.x}" y="${l.y.toFixed(1)}" class="tc-dl" fill="${l.c.color}">${esc(l.text)}<title>${esc(l.c.name)}</title></text>`).join('');
    svg += '</svg>';
    return `<figure class="tc-fig"><figcaption>${nameHtml(p.f, 44, 'tc-name tc-gname')} <span class="tc-mut">${plural(p.lines.length, 'config')}${singles ? ` · ${singles} ran at one speed only: dots, hover for names` : ''}</span></figcaption>${svg}</figure>`;
  }
  hook() {
    return { drill: this.drill ? { ...this.drill, rows: this.drillRows } : null, kind: 'sweep', by: this.by, panels: (this.panels || []).map((p) => p.f),
      cells: (this.panels || []).flatMap((p) => p.lines.flatMap((ln) => ln.pts.map((pt) => [p.f, ln.c.name, pt.s, pt.v, pt.n]))),
      table: this.table || [], answer: this.answer, answerText: (this.el.querySelector('[data-tc-answer]') || {}).textContent || null };
  }
}

// ═══ tc-tradeoff: accuracy against a cost, one point per config, the Pareto frontier ═══
/** One deployment's points (config: cost x, accuracy y, n targets) at the fastest speed, and its frontier. */
function frontierOf(m, cost, d) {
  const pts = [];
  for (const c of m.configs) {
    if (!c.deployments.has(d)) continue;
    const yv = m.value(ACC, 'config', c.name, { speed: m.top, deployment: d });
    const xv = m.value(cost, 'config', c.name, { speed: m.top, deployment: d });
    // WHY a log cost's median must be > 0: a log axis has no zero (the round's oracle.py, tradeoff)
    if (!yv || !xv || (field(cost).log && !(xv.v > 0))) continue;
    pts.push({ c, x: xv.v, y: yv.v, n: yv.n });
  }
  return { d, pts, front: m.pareto(pts).sort((a, b) => a.x - b.x) };
}
class TradeoffView extends Base {
  static type = 'tc-tradeoff';
  onClick(e) {
    if (this.closeDrill(e)) return;
    const f = e.target.closest('[data-tc-cost]');
    if (f) { this.cost = f.dataset.tcCost; store.set(this.key('cost'), this.cost); this.draw(); return; }
    const w = e.target.closest('[data-tc-worst]');
    if (w) this.openWorst(w.dataset.tcWorst, { speed: this.m.top, deployment: w.dataset.tcDep });
  }
  render() {
    const m = this.m;
    const costs = C.costs.map((c) => c.id);
    if (this.cost === undefined) this.cost = store.get(this.key('cost'), this.tc.cost || costs[0]);
    if (!costs.includes(this.cost)) this.cost = costs[0];
    this.F = [];
    if (!m.has || !costs.length) { this.el.innerHTML = empty('tc-tradeoff'); return; }
    const F = this.F = m.deployments.map((d) => frontierOf(m, this.cost, d)).filter((f) => f.pts.length);
    const cu = field(this.cost);
    const sentence = F.map((f) => {
      const acc = f.front.reduce((a, b) => (b.y < a.y ? b : a));
      const cheap = f.front[0];
      const lead = `In <b>${esc(f.d)}</b> the frontier is ${plural(f.front.length, 'config')}`;
      if (acc === cheap) return `${lead}: ${swatch(acc.c)}<b>${esc(acc.c.name)}</b> is both the most accurate (${num3(acc.y)} ${esc(U())}) and the least ${esc(cu.short)} (${num3(acc.x)} ${esc(cu.unit)})`;
      return `${lead}: the most accurate ${swatch(acc.c)}<b>${esc(acc.c.name)}</b> (${num3(acc.y)} ${esc(U())} at ${num3(acc.x)} ${esc(cu.unit)}) … the least ${esc(cu.short)} ${swatch(cheap.c)}<b>${esc(cheap.c.name)}</b> (${num3(cheap.x)} ${esc(cu.unit)} at ${times(cheap.y / acc.y)} the RMS)`;
    });
    this.sentences = sentence;
    let html = `<p class="tc-answer" data-tc-answer>${F.length ? `${sentence[0]}.` : `No config left has both a ${esc(C.acc.label)} and a ${esc(cu.label)}.`}${F.length > 1 ? ` <span class="tc-mut">${plural(F.length - 1, 'more deployment')} below, each with its own frontier.</span>` : ''} <span class="tc-mut">Each point: a config’s ${esc(C.rule)} ${esc(topText(m))}; on the frontier = no other config of that deployment is both more accurate and cheaper${depNote(m)}.</span></p>`;
    html += `<div class="tc-chips"><span class="tc-k">Cost (x)</span>${costs.map((c) => `<button type="button" data-tc-cost="${esc(c)}" aria-pressed="${c === this.cost}">${esc(field(c).label)} <span class="tc-u">${esc(field(c).unit)}</span></button>`).join('')}` +
      '<span class="tc-sp"></span><span class="tc-mut">one panel per deployment · point size = n targets · ringed = on the frontier · y log, shared</span></div>';
    const vals = F.flatMap((f) => f.pts.map((p) => p.y));
    const { lo, hi } = extent(vals, true);
    const width = Math.max(600, (this.el.clientWidth || 1100) - 8);
    const per = F.length <= 1 ? 1 : 2;
    const W = Math.floor((width - (per - 1) * 12) / per), H = F.length <= 2 ? 330 : 260;
    html += `<div class="tc-multiples" style="grid-template-columns:repeat(${per}, ${W}px)">${F.map((f, i) => this.panelSvg(f, W, H, lo, hi, F.length > 1 ? sentence[i] : '')).join('')}</div>`;
    html += `<div class="tc-scroll"><table class="tc-stable"><thead><tr><th class="tc-l">deployment</th><th class="tc-l">config</th><th>${esc(C.acc.label)}<span class="tc-u">${esc(U())}${esc(atTop(m))}</span></th><th>${esc(cu.label)}<span class="tc-u">${esc(cu.unit)}${esc(atTop(m))}</span></th><th>n<span class="tc-u">targets</span></th><th>frontier</th><th></th></tr></thead><tbody>`;
    for (const f of F) {
      for (const p of f.pts.slice().sort((a, b) => a.y - b.y)) {
        const on = f.front.includes(p);
        const open = this.drill && this.drill.config === p.c.name && this.drill.where.deployment === f.d;
        html += `<tr${on ? ' class="tc-onfront"' : ''}><td class="tc-l tc-mut">${esc(middle(f.d, 30))}</td><td class="tc-l tc-cfg">${swatch(p.c)}${nameHtml(p.c.name, 44)}</td><td>${num3(p.y)}</td><td>${num3(p.x)}</td><td>${p.n}</td><td>${on ? '● on it' : ''}</td><td><button type="button" class="tc-link" data-tc-worst="${esc(p.c.name)}" data-tc-dep="${esc(f.d)}" aria-expanded="${!!open}">worst targets ${open ? '↑' : '→'}</button></td></tr>`;
        if (open) html += `<tr class="tc-drillrow"><td colspan="7">${this.drillHtml()}</td></tr>`;
      }
    }
    html += `</tbody></table></div><p class="tc-foot">Each value: the ${esc(C.rule)}, ${esc(topText(m))}, within its deployment (a config on two deployments is a point in each). A config with no ${esc(cu.label)} tag is left out of that panel.${fillNote(m)}</p>`;
    this.el.innerHTML = `<div class="tc tc-tradeoff">${html}</div>`;
  }
  panelSvg(f, W, H, lo, hi, sentence = '') {
    const cu = field(this.cost);
    const L = 48, R = 16, T = 12, B = 34;
    const xs = f.pts.map((p) => p.x);
    let x0 = Math.min(...xs), x1 = Math.max(...xs);
    if (cu.log) { x0 /= 1.4; x1 *= 1.4; } else { const pad = (x1 - x0) * 0.08 || Math.abs(x0) * 0.1 || 1; x0 -= pad; x1 += pad; }
    const X = (v) => L + (cu.log ? logT(v, x0, x1) : linT(v, x0, x1)) * (W - L - R);
    const yl = lo / 1.6, yh = hi * 1.6;
    const Y = (v) => T + (1 - logT(v, yl, yh)) * (H - T - B);
    const nmax = Math.max(...f.pts.map((p) => p.n));
    const short = (s) => (s.length > 24 ? `${s.slice(0, 10)}…${s.slice(-13)}` : s);
    const r = (n) => 3 + 7 * Math.sqrt(n / nmax);
    let svg = `<svg class="tc-panel" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(f.d)}">`;
    for (let e = Math.floor(Math.log10(yl)); e <= Math.ceil(Math.log10(yh)); e += 1) {
      const v = 10 ** e; if (v < yl || v > yh) continue;
      svg += `<line x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="tc-grid"/><text x="${L - 4}" y="${(Y(v) + 3).toFixed(1)}" class="tc-tick" text-anchor="end">${num3(v)}</text>`;
    }
    const ticks = cu.log ? (() => { const t = []; for (let e = Math.floor(Math.log10(x0)); e <= Math.ceil(Math.log10(x1)); e += 1) { const v = 10 ** e; if (v >= x0 && v <= x1) t.push(v); } return t; })()
      : (() => { let step = 10 ** Math.floor(Math.log10((x1 - x0) / 3)); while ((x1 - x0) / step > 6) step *= (String(step)[0] === '2' ? 2.5 : 2); const t = []; for (let v = Math.ceil(x0 / step) * step; v <= x1; v += step) t.push(Number(v.toPrecision(6))); return t; })();
    svg += ticks.map((v) => `<text x="${X(v).toFixed(1)}" y="${H - B + 14}" class="tc-tick" text-anchor="middle">${num3(v)}</text>`).join('');
    svg += `<text x="${W - R}" y="${H - 4}" class="tc-tick" text-anchor="end">${esc(cu.label)}, ${esc(cu.unit)} → (less is cheaper)</text><text x="${L}" y="${T - 2}" class="tc-tick">↓ more accurate (${esc(C.acc.short)}, ${esc(U())}, log)</text>`;
    if (f.front.length > 1) {
      let d = `M${X(f.front[0].x).toFixed(1)} ${Y(f.front[0].y).toFixed(1)}`;
      for (const p of f.front.slice(1)) d += `H${X(p.x).toFixed(1)}V${Y(p.y).toFixed(1)}`;
      svg += `<path d="${d}" class="tc-front"/>`;
    }
    const labels = [];
    for (const p of f.pts) {
      const on = f.front.includes(p);
      svg += `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="${r(p.n).toFixed(1)}" fill="${p.c.color}" fill-opacity="${on ? 0.9 : 0.45}" class="${on ? 'tc-onring' : ''}"><title>${esc(`${p.c.name} (${f.d}): ${num3(p.y)} ${U()} at ${num3(p.x)} ${cu.unit}, median over ${p.n} targets${on ? ' · on the frontier' : ''}`)}</title></circle>`;
      if (on || f.pts.length <= 6) labels.push({ x: X(p.x) + r(p.n) + 3, y: Y(p.y) + 3, c: p.c, on, text: short(p.c.name) });
    }
    for (const l of labels) l.x = Math.min(l.x, W - R - 6 * l.text.length);
    placeLabels(labels, { gap: 11, top: T + 8, bottom: H - B });
    svg += labels.map((l) => `<text x="${l.x.toFixed(1)}" y="${l.y.toFixed(1)}" class="tc-dl${l.on ? ' tc-dl-on' : ''}">${esc(l.text)}<title>${esc(l.c.name)}</title></text>`).join('');
    return `<figure class="tc-fig"><figcaption><b>${esc(f.d)}</b> <span class="tc-mut">${plural(f.pts.length, 'config')} · ${f.front.length} on the frontier</span><div class="tc-figans">${sentence}</div></figcaption>${svg}</svg></figure>`;
  }
  hook() {
    return { drill: this.drill ? { ...this.drill, rows: this.drillRows } : null, kind: 'tradeoff', cost: this.cost, top: this.m.top,
      points: (this.F || []).flatMap((f) => f.pts.map((p) => [f.d, p.c.name, p.x, p.y, p.n])),
      frontier: (this.F || []).flatMap((f) => f.front.map((p) => [f.d, p.c.name])),
      answerText: (this.el.querySelector('[data-tc-answer]') || {}).textContent || null };
  }
}

// ═══ tc-tile: one calm headline number and a small figure; its panel's Open goes to the full view's page ═══
class TileView extends Base {
  static type = 'tc-tile';
  render() {
    const m = this.m, kind = this.tc.tile;
    const t = TILES[kind];
    this.nums = null;
    if (!t || !m.has) { this.el.innerHTML = `<div class="tc tc-tile"><p class="tc-mut">No run left has a ${esc(C.acc.label)}.</p></div>`; return; }
    const out = t(m);
    if (!out) { this.el.innerHTML = `<div class="tc tc-tile"><p class="tc-mut">Nothing to say here for the runs left.</p></div>`; return; }
    this.nums = out.numbers;
    this.el.innerHTML = `<div class="tc tc-tile" data-tile="${esc(kind)}"><div class="tc-tnum" data-tc-answer>${out.big}</div><div class="tc-tsub">${out.sub}</div><div class="tc-tfig">${out.fig || ''}</div></div>`;
  }
  hook() { return { kind: 'tile', tile: this.tc.tile, numbers: this.nums, answerText: (this.el.querySelector('.tc-tile') || {}).textContent || null }; }
}
function dotStrip(items, { lo, hi, W = 300, H = 34 }) {
  const X = (v) => 8 + logT(v, lo, hi) * (W - 16);
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" class="tc-strip tc-mini"><line x1="8" x2="${W - 8}" y1="${H / 2}" y2="${H / 2}" class="tc-axis"/>` +
    items.map((it) => `<circle cx="${X(it.v).toFixed(1)}" cy="${H / 2}" r="4" fill="${it.color}" fill-opacity="0.75"><title>${esc(it.title)}</title></circle>`).join('') +
    `<text x="8" y="${H - 1}" class="tc-tick">${num3(lo)} ${esc(U())}</text><text x="${W - 8}" y="${H - 1}" class="tc-tick" text-anchor="end">${num3(hi)} ${esc(U())} · log</text></svg>`;
}
const TILES = {
  best(m) {
    const L = m.league(ACC, { speed: m.top });
    const b = L[0], n2 = L[1];
    if (!b) return null;
    return {
      numbers: { config: b.name, v: b.v, n: b.n, next: n2 ? [n2.name, n2.v / b.v] : null, configs: L.length },
      big: `${swatch(b.config)}${nameHtml(b.name, 26)} <span class="tc-tval">${num3(b.v)} ${esc(U())}</span>`,
      sub: `the lowest ${esc(C.acc.label)} ${esc(topText(m))} of ${plural(L.length, 'config')}${n2 ? `; next ${esc(n2.name)} at ${times(n2.v / b.v)}` : ''}<span class="tc-mut"> · ${esc(C.rule)}, n ${b.n}${depNote(m)}</span>`,
      fig: `<div class="tc-top5">${L.slice(0, 5).map((r, i) => `<span class="tc-r">${i + 1}</span><span>${swatch(r.config)}${nameHtml(r.name, 30)} <span class="tc-mut">${esc(middle(depText(r.config), 28))}</span></span><span class="tc-v">${num3(r.v)} ${esc(U())}</span><span class="tc-mut">${i ? times(r.v / b.v) : 'best'}</span>`).join('')}</div>${L.length > 5 ? `<div class="tc-mut" style="font-size:11.5px">… ${L.length - 5} more up to ${num3(L[L.length - 1].v)} ${esc(U())} (${times(L[L.length - 1].v / b.v)})</div>` : ''}`,
    };
  },
  coverage(m) {
    // a row per model type (or per config without a mapping), a column per dataset; filled = at least one run with a value
    const datasets = [...new Set([...m.targets.values()].map((t) => t.dataset))];
    datasets.sort((a, b) => m.depOrder(m.datasetDeployment.get(a)) - m.depOrder(m.datasetDeployment.get(b)) || (a < b ? -1 : 1));
    const groups = m.typed ? m.modelTypes : m.configs.map((c) => c.name);
    const filled = new Set();
    for (const r of m.rows) if (validRun(ACC, r[ACC])) filled.add(`${m.group(r)}\u0001${r.dataset}`);
    const cells = groups.length * datasets.length;
    const pct = cells ? (100 * filled.size) / cells : 0;
    const word = m.typed ? String(C.modelTypeLabel || 'model type').toLowerCase() : 'config';
    const cw = Math.max(4, Math.min(36, Math.floor(480 / Math.max(1, datasets.length))));
    const ch = Math.max(4, Math.min(14, Math.floor(120 / Math.max(1, groups.length))));
    const fig = `<svg width="${cw * datasets.length}" height="${groups.length * ch}" class="tc-mini">${groups.map((g, i) => datasets.map((d, j) =>
      `<rect x="${j * cw}" y="${i * ch}" width="${cw - 2}" height="${ch - 2}" rx="2" class="${filled.has(`${g}\u0001${d}`) ? 'tc-fill' : 'tc-empty'}"><title>${esc(`${g} · ${d}: ${filled.has(`${g}\u0001${d}`) ? 'runs' : 'no runs'}`)}</title></rect>`).join('')).join('')}</svg><div class="tc-mut" style="font-size:11.5px">a row per ${esc(word)}, a column per dataset (hover one); the full matrix behind Open</div>`;
    return {
      numbers: { pct, filled: filled.size, cells, groups: groups.length, datasets: datasets.length },
      big: `${Math.round(pct)} % <span class="tc-tval">of ${m.typed ? 'model' : 'config'} × dataset cells have runs</span>`,
      sub: `${filled.size} of ${cells} cells: ${plural(groups.length, word)} × ${plural(datasets.length, 'dataset')}; filled = at least one run with a ${esc(C.acc.label)}`,
      fig,
    };
  },
  speed(m) {
    const b = m.league(ACC, { speed: m.top })[0];
    if (!b || m.speeds.length < 2) return null;
    const values = m.speeds.map((s) => { const x = m.value(ACC, 'config', b.name, { speed: s }); return x ? x.v : null; });
    const first = values.find((v) => v !== null);
    const firstSpeed = m.speeds[values.indexOf(first)];
    const ratio = first ? b.v / first : null;
    const { lo, hi } = extent(values, true);
    return {
      numbers: { config: b.name, from: firstSpeed, v0: first, v1: b.v, ratio },
      big: `${times(ratio)} <span class="tc-tval">more error at ${speedText(m.top)}</span>`,
      sub: `${swatch(b.config)}<b>${esc(b.name)}</b>, ${num3(first)} → ${num3(b.v)} ${esc(U())} from ${speedText(firstSpeed)} to ${speedText(m.top)}`,
      fig: sparkline(values, { lo, hi, log: true, color: b.config.color, w: 260, h: 44, title: `${b.name} vs speed` }),
    };
  },
  cost(m) {
    const b = m.league(ACC, { speed: m.top })[0];
    const costId = C.costs.length ? C.costs[0].id : null;
    if (!b || !costId) return null;
    const cu = field(costId);
    const d = [...b.config.deployments].sort((x, y) => m.depOrder(x) - m.depOrder(y))[0];
    const { pts, front } = frontierOf(m, costId, d);
    if (!front.length) return null;
    const acc = front.reduce((a, p) => (p.y < a.y ? p : a), front[0]);
    const cheap = front[0];
    // WHY so few words: the tile is three rows tall and its figure must fit; the Trade-off page says the rest
    const fig = `<div class="tc-top5">${front.map((p, i) => `<span class="tc-r">${i + 1}</span><span>${swatch(p.c)}${nameHtml(p.c.name, 28)}</span><span class="tc-v">${num3(p.x)} ${esc(cu.unit)}</span><span class="tc-mut">${num3(p.y)} ${esc(U())}</span>`).join('')}</div>`;
    const beaten = pts.length - front.length;
    return {
      numbers: { cost: costId, deployment: d, frontier: front.map((p) => p.c.name), accurate: [acc.c.name, acc.x, acc.y], cheapest: [cheap.c.name, cheap.x, cheap.y] },
      big: `${front.length} <span class="tc-tval">on the frontier</span>`,
      sub: `${esc(C.acc.short)} against ${esc(cu.label)} in <b>${esc(d)}</b>${m.deployments.length > 1 ? ' (the best config’s)' : ''}: ${acc === cheap ? `${esc(acc.c.name)} is both the most accurate and the cheapest` : `${esc(cheap.c.name)} costs ${times(cheap.x / acc.x)} of ${esc(acc.c.name)} at ${times(cheap.y / acc.y)} its RMS`}${beaten ? `; ${plural(beaten, 'more config')} beaten on both` : ''}`,
      fig,
    };
  },
  worst(m) {
    const b = m.league(ACC, { speed: m.top })[0];
    if (!b) return null;
    const items = b.items.slice().sort((x, y) => y.v - x.v);
    const w = items[0];
    const { lo, hi } = extent(items.map((i) => i.v), true);
    const strip = dotStrip(items.map((i) => ({ v: i.v, color: b.config.color, title: `${i.t.target}: ${num3(i.v)} ${U()}` })), { lo, hi });
    return {
      numbers: { config: b.name, target: w.t.key, v: w.v, ratio: w.v / b.v, targets: items.length },
      big: `${num3(w.v)} ${esc(U())} <span class="tc-tval">${times(w.v / b.v)} its median</span>`,
      sub: `${swatch(b.config)}<b>${esc(b.name)}</b>’s worst target: <a href="${esc(targetHref(w.t))}" title="${esc(w.t.target)}: open its target view">${esc(middle(String(w.t.target), 60))}</a> <span class="tc-mut">${esc(datasetShort(w.t.dataset))}${w.t.split === null ? '' : ` · ${esc(w.t.split)}`}, of ${items.length}</span>`,
      fig: strip,
    };
  },
  left(m) {
    const runs = m.rows.length;
    const byDep = m.deployments.map((d) => [d, m.rows.filter((r) => r.deployment === d).length]);
    const datasets = new Set([...m.targets.values()].map((t) => t.dataset)).size;
    const W = 260;
    let x = 0;
    const fig = `<svg width="${W}" height="14" class="tc-mini">${byDep.map(([d, n], i) => { const w = (W * n) / runs; const s = `<rect x="${x.toFixed(1)}" y="0" width="${Math.max(1, w - 1).toFixed(1)}" height="12" class="tc-dep${i % 4}"><title>${esc(`${d}: ${n.toLocaleString('en-US')} runs`)}</title></rect>`; x += w; return s; }).join('')}</svg>`;
    return {
      numbers: { runs, targets: m.targets.size, configs: m.configs.length, deployments: m.deployments.length, datasets },
      big: `${runs.toLocaleString('en-US')} <span class="tc-tval">runs left</span>`,
      sub: `${m.targets.size.toLocaleString('en-US')} targets · ${plural(m.configs.length, 'config')} · ${plural(datasets, 'dataset')} · ${plural(m.deployments.length, 'deployment')} <span class="tc-mut">(${byDep.map(([d, n]) => `${esc(d)} ${n.toLocaleString('en-US')}`).join(' · ')})</span>`,
      fig,
    };
  },
};

// ═══ tc-worst: a config's worst targets, each linking its target view ═══
class WorstView extends Base {
  static type = 'tc-worst';
  onChange(e) { if (e.target.matches('select[data-tc-pick]')) { this.pick = e.target.value; this.draw(); } }
  render() {
    const m = this.m;
    this.rows = [];
    if (!m.has) { this.el.innerHTML = empty('tc-worst'); return; }
    const L = m.league(ACC, { speed: m.top });
    if (!L.length) { this.el.innerHTML = empty('tc-worst'); return; }
    if (!this.pick || !L.some((r) => r.name === this.pick)) this.pick = L[0].name;
    const r = L.find((x) => x.name === this.pick);
    const items = r.items.slice().sort((a, b) => b.v - a.v).slice(0, 25);
    this.rows = items.map((i) => [i.t.key, i.v]);
    let html = `<p class="tc-answer" data-tc-answer>${swatch(r.config)}<b>${esc(r.name)}</b>’s ${items.length} worst of ${r.n} targets${esc(atTop(m))}: the worst is <b>${num3(items[0].v)} ${esc(U())}</b>, ${times(items[0].v / r.v)} its median of ${num3(r.v)} ${esc(U())}. <span class="tc-mut">A target’s value: the median over its runs of this config.</span></p>`;
    html += `<div class="tc-chips"><span class="tc-k">Config</span><select data-tc-pick aria-label="Config">${L.map((x) => `<option value="${esc(x.name)}"${x.name === r.name ? ' selected' : ''}>${esc(x.name)} · ${num3(x.v)} ${esc(U())}</option>`).join('')}</select></div>`;
    html += `<div class="tc-scroll"><table class="tc-stable"><thead><tr><th class="tc-l">#</th><th class="tc-l">target</th><th class="tc-l">dataset · split</th><th>${esc(C.acc.short)}<span class="tc-u">${esc(U())}, median over its runs</span></th><th>× the config’s median</th><th>runs</th><th></th></tr></thead><tbody>`;
    items.forEach((i, k) => {
      html += `<tr><td class="tc-l tc-rank">${k + 1}</td><td class="tc-l">${nameHtml(i.t.target, 56)}</td><td class="tc-l tc-mut">${esc(datasetShort(i.t.dataset))}${i.t.split === null ? '' : ` · ${esc(i.t.split)}`}</td><td>${num3(i.v)}</td><td>${times(i.v / r.v)}</td><td>${i.runs.length}</td><td><a class="tc-link" href="${esc(targetHref(i.t))}">Open target view</a></td></tr>`;
    });
    this.el.innerHTML = `<div class="tc tc-worst">${html}</tbody></table></div><p class="tc-foot">Open target view: the target’s runs the rail keeps ticked, and ‹ All targets back to this filter and tab.${fillNote(m)}</p></div>`;
  }
  hook() { return { kind: 'worst', config: this.pick, rows: this.rows || [] }; }
}

// ═══ tc-pairs: "Does sim match real?" — one calm answer over the pairs the rail keeps ═══
/** The answer over one set of pairs (rows of pairs.json): median real ÷ predicted, n, how often real was worse. */
function pairsSummary(rows) {
  const ratios = rows.map((r) => r.ratio).filter((v) => finite(v) && v > 0);
  // WHY the writer's real_worse, not ratio > 1: ratio is rounded to 4 decimals, real_worse is decided on the exact one
  return { n: ratios.length, median: median(ratios), worse: rows.filter((r) => r.real_worse === 1).length };
}
const pct = (a, b) => (b ? `${Math.round((100 * a) / b)} %` : '—');
/** A ratio near 1 with two decimals (the round's "×1.21"), a large one as num3 does. */
const ratioText = (r) => (finite(r) ? `×${r < 10 ? r.toFixed(2) : num3(r)}` : '—');
class PairsView extends Base {
  static type = 'tc-pairs';
  update(input) {
    // WHY not buildModel: these rows are pairs (pairs.json), not runs
    this.input = input;
    this.tc = (input.view && input.view.tc) || {};
    this.rows = input.rows || [];
    this.draw();
  }
  render() {
    const P = C.pairs || {};
    const rows = this.rows;
    const against = [...new Set(rows.map((r) => r.against))].sort((a, b) => (P.against || []).indexOf(a) - (P.against || []).indexOf(b));
    this.summary = pairsSummary(rows);
    this.against = against.length === 1 ? against[0] : null;
    this.byAgainst = Object.fromEntries(against.map((a) => [a, pairsSummary(rows.filter((r) => r.against === a))]));
    const deployments = [...new Set(rows.map((r) => r.deployment))].sort((a, b) => (C.deployments || []).indexOf(a) - (C.deployments || []).indexOf(b));
    this.byDeployment = deployments.map((d) => [d, pairsSummary(rows.filter((r) => r.deployment === d))]);
    if (!rows.length) {
      // WHY one calm sentence and no number: a 0 or a "—" next to "real ÷ predicted" reads as a result
      const where = (P.deployments || []).length ? ` Real runs with a prediction beside them are in: ${P.deployments.map(esc).join(', ')}.` : '';
      this.el.innerHTML = `<div class="tc tc-pairs"><div class="tc-answer" data-tc-answer>No real run in this filter has a prediction of the same motion beside it, so there is nothing to compare here.<span class="tc-mut">${where}</span></div></div>`;
      return;
    }
    const label = esc(P.label || C.acc.label);
    const line = (a, s) => `On the real robot the ${label} is <b>${ratioText(s.median)}</b> what its <b>${esc(a)}</b> run predicted: median real ÷ predicted over <b>${s.n.toLocaleString('en-US')}</b> paired run${s.n === 1 ? '' : 's'}; real was worse in <b>${s.worse.toLocaleString('en-US')}</b> (${pct(s.worse, s.n)}).`;
    let html = `<div class="tc-answer" data-tc-answer>${against.map((a) => line(a, this.byAgainst[a])).join('<br>')}`;
    if (deployments.length > 1) {
      html += `<ul class="tc-answer-lines">${this.byDeployment.map(([d, s]) => `<li>${esc(d)}: ${ratioText(s.median)} over ${s.n.toLocaleString('en-US')} pair${s.n === 1 ? '' : 's'}, real worse in ${pct(s.worse, s.n)}</li>`).join('')}</ul>`;
    }
    const filled = rows.filter((r) => r.real_from || r.pred_from).length;
    html += `<span class="tc-mut" style="display:block;margin-top:4px">A pair: one run folder’s real line and its prediction of the same commanded motion; ratio = real ÷ predicted ${label} (> 1: real is worse). A pair stays while any run of its folder passes the rail.` +
      (filled ? ` ${filled.toLocaleString('en-US')} pair${filled === 1 ? '' : 's'} read ${esc(C.acc.fill)} on a side whose run carries no tag.` : '') + '</span></div>';
    this.el.innerHTML = `<div class="tc tc-pairs">${html}</div>`;
  }
  hook() {
    return { kind: 'pairs', n: this.summary.n, median: this.summary.median, worse: this.summary.worse, against: this.against,
      byAgainst: this.byAgainst, byDeployment: this.byDeployment };
  }
}

// ── the Coverage tab ──

// WHY these three of the page's headline numbers on a card: one per question the page answers (how much of each joint's
// range, how much of angle × speed, how much of the workspace); the page holds the rest, labelled as here
const COVERAGE_CARD = ['q_span_median_pct', 'q_qd_visited_mean_pct', 'tool_voxels_visited'];

/** The Coverage tab (feedback fb-5defddb0; Zach, Daily Note 2026-11-23: "integrate this into the viewer ... a page you
    can see standalone or just quickly get there from the traj compare stuff"). One card per deployment whose site wrote
    a coverage page (its own headline numbers, how many of its targets the rail keeps runs of), the picked deployment's
    page embedded below, as written (traj_compare.coverage), and its "Open on its own ↗". WHY the page and not a redraw:
    one coverage viewer, so the tab and the standalone page can never disagree. WHY the counts but not a refiltered page:
    the page counts every target of its deployment once (a target repeated by many runs counts once), and it is written
    with the site; the rail picks which deployment is shown, and the answer says so. */
class CoverageView extends Base {
  static type = 'tc-coverage';
  update(input) {
    this.input = input;
    this.tc = (input.view && input.view.tc) || {};
    this.rows = input.rows || [];
    this.draw();
  }
  onClick(e) {
    const card = e.target.closest('[data-tc-coverage-pick]');
    if (!card || !this.el.contains(card)) return;
    this.pick = card.dataset.tcCoveragePick;
    store.set(this.key('deployment'), this.pick);
    this.draw();
  }
  render() {
    const P = C.coverage || { deployments: [], missing: [] };
    const kept = new Map();
    for (const r of this.rows) {
      if (!kept.has(r.deployment)) kept.set(r.deployment, new Set());
      kept.get(r.deployment).add(r.target_slug);
    }
    this.cards = P.deployments.map((d) => ({
      deployment: d.deployment, of: d.trajectories,
      kept: [...(kept.get(d.deployment) || [])].filter((slug) => Object.prototype.hasOwnProperty.call(d.names || {}, slug)).length,
    }));
    if (this.pick === undefined) this.pick = store.get(this.key('deployment'), null);
    const cardOf = (name) => this.cards.find((c) => c.deployment === name);
    // the pick stays while the rail keeps runs of it (or of no deployment with a page); else the first the rail keeps
    let shown = cardOf(this.pick) && (cardOf(this.pick).kept > 0 || !this.cards.some((c) => c.kept > 0)) ? this.pick : null;
    if (!shown) shown = (this.cards.find((c) => c.kept > 0) || this.cards[0] || {}).deployment || null;
    this.shown = shown;
    const entry = P.deployments.find((d) => d.deployment === shown);
    const card = cardOf(shown);
    if (!this.el.querySelector('.tc-coverage')) {
      // the frame is made once and kept across redraws, so a rail tick never reloads the page inside it
      this.el.innerHTML = '<div class="tc tc-coverage"><div class="tc-cov-head" data-tc-coverage-head></div>' +
        '<iframe class="tc-cov-frame" data-tc-coverage-frame title="Coverage page"></iframe></div>';
    }
    const frame = this.el.querySelector('[data-tc-coverage-frame]');
    const head = this.el.querySelector('[data-tc-coverage-head]');
    if (!entry) {
      head.innerHTML = '<div class="tc-answer" data-tc-answer>No deployment here has a coverage page.</div>';
      frame.hidden = true;
      return;
    }
    const n = (v) => Number(v).toLocaleString('en-US');
    const keptText = card.kept === 0
      ? `the rail keeps no run of its targets right now`
      : `the rail keeps runs of <b>${n(card.kept)}</b> of them`;
    let html = `<div class="tc-answer" data-tc-answer>Coverage of <b>${esc(shown)}</b>: its <b>${n(entry.trajectories)}</b> target trajectories, each once; ${keptText}.` +
      `<span class="tc-mut" style="display:block;margin-top:2px">The page below is the deployment's own coverage page (traj_compare.coverage): it counts every target of the deployment, so a tick picks which deployment it shows, never what it counts. A target view's “Coverage ↗” opens one target's trajectory on it.</span></div>`;
    html += '<div class="tc-cov-cards" role="tablist">';
    P.deployments.forEach((d, i) => {
      const c = this.cards[i];
      const numbers = Object.fromEntries((d.numbers || []).map((x) => [x.key, x]));
      const facts = COVERAGE_CARD.filter((k) => numbers[k]).map((k) => {
        const x = numbers[k];
        return `<span class="tc-cov-fact"><span class="tc-mut">${esc(x.label)}</span> <b>${esc(num3(x.value))}${x.unit ? (x.unit === '%' ? ' %' : ` ${esc(x.unit)}`) : ''}</b></span>`;
      }).join('');
      html += `<button type="button" role="tab" class="tc-cov-card" data-tc-coverage-pick="${esc(d.deployment)}" aria-selected="${d.deployment === shown}">` +
        `<b>${esc(d.deployment)}</b> <span class="tc-mut">${n(d.trajectories)} targets · the rail keeps runs of ${n(c.kept)}</span>${facts}</button>`;
    });
    html += '</div>';
    html += `<div class="tc-cov-bar"><a class="tc-link" data-tc-coverage-open href="${esc(entry.href)}" target="_blank" rel="noopener">Open on its own ↗</a>`;
    if ((P.missing || []).length) {
      html += `<span class="tc-mut">No coverage page for ${P.missing.map(esc).join(', ')}: its site was written without one (write_dataset_report(coverage=True) writes it).</span>`;
    }
    html += '</div>';
    head.innerHTML = html;
    frame.hidden = false;
    if (frame.dataset.src !== entry.href) {
      frame.dataset.src = entry.href;
      frame.src = entry.href;
    }
  }
  hook() {
    return { kind: 'coverage', shown: this.shown, cards: this.cards || [], missing: (C.coverage && C.coverage.missing) || [] };
  }
}

// ── registration (data-ui CONTRACT §1: registerView(type, {name, icon, load})) ──
const VIEWS = [
  [TileView, 'Headline tile', 'gauge'],
  [LeagueView, 'League', 'table'],
  [MatrixView, 'Config × dataset matrix', 'grid'],
  [SweepView, 'Speed sweep', 'chart-line'],
  [TradeoffView, 'Trade-off map', 'chart-scatter'],
  [WorstView, 'Worst targets', 'list'],
  [PairsView, 'Sim against real', 'scale'],
  [CoverageView, 'Coverage', 'grid'],
];
export function registerRunsViews(registerView, config) {
  C = config;
  for (const [cls, name, icon] of VIEWS) registerView(cls.type, { name, icon, load: async () => ({ default: cls, css: CSS }) });
}
